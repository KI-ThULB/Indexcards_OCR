# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Repeatable field groups in extraction templates** — a template field can now hold zero,
  one or many sub-records instead of a single value. Built for the AMIGA Tonband-Karteikarte
  collection, where a card carries an overall title *and* several individual track titles,
  plus one duration per track *and* an overall duration. A flat template collapsed that to
  one title and one duration, losing every track.

  A group is declared through an additive optional `field_groups` side-map keyed by the group
  label, which itself stays an ordinary entry in `fields` — the same mechanism `field_rules`
  and `authority_bindings` already use. Existing scalar-only templates, results, checkpoints
  and exports are unaffected, and their generated prompt is byte-identical to before.

  The extraction prompt tells the model that a group may hold any number of entries, that
  every visible entry must be extracted in document order, that values belonging to the same
  visual row stay in one object, that a missing child value must be left empty rather than
  shifting later values up, and that nothing may be invented or calculated. The
  summary-versus-item distinction is derived from the field names, so for AMIGA the model is
  told explicitly that `Gesamttitel` and `Titel_Tracks[*].Titel` are different things and
  that an overall value must never suppress the individual ones.

  Malformed model output never fails a batch: a group is coerced into safe canonical items —
  only defined children survive, a missing child becomes empty, unknown children are dropped
  and counted rather than widening the schema — and a card that cannot be parsed at all
  yields an empty group plus a validation flag carrying problem codes only, never card
  content.

  Curators edit entries in the Verify cockpit, including adding, removing and reordering
  them, with each structural change audited. The CSV export keeps one row per source card
  and gives a group deterministic numbered columns (`Titel_Tracks_count`,
  `Titel_Tracks_1_Titel_ocr`, … up to `max_items`, which is 20 for AMIGA and 12 for generic
  groups), plus `Titel_Tracks_overflow_json` so entries beyond the frozen width are never
  silently lost. Bulk runs freeze the group definitions alongside the rest of the template
  schema, so the consolidated CSV cannot change shape mid-run.

  A ready-made `AMIGA Tonband-Karteikarte` template ships with the application; the older
  flat `AMIGA Tonbandkartei` template is preserved untouched.
- **Bulk / multi-batch processing** *(opt-in; off unless `BULK_IMPORT_ROOT` is set)* — an
  unattended mode that orchestrates the **existing** batch engine sequentially across many
  source folders and produces one consolidated, provenance-bearing CSV. Built for
  homogeneous collections with an already-tested extraction template: 28 folders of ~500
  machine-written index cards each (~14,000 cards) are processed folder by folder with one
  template, with no mandatory quality-control stop between folders.

  Source images are read from `BULK_IMPORT_ROOT` on a filesystem the backend can see, so
  14,000 files never traverse the browser. Only the root's immediate subfolders are
  offered, folder names are never trusted as paths, and images are **hardlinked** into each
  batch by default (no extra disk for tens of GB of scans) with an automatic per-file
  fallback to copying. Source folders are only ever read: they are never modified, moved or
  deleted, and their files stay byte-identical through processing, failure, retry, purge and
  deletion of the generated batches.

  Each folder becomes an ordinary batch, so per-card QC data is still written and every
  batch remains individually inspectable, exportable and purgeable — only the *mandatory
  stop between folders* is skipped. Folders run strictly sequentially, with the existing
  image-level concurrency and the existing bounded retry unchanged.

  A run can be paused, resumed and cancelled; completed results are always kept. A backend
  restart marks a running job `interrupted` rather than resuming it, and shows the last
  folder, last image and interruption timestamp so an operator can verify state before
  clicking **Resume** — resuming skips completed folders and never re-sends a card that has
  already been extracted. Progress arrives over the existing WebSocket, so a browser reload
  re-attaches to a running job.

  The consolidated CSV is generated server-side and streamed (peak memory is one batch),
  carries `bulk_run_id`, `source_folder`, `source_filename` and `batch_id` alongside the
  usual result/status/confidence and template columns, keeps the established CSV conventions
  (UTF-8 BOM, CRLF, fully quoted, `_ocr`/`_edited`/`_confidence` triplets), and is
  deterministic. A companion failures CSV lists the failed records for selective retry.
  Results should be validated before publication or ingest into authoritative systems.

  New settings: `BULK_IMPORT_ROOT`, `BULK_IMPORT_MODE`, `BULK_CONTINUE_ON_BATCH_ERROR`,
  `BULK_MAX_FOLDERS`, `RATE_LIMIT_BULK_START`. See
  [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) and
  [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

### Fixed
- **Checkpoint format compatibility** — viewing a batch's results used to break resume and
  retry for that batch. Two writers disagreed on the shape of `checkpoint.json`: the OCR
  engine wrote a bare list of result rows, while the results API wrote
  `{"results": [...], "audit": [...]}` **and migrated a legacy list into that shape on
  read**. So a plain `GET /batches/{name}/results` rewrote the file into a shape the
  engine's resume loop could not iterate — it walked the object's keys and then failed with
  `TypeError`, which marked the batch `failed`. Checkpoint I/O now lives in one place
  (`app/core/checkpoint.py`): both shapes are readable, reading never writes (a legacy file
  is upgraded on the next real write), writes are atomic so a crash mid-folder cannot leave
  a truncated checkpoint, and curator audit entries are carried through a resume instead of
  being silently discarded. Checkpoints already on disk keep working.
- **Case-insensitive image extensions** — image files are now detected regardless of
  extension casing (`.JPG`, `.JpG`, `.TIFF`, `.TiF`, …). Previously, uploads with
  uppercase extensions were accepted but batch processing globbed case-sensitively and
  reported "No images found" on case-sensitive filesystems (Linux/WSL). Upload validation,
  batch processing and file enumeration now share a single canonical supported-image check
  (`app/core/images.py`) that normalises the suffix with `path.suffix.lower()`. Original
  filenames are preserved exactly — files are never renamed. Cross-platform safe on
  Linux/macOS/Windows.

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
