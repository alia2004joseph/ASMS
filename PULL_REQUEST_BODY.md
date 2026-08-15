# Pull request prepared by Copilot

This PR scaffolds the Class Management foundation inside the ASMS repo. It adds a small, reversible skeleton under `class_management/` while making no changes to existing ASMS settings, INSTALLED_APPS, or the database. No migrations are created or applied in this PR.

---

Files added (11):
- class_management/__init__.py
- class_management/representatives/models.py
- class_management/representatives/serializers.py
- class_management/representatives/views.py
- class_management/representatives/urls.py
- class_management/permissions/classes.py
- class_management/notifications/services.py
- class_management/api/urls.py
- docs/class_management/FOUNDATION_README.md
- class_management/tests/test_representatives.py
- class_management/tests/test_permissions.py

---

Summary
-------
This PR implements a non-invasive scaffold for the Class Management module (foundation only). It introduces model, permissions and notification helper skeletons and minimal tests. This is purely a design and review artifact. The full implementation, migrations, and any modifications to `INSTALLED_APPS` or DB schema are intentionally _not_ part of this PR and will only occur after explicit approval.

Architecture & Specification
----------------------------
The scaffold implements the architecture that was frozen and approved. The authoritative implementation specification repository is: docs/class_management/FOUNDATION_README.md and the conversation up to commit ID 5ae8158.

The scaffold corresponds to the following design doc features:
- ClassRepresentativeAssignment model skeleton (design only)
- Permission class placeholders (IsAdminUser, IsClassRepForClassroomOrSubject, IsTeacherForClassroomSubject)
- Notifications helper to call communications.publish in an idempotent, transaction.on_commit manner
- API route placeholders for the proposed /api/class-management/ endpoints (representatives)

What is intentionally NOT implemented
-------------------------------------
- No changes to `settings.py` or `INSTALLED_APPS`.
- No migrations created or run
- No database writes or backfills
- No production logic inside views (views return dry-run messages and empty lists)
- No frontend changes
- No AI or Streamlit code migration

Tests performed
---------------
The scaffold includes minimal import-level smoke tests that validate module importability and the presence of skeleton classes. These tests are intentionally simple and do not touch the DB.

Run commands (suggested):
- python -m pytest class_management/tests -q

Expected results (from local scaffold run):
- All tests in class_management/tests should pass (they are import-level checks)
- No DB access or migrations required for tests

Proposed Migration Plan (next stage — for review and explicit approval)
------------------------------------------------------------------------
If you approve migrations and adding the apps to INSTALLED_APPS, the proposed changes for the next stage are:
1) Add the following apps to `schoolsys/settings.py` INSTALLED_APPS in a single commit (explicit PR step):
   - "class_management.representatives",
   - "class_management.permissions",
   - "class_management.notifications",
   - "class_management.api",
   - (add other class_management apps in subsequent phases: materials, groups, attendance, polls, feedback)

2) Create migrations for new models:
   - Create migration for ClassRepresentativeAssignment model
   - Create migration to EXTEND attendance.AttendanceRecord (add optional session FK) — do this only after we finalize AttendanceSession model in the next phase

3) Staging steps before production:
   - Deploy changes to staging with new INSTALLED_APPS and run migrations on staging DB clone
   - Run full test suite (pytest) and integration tests including attendance marking flows in staging
   - Run small sample migration/dry-run for pre-existing data imports if needed

4) Production deployment plan:
   - Take a backup of production DB
   - Run migrations during a maintenance window
   - Smoke test and run acceptance test plan

Migration safeguards
--------------------
- Keep ClassRepresentativeAssignment migration additive (non-destructive)
- Add AttendanceRecord.session FK as nullable to avoid locking or data loss
- All migrations must be reviewed and a rollback procedure validated (DB backup + migration reversal instructions)

Risks and rollback plan
------------------------
Risks:
- Introducing new apps to INSTALLED_APPS without careful review could create circular import or migration issues.
- Adding an AttendanceRecord FK must be done with care to avoid blocking operations on large tables.
- Email delivery scale issues if synchronous communications.publish is used for large recipient sets.

Rollback plan:
- For any migration that fails, revert to pre-migration tag and restore DB from backup
- For code-level regressions, revert PR merge and redeploy the previous tag

Review checklist (to be completed before any migration or INSTALLED_APPS change)
--------------------------------------------------------------------------------
- [ ] Code review of scaffold files
- [ ] Approval of the detailed implementation specification (the long design doc)
- [ ] Confirmation of comment responses listed in the design doc (announcement policy, thresholds, poll audit policy)
- [ ] Approval to add apps to INSTALLED_APPS and run migrations
- [ ] Schedule a maintenance window and staging deployment for migration

---

I will now open the PR in the GitHub repo and post back the PR link. No further changes will be made until you instruct me.
