# Roadmap

## Phase 1: Backend Foundation (FastAPI Integration)
**Goal:** Implementation of the modular FastAPI service, WebSocket progress tracking, and batch/upload lifecycle logic.
**Plans:** 9 plans
- [x] 01-01-PLAN.md — Core architecture and modularized OcrEngine service.
- [x] 01-02-PLAN.md — Batch lifecycle management, Upload API, and reusable field templates.
- [x] 01-03-PLAN.md — Real-time progress updates via WebSockets and resilient error recovery.
- [x] 01-04-PLAN.md — Gap closure: fix health endpoint double prefix and WebSocket proxy.
- [x] 01-05-PLAN.md — Gap closure: template save/delete UI and image preview with magnifier.
- [x] 01-06-PLAN.md — Gap closure: batch history backend endpoints and frontend dashboard.
- [x] 01-07-PLAN.md — Gap closure: fix asyncio event loop bug + silent failure (BLOCKER).
- [x] 01-08-PLAN.md — Gap closure: temp session cleanup to prevent server pollution (MAJOR).
- [x] 01-09-PLAN.md — Gap closure: larger image preview and magnifier for A5 cards (MINOR).

**Requirements:**
- [x] [BACKEND-01] Initialize FastAPI project structure (app, models, services).
- [x] [BACKEND-02] Refactor `indexcard_ocr.py` into a modular `OcrEngine` class.
- [x] [BACKEND-03] Implement Upload API with Temp-to-Perm lifecycle and naming conventions.
- [x] [BACKEND-04] Implement Batch configuration and Template management.
- [x] [BACKEND-05] Implement WebSocket progress tracking (%, X/Y, ETA, live streaming).
- [x] [BACKEND-06] Implement Error Handling & Recovery (skip-on-error, _errors/ folder).
- [x] [BACKEND-07] Implement Batch History and Resume/Retry functionality.

## Phase 2: Frontend Scaffold & Configuration (React)
**Goal:** Initialize the React frontend, port the "Museum-Ready" design, and implement the Upload/Configure workflow.
**Plans:** 5 plans
- [x] 02-01-PLAN.md — Frontend Foundation & Global Shell.
- [x] 02-02-PLAN.md — Step 1: Upload Workflow & API.
- [x] 02-03-PLAN.md — Step 2: Configuration & Field Management.
- [x] 02-04-PLAN.md — Gap closure: sidebar back-navigation to completed steps.
- [x] 02-05-PLAN.md — Gap closure: sticky floating WizardNav bar for always-visible navigation.

**Requirements:**
- [x] [FRONTEND-01] Initialize React + TypeScript + Tailwind project (Vite-based).
- [x] [FRONTEND-02] Port the "Museum-Ready" design (Parchment theme) to React components.
- [x] [FRONTEND-03] Implement the **Upload** step (Dropzone component + List View).
- [x] [FRONTEND-04] Implement the **Configure** step (dynamic field management + templates).
- [x] [FRONTEND-05] Connect Frontend to Backend (API integration via TanStack Query).

### Phase 02.1: add turbo (INSERTED)

**Goal:** Set up Turborepo monorepo with unified dev commands, migrate to apps/ + packages/ convention, create shared types package with cross-language codegen.
**Depends on:** Phase 2
**Plans:** 3/3 plans complete

Plans:
- [ ] 02.1-01-PLAN.md — Directory restructure (git mv), root package.json + turbo.json, .env path fixes.
- [ ] 02.1-02-PLAN.md — Backend thin package.json wrapper, frontend workspace updates, root setup script.
- [ ] 02.1-03-PLAN.md — Shared types package with JSON Schema codegen (TypeScript + Pydantic).

## Phase 3: Processing & Results (React)
**Goal:** Wire the Processing step to the backend OCR engine via WebSocket with real-time progress and live feed, then display results in an editable data table with summary stats, image thumbnails, retry capability, and CSV/JSON export.
**Plans:** 3 plans

Plans:
- [ ] 03-01-PLAN.md — Backend gaps: cancel support, results/cancel/retry-image endpoints, StaticFiles mount.
- [ ] 03-02-PLAN.md — Processing step: Zustand extension, WebSocket hook, ProgressBar, LiveFeed, cancel, catastrophic failure detection.
- [ ] 03-03-PLAN.md — Results step: TanStack sortable/editable table, thumbnails with lightbox, retry, CSV/JSON export.

### Phase 03.1: Dynamic prompt generation from field definitions with configurable prompt template (INSERTED)

**Goal:** Add an optional `prompt_template` field to templates and batches, wire it through the backend OCR pipeline with `{{fields}}` placeholder substitution, and surface a collapsible prompt editor with live preview in the Configure step UI.
**Depends on:** Phase 3
**Plans:** 3/3 plans complete

Plans:
- [x] 03.1-01-PLAN.md — Schema + codegen + Pydantic models + backend pipeline wiring (batch_manager, ocr_engine, batches endpoint).
- [x] 03.1-02-PLAN.md — Frontend: Zustand store, API layers, PromptTemplateEditor component, ConfigureStep/TemplateSelector/FieldManager integration.
- [ ] 03.1-03-PLAN.md — Gap closure: domain-agnostic default prompt + template save persists prompt_template.

## Phase 6: Merge features of main and current branch
**Goal:** Port features from the main branch (provider selection, OCR resilience, multi-entry results, XML exports, app branding) onto the current branch, resolving divergent implementations via feature interview.
**Plans:** 8 plans

Plans:
- [x] 06-01-PLAN.md — Feature discovery interview (8/9 features accepted, Feature 5 rejected).
- [x] 06-02-PLAN.md — Backend reimplementation (cancel/results/retry, OCR resilience, provider selection).
- [x] 06-03-PLAN.md — Frontend feature porting (provider store, UI, WS reconnect, multi-entry, XML exports, thumbnails).
- [x] 06-04-PLAN.md — Provider selector wiring and model defaults.
- [x] 06-05-PLAN.md — Processing WebSocket reconnect hardening.
- [x] 06-06-PLAN.md — App branding (ThULB logo, Hack the Heritage banner, title rename).
- [x] 06-07-PLAN.md — Gap closure: results table layout restructure + thumbnail DOM performance.
- [ ] 06-08-PLAN.md — Gap closure: textarea for multiline editing, remove duplicate filename column, reorder columns.

## Phase 4: Refinement & Polish
- [ ] Enhance error handling in the GUI (e.g., failed images list).
- [ ] Optimize image resizing logic in the backend.
- [ ] Ensure local persistence for batch history.
- [ ] Final E2E testing of the "Museum-Ready" workflow.

## Phase 5: Advanced Domain Research & Features
- [ ] Research historical handwriting/notations and update the default prompt.
- [ ] Research technical optimizations for VLM (e.g., better image quality vs. cost).
- [ ] Support for additional output formats (JSON-LD, XML).
- [ ] Packaging for local deployment (Docker or portable executable).

## Phase 7: UAT Bug Fixes — Session Lifecycle, Batch Data Isolation, Navigation & Data Quality

**Goal:** Fix all 15 bugs discovered during comprehensive browser-automated UAT audit of the full application workflow (Upload → Configure → Processing → Results → Archive → Export). Bugs are organized into 4 clusters: (A) Session Lifecycle — stale session after batch creation prevents re-processing/resume (BUG-13 HIGH, BUG-15 MEDIUM), (B) Batch Data Isolation — results view uses Zustand fields instead of batch config, breaking all exports (BUG-06 CRITICAL, BUG-07 CRITICAL), (C) Navigation & State Restoration — sidebar guards, template name persistence, toast timing (BUG-01 HIGH, BUG-02 HIGH, BUG-03 MEDIUM, BUG-12 MEDIUM), (D) Data Quality & Cosmetics — batch status/names, trailing newline, LIDO hardcode, page title, WebSocket race (BUG-04, BUG-05, BUG-08, BUG-09, BUG-10, BUG-11, BUG-14).
**Depends on:** Phase 6
**Plans:** 3 plans

Plans:
- [ ] 07-01-PLAN.md — Critical/high bug fixes: batch data isolation (BUG-06/07), session lifecycle (BUG-13/15), batch name uniqueness (BUG-05).
- [ ] 07-02-PLAN.md — Navigation & state restoration: sidebar results navigation (BUG-01/02), template name persistence (BUG-03), toast timing (BUG-12).
- [ ] 07-03-PLAN.md — Data quality & cosmetics: batch status persistence (BUG-04), trailing newline (BUG-08), LIDO hardcode (BUG-09), page title (BUG-10), WebSocket race (BUG-11).

### Phase 8: Validation Rules Engine — per-field regex/vocabulary/LLM-correction rules applied after VLM extraction, surfaced as field status badges in Results and Verify views

**Goal:** Add per-field validation (regex + closed vocabulary + LLM corrector) to the OCR pipeline. Rules attach to field definitions, snapshot at batch creation, run inline during VLM extraction, are re-runnable on demand, and surface as per-cell badges with filter chips and soft-block export gating. LLM corrector is opt-in per batch with a hard call cap, fires only on rule failure, uses a cheap text-only model by default, and always proposes corrections (never silently overwrites). The data shape produced is ready for the Phase 9 Verify cockpit to consume without further changes.
**Depends on:** Phase 7
**Plans:** 3/4 plans executed

Plans:
- [ ] 08-01-PLAN.md — Schema, codegen, model layer: FieldRule + ValidationOutcome additions to JSON Schema, regenerate Pydantic + TS types, mirror in schemas.py and frontend API type copies (null-default backward compat).
- [ ] 08-02-PLAN.md — Backend validation engine + integration: validation/ package (regex, vocab + rapidfuzz, corrector with thread-safe cap), wire into _process_card_sync, snapshot rules into batch config, /revalidate endpoint.
- [ ] 08-03-PLAN.md — Frontend Configure step: ValidationRuleEditor disclosure on each FieldManager row, regex preset library, vocabulary + fuzzy toggle, batch-level corrector toggle + cap, template save/load round-trip.
- [ ] 08-04-PLAN.md — Frontend Results step: ValidationBadge per cell with Accept/Reject, ValidationFilterChips above table, SummaryBanner aggregate counts, sonner soft-block export gate. Emits ResultRow shape Phase 9 will consume.

### Phase 9: Verification Cockpit — side-by-side image/fields workspace as new wizard step with deep-zoom image, per-field verified/corrected status, keyboard navigation, optional ROI overlay

**Goal:** [To be planned]
**Depends on:** Phase 8
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 9 to break down)

### Phase 10: OpenRefine-style Cleaning Stage — column-wise data quality view with fingerprint clustering, bulk transforms, faceting, undo/commit audit log over batch results

**Goal:** [To be planned]
**Depends on:** Phase 9
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 10 to break down)

### Phase 11: Authority Reconciliation — per-field reconciliation against GND/Wikidata/GeoNames/Getty AAT with candidate picker, bulk column mode, cache, and authority URI emission in LIDO/MARCXML/Dublin Core exports

**Goal:** [To be planned]
**Depends on:** Phase 10
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 11 to break down)
