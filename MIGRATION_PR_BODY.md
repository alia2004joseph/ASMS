---
# Migration PR: Add ClassRepresentativeAssignment and AttendanceRecord.session_id (proposal)

This PR contains the proposed migration commits for the Class Management foundation. It is intentionally additive and designed to be safe for large production databases. It **does not** apply migrations or modify the database; it only adds migration files and the settings change that will be reviewed.

PR Contents (draft):

1) Update schoolsys/settings.py (proposed change to INSTALLED_APPS):

Add the following local apps to INSTALLED_APPS in the app area (example insertion; exact placement will be reviewed):

INSTALLED_APPS += [
    'class_management.representatives',
    'class_management.permissions',
    'class_management.notifications',
    'class_management.api',
]

This small change is isolated so reviewers can comment on exact placement. If you prefer, we can add only class_management.representatives now and add others later.

2) Migration: class_management/representatives/migrations/0001_initial.py (Create ClassRepresentativeAssignment)

Operations (auto-generated style):
- CreateModel: ClassRepresentativeAssignment
  - fields: id, student_profile FK (accounts.StudentProfile, CASCADE), classroom FK (academics.Classroom, PROTECT, null=True), classroom_subject FK (academics.ClassroomSubject, PROTECT, null=True), academic_term FK (academics.AcademicTerm, PROTECT, null=True), assigned_by FK (AUTH_USER_MODEL, SET_NULL, null=True), assigned_at, is_active (default True), approval_status, notes, revoked_at, revoked_by FK (AUTH_USER_MODEL, SET_NULL, null=True), created_at, updated_at
- AddIndex on (classroom, classroom_subject, is_active)
- AddIndex on student_profile

3) Migration: attendance/migrations/00XX_add_session_id_tmp.py (Add nullable session column)

Operations:
- AddField: attendance.AttendanceRecord.session_id_tmp IntegerField null=True blank=True

This adds a column quickly without adding a FK constraint (fast, non-blocking).

Notes and plan for subsequent steps (not in this PR):
- Optionally add AttendanceSession model and a separate migration for it (in a following PR), then add a FK via a safe two-step process (NOT VALID constraint then VALIDATE) to avoid table locking.
- Add indexes via CREATE INDEX CONCURRENTLY where appropriate.

Runbook & verification instructions (included in PR body):
- How to preview migrations (python manage.py migrate --plan)
- Staging steps to apply safely with tests
- Production backup, migrate, and smoke test plans

Risks & rollback plans (included):
- Potential long-running validation when adding FK constraints — mitigated by NOT VALID approach
- Rollback path: git revert commits and (if needed) DB restore from backups

Review checklist (must be completed before merging this PR):
- [ ] Code review of migration files
- [ ] Confirm dependency names for migrations are correct
- [ ] Confirm the additions to INSTALLED_APPS are acceptable
- [ ] Approve the staging & production runbook and schedule

---

(End of PR body. The migration files themselves are included on the branch in draft form.)
