feat(class-management): scaffold foundation — Class Representative, permissions, notifications glue

This PR introduces the foundation scaffold for the Class Management module inside the ASMS repository. It is intentionally small, reversible, and non-invasive. No existing ASMS settings, authentication, timetable, attendance, communications, or frontend code are modified by this PR. No migrations or database changes are created or applied.

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

Tests performed and results
---------------------------
- Import-level smoke tests included under class_management/tests: they assert that the scaffold modules and permission classes load without requiring DB access.
- Expected results: tests pass locally in a dev environment; they do not require migrations nor DB connections.

Architecture / Specification referenced
--------------------------------------
This scaffold implements elements of the approved Class Management design specification (frozen architecture). See docs/class_management/FOUNDATION_README.md and the project design discussion for the complete implementation specification that will guide future work.

What is intentionally NOT implemented in this PR
------------------------------------------------
- No changes to INSTALLED_APPS or settings.py
- No migrations or DB schema changes
- No modifications to the existing ASMS codebase beyond adding these scaffold files
- No frontend code or UI changes
- No AI code or Streamlit migration
- No production logic in views or services (views return placeholder responses)

Proposed migration changes for next stage (for review & approval)
-----------------------------------------------------------------
If this scaffold is approved, the next stage would include the following explicit changes (subject to a separate approval step):
1) Add apps to INSTALLED_APPS in schoolsys/settings.py: class_management.representatives, class_management.permissions, class_management.notifications, class_management.api (and later: materials, groups, attendance, polls, feedback)
2) Create migrations for ClassRepresentativeAssignment model (add table) and extend attendance.AttendanceRecord with optional session FK (nullable)
3) Deploy to staging and run the full test suite, including integration/E2E tests
4) After staging signoff, run migrations in production during a scheduled maintenance window with backups in place

Risks and rollback plan
-----------------------
Risks:
- Adding new apps and migrations without review risks migration conflicts or runtime import errors.
- Extending large tables (attendance.AttendanceRecord) must be done with care to avoid long locks.
- Synchronous communications.publish for large recipient sets may cause latency spikes; operator should configure async/queue when scaling.

Rollback Plan:
- Revert code changes (Git rollback) and redeploy to previous tag
- Restore DB from backup if needed for failed migrations
- Remove added data or undo partial imports via documented import rollback scripts

Review checklist (must be completed before any migration or INSTALLED_APPS change)
----------------------------------------------------------------------------------
- [ ] Code review of scaffold files
- [ ] Approval of the detailed implementation specification (frozen design doc)
- [ ] Confirm announcement approval policy and threshold settings
- [ ] Approval to add apps to INSTALLED_APPS and run migrations
- [ ] Schedule staging and production deployment windows

Notes
-----
- This PR is intentionally minimal and review-focused. All database-affecting steps are deferred until the review checklist is completed and explicit approval for the migration stage is provided.

