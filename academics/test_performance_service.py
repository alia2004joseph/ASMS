"""
Integration tests for academics.services.performance_service.

These hit the real ORM/test database (sqlite, per project settings) --
no mocking of the calculation logic itself, per the requirement to
verify with actual ORM queries rather than just checking imports pass.

Run:
    pytest academics/tests_performance_service.py -q
"""

from decimal import Decimal

import pytest
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from accounts.models import StudentProfile, User
from academics.models import (
    AcademicTerm,
    AcademicYear,
    Classroom,
    ClassroomSubject,
    StudentEnrollment,
    Subject,
)
from academics.services.performance_service import (
    PerformanceServiceError,
    get_student_performance,
)
from grading.models import (
    Assessment,
    AssessmentType,
    Grade,
    GradeBoundary,
    GradeStatus,
    GradingScale,
)
from schools.models import School


class PerformanceServiceTestBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Test School", code="TS-001")
        self.other_school = School.objects.create(
            name="Other School", code="OS-001",
        )

        self.year = AcademicYear.objects.create(
            school=self.school,
            name="2026",
            start_date="2026-01-01",
            end_date="2026-12-01",
        )
        self.term = AcademicTerm.objects.create(
            school=self.school,
            academic_year=self.year,
            name=AcademicTerm.TermName.TERM_ONE,
            start_date="2026-01-05",
            end_date="2026-04-01",
        )
        self.classroom = Classroom.objects.create(
            school=self.school,
            academic_year=self.year,
            name="Year 1",
            code="Y1",
        )

        self.maths = Subject.objects.create(
            school=self.school, name="Mathematics", code="MATH",
        )
        self.physics = Subject.objects.create(
            school=self.school, name="Physics", code="PHY",
        )

        self.cs_maths = ClassroomSubject.objects.create(
            school=self.school,
            classroom=self.classroom,
            subject=self.maths,
            academic_term=self.term,
        )
        self.cs_physics = ClassroomSubject.objects.create(
            school=self.school,
            classroom=self.classroom,
            subject=self.physics,
            academic_term=self.term,
        )

        self.teacher_user = User.objects.create_user(
            email="teacher@test.school",
            password="x",
            first_name="Terry",
            last_name="Teacher",
            role=User.Role.TEACHER,
            school=self.school,
            is_active=True,
            approval_status=User.ApprovalStatus.APPROVED,
        )

        self.cs_maths.teacher = self.teacher_user
        self.cs_maths.save(update_fields=["teacher"])
        self.cs_physics.teacher = self.teacher_user
        self.cs_physics.save(update_fields=["teacher"])

        self.test_type = AssessmentType.objects.create(
            school=self.school, name="Test", code="TEST",
            weight_percentage=Decimal("30.00"),
        )
        self.exam_type = AssessmentType.objects.create(
            school=self.school, name="Exam", code="EXAM",
            weight_percentage=Decimal("70.00"),
        )

        self.scale = GradingScale.objects.create(
            school=self.school, name="Default Scale", is_active=True,
        )
        GradeBoundary.objects.create(
            scale=self.scale, grade_symbol="A",
            min_percentage=Decimal("80.00"), max_percentage=Decimal("100.00"),
            grade_point=Decimal("5.00"), remark="Excellent",
            is_passing=True,
        )
        GradeBoundary.objects.create(
            scale=self.scale, grade_symbol="B",
            min_percentage=Decimal("60.00"), max_percentage=Decimal("79.99"),
            grade_point=Decimal("4.00"), remark="Good",
            is_passing=True,
        )
        GradeBoundary.objects.create(
            scale=self.scale, grade_symbol="F",
            min_percentage=Decimal("0.00"), max_percentage=Decimal("39.99"),
            grade_point=Decimal("0.00"), remark="Fail",
            is_passing=False,
        )

    def make_student(self, *, email, student_id_number):
        user = User.objects.create_user(
            email=email, password="x", first_name="Student",
            role=User.Role.STUDENT, school=self.school,
            is_active=True, approval_status=User.ApprovalStatus.APPROVED,
        )
        return StudentProfile.objects.create(
            user=user, school=self.school, classroom=self.classroom,
            student_id_number=student_id_number,
        )

    def enroll(self, student, classroom_subject):
        return StudentEnrollment.objects.create(
            student=student, classroom_subject=classroom_subject,
        )

    def grade(self, *, enrollment, assessment, score, status=GradeStatus.APPROVED):
        return Grade.objects.create(
            school=self.school,
            student_enrollment=enrollment,
            assessment=assessment,
            score=score,
            recorded_by=self.teacher_user,
            status=status,
        )

    def assessment(self, *, classroom_subject, assessment_type, title, maximum_score):
        return Assessment.objects.create(
            school=self.school,
            classroom_subject=classroom_subject,
            assessment_type=assessment_type,
            title=title,
            maximum_score=maximum_score,
            assessment_date="2026-02-01",
        )


class TestWeightedCalculation(PerformanceServiceTestBase):
    def test_weighted_subject_score_two_assessment_types(self):
        student = self.make_student(
            email="s1@test.school", student_id_number="S1",
        )
        enrollment = self.enroll(student, self.cs_maths)

        test_a = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.test_type,
            title="Test 1", maximum_score=Decimal("50.00"),
        )
        exam_a = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.exam_type,
            title="Final Exam", maximum_score=Decimal("100.00"),
        )
        # 40/50 = 80% -> weighted 80 * 0.30 = 24.00
        self.grade(enrollment=enrollment, assessment=test_a, score=Decimal("40.00"))
        # 60/100 = 60% -> weighted 60 * 0.70 = 42.00
        self.grade(enrollment=enrollment, assessment=exam_a, score=Decimal("60.00"))
        # total weighted = 66.00, weight covered = 100 -> final = 66.00

        result = get_student_performance(student=student, term=self.term)
        subject = next(
            s for s in result["subjects"] if s["subject_code"] == "MATH"
        )
        self.assertEqual(subject["final_score"], Decimal("66.00"))
        self.assertEqual(subject["grade"], "B")
        self.assertTrue(subject["is_passing"])

    def test_multiple_assessments_same_type_are_averaged_not_summed(self):
        student = self.make_student(
            email="s2@test.school", student_id_number="S2",
        )
        enrollment = self.enroll(student, self.cs_maths)

        t1 = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.test_type,
            title="Test 1", maximum_score=Decimal("100.00"),
        )
        t2 = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.test_type,
            title="Test 2", maximum_score=Decimal("100.00"),
        )
        self.grade(enrollment=enrollment, assessment=t1, score=Decimal("80.00"))
        self.grade(enrollment=enrollment, assessment=t2, score=Decimal("60.00"))
        # avg percentage = 70, weight = 30 -> weighted = 21.00, weight covered = 30
        # final_score normalised = 21.00 / (30/100) = 70.00

        result = get_student_performance(student=student, term=self.term)
        subject = next(
            s for s in result["subjects"] if s["subject_code"] == "MATH"
        )
        self.assertEqual(subject["final_score"], Decimal("70.00"))

    def test_maximum_score_normalisation(self):
        student = self.make_student(
            email="s3@test.school", student_id_number="S3",
        )
        enrollment = self.enroll(student, self.cs_physics)
        a = self.assessment(
            classroom_subject=self.cs_physics, assessment_type=self.exam_type,
            title="Exam", maximum_score=Decimal("40.00"),
        )
        self.grade(enrollment=enrollment, assessment=a, score=Decimal("20.00"))
        # 20/40 = 50%

        result = get_student_performance(student=student, term=self.term)
        subject = next(
            s for s in result["subjects"] if s["subject_code"] == "PHY"
        )
        self.assertEqual(subject["assessments"][0]["percentage"], Decimal("50.00"))


class TestApprovalFiltering(PerformanceServiceTestBase):
    def test_unapproved_marks_excluded(self):
        student = self.make_student(
            email="s4@test.school", student_id_number="S4",
        )
        enrollment = self.enroll(student, self.cs_maths)
        a = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.exam_type,
            title="Exam", maximum_score=Decimal("100.00"),
        )
        self.grade(
            enrollment=enrollment, assessment=a, score=Decimal("90.00"),
            status=GradeStatus.SUBMITTED,
        )

        result = get_student_performance(student=student, term=self.term)
        subject = next(
            s for s in result["subjects"] if s["subject_code"] == "MATH"
        )
        self.assertIsNone(subject["final_score"])
        self.assertEqual(subject["assessments"], [])

    def test_approved_marks_included(self):
        student = self.make_student(
            email="s5@test.school", student_id_number="S5",
        )
        enrollment = self.enroll(student, self.cs_maths)
        a = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.exam_type,
            title="Exam", maximum_score=Decimal("100.00"),
        )
        self.grade(
            enrollment=enrollment, assessment=a, score=Decimal("90.00"),
            status=GradeStatus.APPROVED,
        )

        result = get_student_performance(student=student, term=self.term)
        subject = next(
            s for s in result["subjects"] if s["subject_code"] == "MATH"
        )
        self.assertIsNotNone(subject["final_score"])


class TestCrossSchoolIsolation(PerformanceServiceTestBase):
    def test_cross_school_student_and_term_rejected(self):
        other_year = AcademicYear.objects.create(
            school=self.other_school, name="2026",
            start_date="2026-01-01", end_date="2026-12-01",
        )
        other_term = AcademicTerm.objects.create(
            school=self.other_school, academic_year=other_year,
            name=AcademicTerm.TermName.TERM_ONE,
            start_date="2026-01-05", end_date="2026-04-01",
        )
        student = self.make_student(
            email="s6@test.school", student_id_number="S6",
        )

        with self.assertRaises(PerformanceServiceError):
            get_student_performance(student=student, term=other_term)


class TestMissingAssessmentHandling(PerformanceServiceTestBase):
    def test_missing_assessment_type_reports_partial_weight_covered(self):
        student = self.make_student(
            email="s7@test.school", student_id_number="S7",
        )
        enrollment = self.enroll(student, self.cs_maths)
        t1 = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.test_type,
            title="Test 1", maximum_score=Decimal("100.00"),
        )
        self.grade(enrollment=enrollment, assessment=t1, score=Decimal("90.00"))
        # only "Test" (30%) graded; "Exam" (70%) missing entirely

        result = get_student_performance(student=student, term=self.term)
        subject = next(
            s for s in result["subjects"] if s["subject_code"] == "MATH"
        )
        self.assertEqual(subject["weight_covered_percentage"], Decimal("30.00"))
        # normalised: weighted 27.00 / 0.30 = 90.00
        self.assertEqual(subject["final_score"], Decimal("90.00"))

    def test_no_enrollment_returns_empty_subjects(self):
        student = self.make_student(
            email="s8@test.school", student_id_number="S8",
        )
        result = get_student_performance(student=student, term=self.term)
        self.assertEqual(result["subjects"], [])
        self.assertEqual(result["pass_fail_status"], "NO_SUBJECTS")


class TestGradeAssignment(PerformanceServiceTestBase):
    def test_grade_assigned_from_configured_scale(self):
        student = self.make_student(
            email="s9@test.school", student_id_number="S9",
        )
        enrollment = self.enroll(student, self.cs_maths)
        a = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.exam_type,
            title="Exam", maximum_score=Decimal("100.00"),
        )
        self.grade(enrollment=enrollment, assessment=a, score=Decimal("30.00"))
        # 30% -> F band, weight_covered = 70 (only exam graded)
        # weighted = 30*0.70=21.00, normalised = 21/0.70 = 30.00 -> F

        result = get_student_performance(student=student, term=self.term)
        subject = next(
            s for s in result["subjects"] if s["subject_code"] == "MATH"
        )
        self.assertEqual(subject["grade"], "F")
        self.assertFalse(subject["is_passing"])

    def test_no_active_scale_returns_ungraded(self):
        self.scale.is_active = False
        self.scale.save(update_fields=["is_active"])

        student = self.make_student(
            email="s10@test.school", student_id_number="S10",
        )
        enrollment = self.enroll(student, self.cs_maths)
        a = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.exam_type,
            title="Exam", maximum_score=Decimal("100.00"),
        )
        self.grade(enrollment=enrollment, assessment=a, score=Decimal("90.00"))

        result = get_student_performance(student=student, term=self.term)
        subject = next(
            s for s in result["subjects"] if s["subject_code"] == "MATH"
        )
        self.assertIsNone(subject["grade"])
        self.assertEqual(result["pass_fail_status"], "UNGRADED")


class TestAveragesAndRanking(PerformanceServiceTestBase):
    def _fully_grade(self, student, classroom_subject, exam_score, assessment=None):
        enrollment = self.enroll(student, classroom_subject)
        if assessment is None:
            assessment = self.assessment(
                classroom_subject=classroom_subject,
                assessment_type=self.exam_type,
                title="Exam", maximum_score=Decimal("100.00"),
            )
        self.grade(enrollment=enrollment, assessment=assessment, score=exam_score)
        return enrollment, assessment

    def test_subject_and_overall_average(self):
        student = self.make_student(
            email="s11@test.school", student_id_number="S11",
        )
        self._fully_grade(student, self.cs_maths, Decimal("80.00"))
        self._fully_grade(student, self.cs_physics, Decimal("60.00"))

        result = get_student_performance(student=student, term=self.term)
        # both normalised to 70% weight covered -> 80.00 and 60.00 final scores
        self.assertEqual(result["average"], Decimal("70.00"))

    def test_class_position_and_ties(self):
        top = self.make_student(email="top@test.school", student_id_number="T1")
        mid = self.make_student(email="mid@test.school", student_id_number="T2")
        tie_a = self.make_student(email="tiea@test.school", student_id_number="T3")
        tie_b = self.make_student(email="tieb@test.school", student_id_number="T4")

        _, shared_assessment = self._fully_grade(top, self.cs_maths, Decimal("95.00"))
        self._fully_grade(mid, self.cs_maths, Decimal("70.00"), assessment=shared_assessment)
        self._fully_grade(tie_a, self.cs_maths, Decimal("50.00"), assessment=shared_assessment)
        self._fully_grade(tie_b, self.cs_maths, Decimal("50.00"), assessment=shared_assessment)

        result_top = get_student_performance(student=top, term=self.term)
        result_mid = get_student_performance(student=mid, term=self.term)
        result_tie_a = get_student_performance(student=tie_a, term=self.term)
        result_tie_b = get_student_performance(student=tie_b, term=self.term)

        self.assertEqual(result_top["class_position"], 1)
        self.assertEqual(result_mid["class_position"], 2)
        # tied students share rank 3, next distinct rank would be 5 (1224 rule)
        self.assertEqual(result_tie_a["class_position"], 3)
        self.assertEqual(result_tie_b["class_position"], 3)
        self.assertEqual(result_top["class_size"], 4)


class TestDecimalAndDeterminism(PerformanceServiceTestBase):
    def test_returns_decimal_not_float(self):
        student = self.make_student(
            email="s12@test.school", student_id_number="S12",
        )
        enrollment = self.enroll(student, self.cs_maths)
        a = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.exam_type,
            title="Exam", maximum_score=Decimal("100.00"),
        )
        self.grade(enrollment=enrollment, assessment=a, score=Decimal("33.33"))

        result = get_student_performance(student=student, term=self.term)
        subject = result["subjects"][0]
        self.assertIsInstance(subject["final_score"], Decimal)
        self.assertNotIsInstance(subject["final_score"], float)

    def test_deterministic_for_same_data(self):
        student = self.make_student(
            email="s13@test.school", student_id_number="S13",
        )
        enrollment = self.enroll(student, self.cs_maths)
        a = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.exam_type,
            title="Exam", maximum_score=Decimal("100.00"),
        )
        self.grade(enrollment=enrollment, assessment=a, score=Decimal("77.00"))

        first = get_student_performance(student=student, term=self.term)
        second = get_student_performance(student=student, term=self.term)
        self.assertEqual(first["subjects"][0]["final_score"], second["subjects"][0]["final_score"])

    def test_stable_canonical_response_shape(self):
        student = self.make_student(
            email="s14@test.school", student_id_number="S14",
        )
        result = get_student_performance(student=student, term=self.term)
        expected_keys = {
            "student_id", "term_id", "grading_policy_version",
            "computation_reference", "subjects", "average", "gpa",
            "aggregate", "class_position", "class_size", "class_average",
            "school_average", "subject_positions", "pass_fail_status",
            "performance_summary",
        }
        self.assertEqual(set(result.keys()), expected_keys)


class TestQueryCount(PerformanceServiceTestBase):
    def test_query_count_bounded_for_single_student(self):
        student = self.make_student(
            email="s15@test.school", student_id_number="S15",
        )
        enrollment = self.enroll(student, self.cs_maths)
        a = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.exam_type,
            title="Exam", maximum_score=Decimal("100.00"),
        )
        self.grade(enrollment=enrollment, assessment=a, score=Decimal("80.00"))

        with CaptureQueriesContext(connection) as ctx:
            get_student_performance(student=student, term=self.term)

        # Not asserting an exact number (that's brittle); asserting it does
        # not scale per-assessment/per-grade, i.e. stays small and bounded.
        self.assertLess(len(ctx.captured_queries), 15)


class TestIntegrationWithReportsProvider(PerformanceServiceTestBase):
    def test_reports_provider_setting_resolves_to_this_function(self):
        from django.conf import settings
        from django.utils.module_loading import import_string

        provider = import_string(settings.REPORTS_PERFORMANCE_PROVIDER)
        self.assertIs(provider, get_student_performance)

    def test_reports_performance_history_service_can_call_it_live(self):
        from reports.services import performance_history_service

        student = self.make_student(
            email="s16@test.school", student_id_number="S16",
        )
        enrollment = self.enroll(student, self.cs_maths)
        a = self.assessment(
            classroom_subject=self.cs_maths, assessment_type=self.exam_type,
            title="Exam", maximum_score=Decimal("100.00"),
        )
        self.grade(enrollment=enrollment, assessment=a, score=Decimal("80.00"))

        # reports.services.performance_history_service wraps student/term in
        # its own validation (school_id attributes etc.) -- this exercises
        # the real end-to-end path, not a mock.
        student.school_id = student.school_id  # already set; explicit for clarity
        self.term.school_id = self.term.school_id

        data = performance_history_service.get_current_performance(
            student, self.term,
        )
        self.assertIn("gpa", data)
