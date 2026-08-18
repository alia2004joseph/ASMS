# ASMS Class Management Integration Guide

This guide details how our complete, production-ready Class Management system fits into your existing `class_management` package found in the `me-class-hub-scaffold` / `me-class-hub-migrations` branches of **`alia2004joseph/ASMS`**.

---

## 1. Structure in Your Repository

In your repository branches (`me-class-hub-scaffold` and `me-class-hub-migrations`), you structured the package as:
```
class_management/
├── __init__.py
├── api/
│   └── urls.py
├── notifications/
│   └── services.py
├── permissions/
│   └── classes.py
├── representatives/
│   ├── apps.py
│   ├── models.py
│   ├── serializers.py
│   ├── urls.py
│   └── views.py
└── tests/
    ├── test_permissions.py
    └── test_representatives.py
```

And registered it in `schoolsys/settings.py` as:
```python
INSTALLED_APPS = [
    # ...
    "accounts",
    "schools",
    "academics",
    "grading",
    "attendance",
    "timetable",
    "finance",
    "reports",
    "communications",
    # Class Management representatives app
    "class_management.representatives",
]
```

---

## 2. What We Built to Complete Your System

All files have been built to fill in and complete this exact architecture:

1. **`ClassRepresentativeAssignment`** (in `class_management/representatives/models.py` & `class_management/models_asms_authoritative.py`):
   - Direct foreign key links to `accounts.StudentProfile`, `academics.Classroom`, `academics.ClassroomSubject`, and `academics.AcademicTerm`.
   - Granular permission flags: `can_manage_materials`, `can_manage_attendance`, `can_create_announcements`, `can_create_groups`, `can_create_polls`.

2. **`Announcement` Noticeboard**:
   - Status workflow: `DRAFT` $\to$ `PENDING_REVIEW` $\to$ `PUBLISHED` / `REJECTED`.
   - Automatic immediate publishing for Teachers & Admins; approval queue for Student Class Reps.

3. **`GroupSet` & `StudyGroup` Module**:
   - `RANDOM`, `BALANCED` (by performance), and `MANUAL` team formation.
   - Distinct roles: `MEMBER` and `LEADER`.

4. **`Poll` & `PollVote` Democratic Voting Engine**:
   - Anonymous single-vote security via HMAC-SHA256 voter hash.
   - Proposal voting (Support / Oppose / Abstain).

5. **`StudentFeedback` Grievance Triage Channel**:
   - Category filtering (Academic, Facilities, Timetable, Administrative).
   - Teacher response logs and resolution timestamps.

6. **Gemini 3.7 AI Service** (`class_management/services/ai_service.py`):
   - Contextual Q&A on class materials, automatic feedback summarization, and notice drafting assistance using `google-genai`.

---

## 3. Activation Commands for Your Local Environment

```bash
# 1. Checkout your working branch
git checkout me-class-hub-migrations

# 2. Make and apply migrations
python manage.py makemigrations representatives
python manage.py migrate

# 3. Start development server
python manage.py runserver
```
