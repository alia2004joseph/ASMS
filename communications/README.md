# Communications App

School-scoped announcements, notices and emergency broadcasts with
in-app and email delivery, read/acknowledgement tracking, templates and
notification preferences.

## Status: Version 1 (backend)

Implemented: Communication lifecycle (draft → submit → approve/reject →
schedule → publish → deliver → complete/cancel/expire), audience
targeting (school-wide, role-wide, classrooms, selected users, guardians
of targeted students), frozen recipient snapshots, in-app + email
delivery, inbox, unread counts, read/acknowledge, templates with safe
variable substitution, notification preferences, attachments.

Not implemented in V1 (documented, not faked): SMS/WhatsApp providers
(no credentials configured — `deliver_communication` marks those
channels `skipped` with a reason rather than pretending delivery
succeeded), direct messaging/conversation threads, Celery-based async
delivery (this repo has no Celery/Redis configured — delivery currently
runs synchronously via `transaction.on_commit` right after publish; see
"Adding Celery" below for how to move it behind a task queue without
changing the service functions' contracts). This repo also has no
frontend directory, so no React work is included here.

## Data model

- `Communication` — the announcement/notice/broadcast itself.
- `CommunicationAttachment` — validated file attachments (pdf/docx/png/jpg).
- `CommunicationRecipient` — one row per (communication, recipient, channel);
  the frozen, auditable delivery/read/acknowledgement record.
- `CommunicationTemplate` — reusable subject/body templates with an
  explicit allow-list of substitutable variables.
- `NotificationPreference` — per-user optional-channel settings.

Audience targeting is a hybrid: `audience_type` selects a role-wide or
custom scope; `target_classrooms` / `target_users` (validated FKs, not
raw JSON IDs) narrow it further; `include_guardians_of_targets` pulls in
linked guardians. Recipients are only resolved and frozen into
`CommunicationRecipient` rows at publish time (`services.publish` →
`services.freeze_recipient_snapshot`), so later roster changes never
rewrite historical delivery records. `services.resolve_recipients` has a
defence-in-depth check that raises rather than silently drops any
resolved user outside the communication's own school.

## Workflow / permissions

| Action | Admin | Teacher | Accountant | Student/Guardian |
|---|---|---|---|---|
| Create draft | ✅ any type/audience | ✅ own classrooms/users only, no `emergency`, no school-wide | ✅ `finance` type only | ❌ |
| Submit | ✅ (auto-drafts, no approval needed) | ✅ (requires approval) | ✅ (requires approval) | ❌ |
| Approve/reject | ✅ | ❌ | ❌ | ❌ |
| Publish | ✅ | ✅ once approved | ✅ once approved | ❌ |
| Cancel | ✅ own school | ✅ own drafts | ✅ own drafts | ❌ |
| Emergency broadcast | ✅ only | ❌ | ❌ | ❌ |
| Read/acknowledge inbox | ✅ | ✅ | ✅ | ✅ own items only |

Enforced in `communications/permissions.py` (endpoint-level) and
`communications/services.py::_enforce_role_scope_rules` /
`has_object_permission` (object- and business-rule-level, since teacher
classroom-scope and accountant type-restriction depend on the specific
communication, not just the route).

## API

All under `/api/communications/`:

```
GET/POST            communications/
GET/PATCH           communications/{id}/
POST                communications/{id}/submit/
POST                communications/{id}/approve/
POST                communications/{id}/reject/          {reason}
POST                communications/{id}/schedule/         {scheduled_at}
POST                communications/{id}/publish/
POST                communications/{id}/cancel/
GET                 communications/{id}/recipients/
GET                 communications/{id}/delivery-summary/
GET                 communications/{id}/acknowledgements/
POST                communications/{id}/send-reminder/
GET/POST            attachments/
GET/POST            templates/          , templates/{id}/
GET                 inbox/              , inbox/{id}/
POST                inbox/{id}/read/
POST                inbox/{id}/acknowledge/
POST                inbox/mark-all-read/
GET                 unread-count/
GET/PATCH           preferences/me/
```

## Adding Celery later

`services.publish` currently schedules `services.deliver_communication`
via `transaction.on_commit`, executed in-process. To move to Celery:
add a `@shared_task` wrapping `deliver_communication(communication_id)`
(stable ID, not a serialized instance — required for retry safety), and
change the `transaction.on_commit` call in `publish()` to
`.delay(communication.id)` instead of a direct call. `deliver_communication`
is already idempotent (only acts on `PENDING` recipient rows via
`get_or_create`), so retries won't duplicate deliveries. Add `CELERY_*`
settings and a `celery.py` app entrypoint per the standard Django+Celery
pattern; none of that exists in this repo yet.

## Environment variables

None required for V1 (in-app + Django's console/SMTP email backend,
whichever `EMAIL_BACKEND` is already configured in `schoolsys/settings.py`).
When SMS/WhatsApp providers are approved, their credentials should be
read via `python-decouple`/env vars — never hardcoded — following the
same pattern as any future provider settings.

## Testing

```
python -m pytest communications
```

24 tests: model constraints/defaults, audience resolution + cross-school
rejection + deduplication, full workflow (draft→submit→approve/reject→
publish→cancel), idempotent delivery snapshot, acknowledgement flow,
API-level permission and school-isolation checks, inbox/unread-count
behavior. No test sends a real email (Django's test runner uses the
locmem backend automatically).

## Known limitations / future phases

- No conversation/direct-messaging model yet (V1 intentionally scoped to
  broadcast-style communications per the safeguarding guidance — student-
  to-student messaging should stay disabled until a threaded-conversation
  model with participant validation is added).
- No SMS/WhatsApp provider implementation (interfaces only, via the
  `channel` enum on `CommunicationRecipient`; unconfigured channels are
  marked `skipped`, never faked as delivered).
- No Celery — delivery is synchronous within the publishing request's
  `on_commit` hook, which is fine for the free/dev tier of a single
  small-to-medium Ugandan school but should move to a task queue before
  onboarding schools with large rosters.
- No frontend — this repository is backend-only; the previously-delivered
  ASMS React app lives elsewhere and would need its own Communications
  section (dashboard, list/filter, create/edit form, approval queue,
  inbox, template manager) wired to the endpoints above.
