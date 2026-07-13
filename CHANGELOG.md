# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-07-13

### Added
- **Confidence scoring** — the VLM self-reports a per-field and a card-level overall
  confidence, surfaced as a 0–100% score with a green/amber/red band. The results table
  gains a sortable "Ø Konf." column and per-field confidence chips (also in the Verify
  cockpit) for triage. CSV/JSON exports carry the confidence scores; XML formats stay
  value-only. Confidence is a QA signal, not ground truth.
- **Picture description** *(opt-in per batch)* — when a card carries a picture, drawing, or
  photo, the VLM writes a short description into a dedicated `Bildbeschreibung` field. Toggled
  per batch in Configure via `describe_pictures`.
- Configurable VLM request timeout.

### Changed
- Both new OCR features ride the existing single VLM call — no extra API round-trip.
- Parsing of the VLM response is defensive: a model that ignores the confidence contract still
  yields usable fields (legacy flat shape), so extraction never breaks on response shape.

### Notes
- Backwards compatible: batches processed before v1.1 render with no confidence column and no
  picture field; the toggle defaults off.

## [1.0.0] - 2026-05-18

### Added
- **Configurable OCR provider** — point the app at a self-hosted Ollama instance purely through
  the backend `.env` (no code change, no frontend rebuild); installed models auto-discovered
  server-side and filtered to vision-capable ones, with an optional allow-list.
- **Data protection (GDPR)** — configurable retention policy (auto-purge completed batches,
  opt-in) with dry-run preview and explicit per-batch purge, plus an append-only security audit
  log of privacy-relevant events (audit items I-2 / I-3).
- **Validation rules engine** (phase 8) — per-field regex / vocabulary / LLM-corrector rules
  applied after VLM extraction, surfaced as field-status badges in Results and Verify.
- **Verification cockpit** (phase 9) — side-by-side deep-zoom image and inline-editable fields
  as a new wizard step, with keyboard navigation and verified/corrected status.
- **OpenRefine-style cleaning stage** (phase 10) — column-wise data-quality view with
  fingerprint clustering, faceting, seven bulk transforms, per-operation undo, and a persistent
  audit log.
- **Authority reconciliation** (phase 11) — per-field reconciliation against GND, Wikidata,
  GeoNames, and Getty AAT, with a candidate picker, bulk column mode, cache, and authority-URI
  emission in LIDO / MARCXML / Dublin Core exports.

### Security
- **Backend hardening against penetration-test findings W-01…W-08:**
  - Optional env-gated bearer-token auth on the JSON API + WebSocket `?token=` (constant-time
    compare); default bind `127.0.0.1`.
  - Central path-traversal validators (uuid4 session ids, `[A-Za-z0-9._-]` names/filenames,
    `safe_join` anchor) in `core/security.py`.
  - Stored-XSS + upload hardening: validated image route (extension whitelist, explicit
    content-type, `nosniff`); upload extension + magic-byte check with size/count caps.
  - WebSocket Origin allow-list + token check before `accept()` (close 1008 on failure).
  - Single-active-run-per-batch lockfile (409 on concurrent start/retry) + slowapi rate limits.
  - Generic 500s (no exception leakage); OpenAPI/docs gated behind `ENABLE_DOCS`.
  - Security-header middleware (CSP, nosniff, Referrer-Policy, X-Frame-Options); optional strict
    CORS.
  - Pinned `requirements.txt` with `==` for reproducibility and CVE control.

### Fixed
- v1.0 milestone audit: closed four cross-phase integration wiring breaks (phase 12) — authority
  bindings forwarding in templates, `edited_data` round-trip, CleanStep reconciliation clearing,
  and CockpitBadge reconciliation badge.
- WebSocket allow-list accepts the backend origin so the Vite dev proxy works.

[Unreleased]: https://github.com/KI-ThULB/Indexcards_OCR/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/KI-ThULB/Indexcards_OCR/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/KI-ThULB/Indexcards_OCR/releases/tag/v1.0.0
