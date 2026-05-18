# Requirements

**Milestone v1.0 coverage:** 5/9 satisfied · 4/9 partial (FR2, FR4, FR5, NFR4 — gap closure in progress via Phases 12 + 13)

## Functional Requirements

### FR1: Image Upload (Drag & Drop)
*Status: satisfied (Phases 01, 02)*
- [x] Users can upload single or multiple JPG/JPEG images of index cards.
- [x] Users can remove uploaded files before processing.
- [x] Support for large batches (at least 100 images per session).

### FR2: Metadata Field Configuration
*Status: partial — authority_bindings round-trip broken at template_service layer. Gap closure: Phase 12 T1.*
- [x] Users can define a list of fields to be extracted (e.g., Inventory No, Object Name, Date).
- [x] Field names will dynamically update the VLM prompt.
- [x] Ability to enable/disable or delete predefined/custom fields.
- [ ] Field-level configuration (rules, prompt template, authority bindings) round-trips through template save/load. *Blocked: template_service.create_template/update_template drops authority_bindings.*

### FR3: OCR Processing & Progress Tracking
*Status: satisfied (Phases 01, 03, 06)*
- [x] Backend must process images using the Qwen3-VL model via OpenRouter.
- [x] Real-time progress updates (percentage completed) shown in the GUI.
- [x] Resilient handling of API rate limits and errors (inherited from `indexcard_ocr.py`).

### FR4: Results Visualization & Export
*Status: partial — 3 cross-phase wiring breaks. Gap closure: Phase 12 T2 (clear_reconciliation PATCH), T3 (CockpitBadge reconciliation icon), via T1 cascade.*
- [x] Summary of results shown after processing (Success/Fail counts, duration).
- [x] Ability to download the extracted data as a CSV file.
- [x] CSV format must be compatible with collection management systems (UTF-8 with BOM for Excel compatibility).
- [x] Validation badges + filter chips + soft-block export gate (Phase 08).
- [x] Verify cockpit per-field verified/corrected status (Phase 09).
- [x] OpenRefine-style cleaning stage (Phase 10).
- [ ] Authority URI emission round-trip across cockpit + bulk-reconcile clears + URI badge in all views. *Blocked: handleCellReconciled(null) PATCH omits clear_reconciliation; CockpitBadge missing Link2 icon; FR2 cascade affects URI emission path.*

### FR5: Local Storage / Persistence
*Status: partial — edited_data PATCH writes never read back. Gap closure: Phase 12 T4.*
- [x] Processing results and logs should be stored locally (e.g., in `output_batches/`).
- [x] checkpoint.json `{results, audit}` shape with auto-migration (Phase 10).
- [x] Per-batch authority_cache.json (Phase 11).
- [ ] Curator edits (edited_data) round-trip through PATCH endpoint → checkpoint.json → frontend hydration on reload. *Blocked: ExtractionResult lacks edited_data field; frontend rebuilds from Zustand localStorage only.*

## Non-Functional Requirements

### NFR1: Performance
*Status: satisfied (Phases 01, 06)*
- [x] Multi-threaded processing on the backend for faster extraction.
- [x] Optional image resizing before upload to reduce API latency and cost.

### NFR2: Usability
*Status: satisfied (Phases 02, 03, 09)*
- [x] Responsive web interface matching the "Museum-Ready" prototype aesthetic.
- [x] Clear error messaging for failed API calls or invalid images.

### NFR3: Security
*Status: satisfied (Phase 01)*
- [x] API keys should be handled via environment variables (`.env`).
- [x] The web server should run locally by default (for privacy-conscious institutions).

### NFR4: Maintainability
*Status: partial — shared-types codegen pipeline orphaned. Gap closure: Phase 13.*
- [x] Modular architecture separating the OCR engine logic from the web API.
- [ ] Schema-first codegen pipeline from `packages/shared-types/schemas/` is the single source of truth. *Blocked: Phase 9 (ResultPatch), Phase 10 (AuditEntry), Phase 11 (AuthorityBinding + ReconciliationOutcome) shapes never added to JSON Schema; generated/ directories never imported; parallel hand-written copies in batchesApi.ts + schemas.py are de-facto truth.*
- [x] Clear documentation on how to update fields or prompts.

## Traceability Table

| Req | Status | Satisfied by | Partial Reason | Gap Closure Phase |
|-----|--------|--------------|----------------|-------------------|
| FR1 | satisfied | 01, 02 | — | — |
| FR2 | partial | 01, 02, 08, 11 | template_service drops authority_bindings | Phase 12 (T1) |
| FR3 | satisfied | 01, 03, 06 | — | — |
| FR4 | partial | 03, 06, 08, 09, 10, 11 | clear_reconciliation PATCH bug + CockpitBadge missing icon + FR2 cascade | Phase 12 (T2, T3) |
| FR5 | partial | 01, 10, 11 | edited_data PATCH round-trip incomplete | Phase 12 (T4) |
| NFR1 | satisfied | 01, 06 | — | — |
| NFR2 | satisfied | 02, 03, 09 | — | — |
| NFR3 | satisfied | 01 | — | — |
| NFR4 | partial | 01, 02.1 | shared-types codegen pipeline bypassed for Phase 9/10/11 shapes | Phase 13 |
