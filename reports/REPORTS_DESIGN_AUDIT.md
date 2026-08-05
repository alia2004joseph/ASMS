# Reports Module — Design System Audit

## Scope of this pass
Inspected: models, serializers, services, viewsets, exporters, and every
template under `reports/templates/reports/`, including the shared design
system (`shared/_base_styles.html`, `_header_letterhead.html`, `_footer.html`,
`_qr_block.html`, `_signature_block.html`, `_stamp_block.html`).

## Key finding
`_base_styles.html` is the single stylesheet included once at the top of
every document (`report_card`, `transcript`, `fee_clearance`,
`seating_list`, `permit`, `result_slip`, `certificate`). However, five of
the six shared partials — the letterhead, footer, QR verification block,
signature block, and stamp block — used their own BEM-style class names
(`.qr-block__frame`, `.signature-block__image`, `.doc-header--professional`,
etc.) that were **never defined anywhere in the CSS**. Every document using
these shared fragments (report cards, transcripts, fee clearance
statements, seating lists, permits, result slips) was rendering them
completely unstyled — no borders, spacing, alignment, or typography — even
though the underlying data and logic were correct.

Certificates were unaffected because that template defines its own
self-contained inline styles rather than using the shared partials.

## Fix applied
Added a matching, production-quality CSS module to `_base_styles.html`
covering all classes referenced by the five shared partials:
- Professional multi-column letterhead layout (logo, identity, secondary
  logo, motto, contact lines, registration/accreditation line, rule).
- Two-column footer (school + contact info / generated timestamp) with a
  security notice and metadata line (ref, version, generated-by).
- QR verification block (image + heading + document number + verification
  code chip + URL + instructions), matching the certificate's verification
  panel styling.
- Signature block with left/center/right zone variants, image area,
  signature line, name/credentials/title/department, and a verified badge.
- Stamp block with five position variants (top-left/right, center,
  bottom-left/right) for absolute placement over the document.

All new rules reuse the existing branding variables
(`branding.colors.primary`, `branding.colors.accent`, `branding.font_family`)
so schools' custom branding continues to flow through automatically — no
hardcoded colors were introduced.

## Verified
- Rendered all five shared partials plus the full stylesheet through
  Django's template engine standalone with representative context — no
  template errors.
- Confirmed via `git diff` that no existing selector, block, or template
  file was removed — this is a additive-only change.

## Noted for follow-up (not yet changed, flagging for visibility)
- `report_card/document.html` and `result_slip/document.html` both expose
  a `position` context variable for the student's class rank. The shared
  `_signature_block.html` also reads `position.zone` / `position.alignment`
  for its own layout placement. Because Django's `{% include %}` inherits
  the full parent context, these two names currently collide. No template
  today explicitly sets a signature `position` dict in those two report
  types, so the collision is currently latent (the signature block simply
  falls back to its default left-aligned layout) rather than a visible
  defect — but it should be resolved before either template intentionally
  passes a signature zone. Recommended fix: rename the shared partial's
  context key to `signature_position` and update the handful of call sites
  once a caller needs it.
- Certificates already carry a fully self-contained, superb design; a
  future pass could extract shared pieces (info-strip, verification panel)
  from the certificate template into the shared partials so all seven
  document types converge on one design system with zero duplicated CSS.
