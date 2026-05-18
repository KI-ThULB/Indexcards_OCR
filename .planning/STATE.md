# Project State

## Current Phase
Phase 08: Validation Rules Engine — EXECUTING (08-01 complete)

## Current Plan
08: 4 plans across 3 waves — 1/4 complete
- Wave 1: 08-01 (schema + codegen — FieldRule + ValidationOutcome) — DONE (5dc6333, d5a48e3)
- Wave 2: 08-02 (backend engine + integration + /revalidate endpoint) — PENDING; 08-03 (Configure ValidationRuleEditor + corrector toggle + template round-trip) — PENDING
- Wave 3: 08-04 (Results badges, filter chips, SummaryBanner counts, soft-block export) — PENDING

## Recent Milestones
- [x] Codebase exploration completed.
- [x] Initial configuration questions answered.
- [x] `.planning/PROJECT.md` and `config.json` created.
- [x] Phase 1: Backend Foundation (FastAPI Integration) completed.
- [x] Phase 2 Execution Plan created (02-01, 02-02, 02-03).
- [x] Frontend Project Initialized with Parchment Theme & Shell (02-01).
- [x] Step 1: Upload Workflow & Backend API integration (02-02).
- [x] Step 2: Configuration & Field Management (02-03).
- [x] Phase 2: Frontend Scaffold & Configuration (React) completed.
- [x] Phase 02.1 Plan 01: Turborepo monorepo migration (apps/ + packages/ restructure).
- [x] Phase 02.1 Plan 02: Backend package.json wrapper, frontend workspace rename, setup script.
- [x] Phase 02.1 Plan 03: Shared types package with JSON Schema + TypeScript codegen.
- [x] Phase 03 Plan 01: Backend prerequisites for Processing & Results (results/cancel/retry-image + StaticFiles).
- [x] Phase 03 Plan 02: Processing step (React): WebSocket, ProgressBar, LiveFeed, cancel, catastrophic failure.
- [x] Phase 03 Plan 03: Results step (React): sortable/editable table, thumbnails, lightbox, CSV/JSON export.
- [x] Phase 01 Plan 04 (gap closure): Fixed health endpoint double-prefix bug and Vite WS proxy for UAT tests 1 and 5.
- [x] Phase 01 Plan 05 (gap closure): Template Save/Delete UI + ImagePreview with magnifier for UAT test 4.
- [x] Phase 01 Plan 06 (gap closure): Batch History Dashboard — GET /history, DELETE /{name}, BatchHistoryDashboard + BatchHistoryCard, AppView routing.
- [x] Phase 01 Plan 09 (gap closure): Image preview 200px magnifier at 3.5x zoom, 500px max-height for A5 cards.
- [x] Phase 01 Plan 08 (gap closure): Temp session cleanup — startup stale removal + DELETE /upload/{session_id}.
- [x] Phase 01 Plan 07 (gap closure): BLOCKER fix — asyncio event loop capture + silent failure broadcast in batches.py.
- [x] Phase 02 Plan 04 (gap closure): Sidebar back-navigation to completed steps.
- [x] Phase 02 Plan 05 (gap closure): WizardNav sticky bottom navigation bar on Upload, Configure, Results steps.

## Active Tasks
- Phase 07 complete. All 14 in-scope UAT bugs fixed (BUG-14 deferred as prompt engineering out of scope).

## Key Decisions
- **Target Platform:** Web GUI.
- **Backend:** FastAPI (to wrap existing Python logic).
- **Frontend:** React + Tailwind + Vite (Parchment theme).
- **OCR Engine:** Keep Qwen3-VL via OpenRouter.
- **State Management:** Zustand with persistent storage.
- **Aesthetic:** "Museum/Archive" theme with serif fonts and paper textures.
- **Tailwind version:** 3.4 (not 4.x) for stable PostCSS plugin ecosystem.
- **Sidebar navigation:** Display-only; step transitions only via store actions to enforce wizard order.
- **Font loading:** Crimson Text + IBM Plex Mono via Google Fonts CDN import in index.css.
- **Monorepo layout:** apps/frontend, apps/backend, apps/legacy, packages/ (Turborepo convention).
- **Single root .env:** Both frontend (Vite envDir) and backend (pydantic-settings tuple) read from repo root.
- **Local caching only:** No remote Turborepo cache.
- **Task pipeline:** typecheck before build, lint independent, test after build (locked).
- **Atomic migration commit:** Entire directory restructure in single git commit for clean history.
- **Backend npm wrapper: zero npm deps** — all Python deps managed by uv via requirements files to avoid workspace hoisting issues.
- **Port conflict detection:** Inline Node net.createServer in dev scripts (cross-platform, no bash-isms).
- **Frontend test placeholder:** echo 'No tests yet' — turbo won't fail before vitest is wired.
- **Shared types codegen: custom converter** — json-schema-to-typescript generates duplicate helper types; custom jsonSchemaTypeToTs() produces clean inline types without aliases.
- **JSON Schema as source of truth:** Edit .schema.json files for API changes, run turbo generate; never edit generated/ directly.
- **Generated files committed:** generated/ts/index.ts tracked in git so frontend can import without codegen at install time.
- **Cancellation uses threading.Event (not asyncio.Event):** is_set() is thread-safe from ThreadPoolExecutor workers; asyncio.Event is not.
- **cancel_event cleared at top of run_ocr_task:** Ensures fresh state regardless of invocation path (start, retry, retry-image).
- **StaticFiles mount after include_router:** API routes take priority; /batches-static serves data/batches/ directory.
- **Vite ws:true on /api proxy:** WebSocket upgrade for /api/v1/ws/... paths; removed unused /ws entry.
- **Native WebSocket (not react-use-websocket):** avoids React 19 flushSync incompatibility; no new dependency.
- **WebSocket onMessage as callback (not hook state):** hook dispatches directly to Zustand; no re-renders on every WS message.
- **Zustand partialize excludes processingState/results:** prevents localStorage cell-edit performance regression.
- **3-strike catastrophic failure:** closes WS + best-effort cancel + full-screen troubleshooting screen; user returns to configure.
- **Hydrate results from REST (not WS stream):** GET /batches/{name}/results is authoritative; WS can have gaps from reconnects.
- **hydratedRef guard in ResultsStep:** prevents double setResults on React Strict Mode double-invoke.
- **Merge editedData on results hydration:** fresh API data overwrites data fields but editedData map is preserved within session.
- **Tailwind JIT status color lookup map:** static statusStyles object instead of template literals to avoid JIT purge.
- **retryImage navigates to processing step:** single-image retry starts new WS stream; retryBatch used for bulk retry (POST /retry).
- **FastAPI route ordering: /history before /{batch_name}:** path parameters match greedily; static segments must be registered first.
- **AppView in Zustand (wizard|history):** top-level view switch enables history dashboard without a React Router dependency; view persisted in localStorage.
- **loadBatchForReview sets batchId+step+view atomically:** ResultsStep uses existing useResultsQuery(batchId) to hydrate — no new API wiring needed.
- **delete_batch checks disk AND history file:** batch found in either location counts as found; both cleaned up if present.
- **FastAPI router prefix pattern:** include_router(router, prefix='/x') + @router.get('/') resolves to /x (not /x/x); decorator must be '/' not the route name.
- **Vite 7 WS proxy:** rewriteWsOrigin:true required in addition to changeOrigin:true for WebSocket upgrade origin rewriting (http-proxy-3 behaviour).
- **Custom div dropdown for TemplateSelector:** HTML <select> cannot render custom markup inside <option>, so refactored to div-based dropdown with per-row Trash2 delete button.
- **Magnifier uses pure CSS/JS (no library):** Overlaid scaled <img> positioned from cursor's relative x/y in container; 200px lens, 3.5x zoom factor.
- **ImagePreview reads blob URL from Zustand:** Temp session files are not served by StaticFiles; blob URLs created during upload step via URL.createObjectURL. Falls back to placeholder text if undefined.
- **Event loop closure capture for thread-safe WS callbacks:** asyncio.get_running_loop() in async method, closure variable used by worker thread's run_coroutine_threadsafe.
- **Defensive broadcast on all exit paths:** run_ocr_task creates fallback BatchProgress(current=0, total=0) when last_state is None.
- **Modern FastAPI lifespan over deprecated on_event:** asynccontextmanager lifespan is the recommended pattern; on_event("startup") is deprecated.
- **24-hour default for stale session cleanup:** configurable via max_age_hours parameter; runs on every server startup.
- **Sidebar step clickability guard in component (not store):** handleStepClick in Sidebar guards processing/results from sidebar navigation; setStep in store remains unrestricted so loadBatchForReview and other callers work freely.
- **WizardNav uses sticky bottom-0 (not fixed):** nav bar stays within main scroll container and does not overlap the Footer; ProcessingStep excluded from WizardNav.
- **prompt_template uses {{fields}} substitution with append fallback:** if placeholder absent in template, fields block appended after two newlines; null/absent means existing hardcoded German prompt.
- **prompt_template read via config.get() in run_ocr_task:** backward compatibility with existing config.json files that lack the key — no migration required.
- **process_batch prompt_template at end of signature:** avoids breaking existing callers that use positional args for earlier parameters.
- **DEFAULT_TEMPLATE in PromptTemplateEditor matches ocr_engine.py exactly:** null sentinel correctly identifies when user has reset to default; no duplicate string stored.
- **Domain-agnostic default prompt:** "aus dem Bereich Musik" removed from all three prompt locations (PromptTemplateEditor DEFAULT_TEMPLATE, ocr_engine._generate_prompt fallback, config.py EXTRACTION_PROMPT); prompts work for any historical archive card type.
- **prompt_template persisted in template_service:** create_template() passes prompt_template to Template constructor; update_template() uses is-not-None guard matching existing name/fields pattern.
- **PromptTemplateEditor collapsed by default:** non-intrusive for users who don't need prompt customization; power-user feature discoverable via expand toggle.
- **null-means-default pattern throughout:** null in Zustand store = backend uses its own hardcoded German prompt; non-null = custom override sent via API.
- **Feature 5 (custom_prompt) rejected — keep prompt_template from main:** BatchCreate.prompt_template, batch_manager, and ocr_engine all retain the prompt_template naming from main; custom_prompt parameter not added anywhere.
- **Provider resolution via _resolve_provider():** call-time override pattern — api_endpoint/model_name/api_key passed per-call through process_batch → _process_card_sync → _call_vlm_api_resilient; no global settings mutation.
- **OCR resilience improvements:** 401 exits immediately (no retry), 5xx retries with backoff, 4xx non-401/429 exits, ConnectionError/Timeout as distinct explicit retry branches; max_tokens bumped 1200 → 4096.
- **Multi-entry detection:** isinstance(data, list) check after JSON parse; AI-returned array stored as _entries (JSON string) + _entry_count in result dict.
- **asyncio.get_running_loop() before _save_checkpoint closure:** ensures loop captured in async context before entering thread pool.
- **OcrProvider defaults to openrouter in store initialState:** backward compatible with existing sessions; PROVIDER_DEFAULT_MODELS maps provider string to default model.
- **FieldRule inlined in batch.schema.json (not cross-ref from template.schema.json):** codegen script is single-file; duplicate silently skipped at generation time — single FieldRule interface in output.
- **ValidationOutcome re-exported through batchesApi.ts into wizardStore.ts:** avoids circular imports while extending ExtractionResult and ResultRow; validation field rides on the already-excluded-from-partialize results array.
- **startBatch sends explicit provider body:** { provider, model } always sent even for defaults — no ambiguity in backend _resolve_provider().
- **recursive connect() in useProcessingWebSocket:** wsRef.current === ws guard prevents stale closure reconnect; cleaner than previous newWs.onmessage = ws.onmessage assignment.
- **multi-entry virtual filenames:** ${pageFilename}__entry_${idx} used as Zustand updateResultCell key — per-entry edit tracking without schema changes.
- **XML exports fully client-side:** LIDO, EAD, Darwin Core, Dublin Core, MARC21-XML, METS/MODS all generated in-browser from results array; no new backend endpoints.
- **App branding assets via git checkout branch -- path:** ThULB SVG and Hack the Heritage PNG copied directly from feat/phase-03-processing-results without manual download.
- **Header retains main-branch history/archive navigation while adding ThULB logo:** combines best-of-both-branches rather than fully replacing header with source version.
- **Single shared Lightbox in ResultsTable (not per-row):** one lightboxSrc state + one <Lightbox> instance; ThumbnailCell calls onOpenLightbox callback prop — eliminates N Lightbox mount/unmount cycles at 500+ rows.
- **Error message as native browser tooltip on status chip (title attribute):** no separate display area or column; retry button rendered inside status column below chip — no separate actions column.
- **Extraction column uses dl/dd definition list with grid-cols-[auto_1fr]:** all fields as key-value pairs in single table cell; visible fields filter excludes internal _-prefixed fields.
- **ThumbnailCell rewritten as text-link button with Image icon:** zero <img> DOM nodes per row — eliminates DOM explosion at 500+ rows; onOpenLightbox callback prop replaces per-row Lightbox.
- **EditableCell uses auto-resizing textarea:** height='auto' then scrollHeight applied on mount and onChange; resize-none overflow-hidden; Ctrl/Cmd+Enter commits, Escape cancels, plain Enter inserts newline; display uses whitespace-pre-wrap.
- **Entry labels for multi-entry rows moved into Image column:** primary row shows ThumbnailCell + entry badge (flex-col); sub-rows show badge only — filename column eliminated.
- **ResultsTable column order: Image, Status, Time, Extraction:** Extraction (widest) last; Duration moved before Extraction.
- **update_batch_status in try+except separately (not finally):** status value differs per path — "completed"/"cancelled" in success path, "failed" in exception path; finally block cannot determine which status to use.
- **EditableCell trailing newline trim:** draft.replace(/\n+$/, '') strips only trailing newlines before comparing to value — preserves intentional internal newlines in multi-line fields.
- **Karteikarte replaces Tonbandkarteikarte in LIDO export:** generic German archival term for any index card type; previous term was music-archive-specific and incorrect for other collections.
- **WebSocket CONNECTING guard:** set ref.onopen = () => ref.close() when readyState === CONNECTING to avoid "WebSocket is closed before connection is established" browser console warning.

## Last Session
Stopped at: Completed 08-01-PLAN.md — schema foundation for Phase 8 validation rules engine. FieldRule + ValidationOutcome types propagated through all layers. 08-02 and 08-03 (Wave 2 — parallel) are next.

Resume command: /gsd:execute-phase 8 (plans 08-02 and 08-03 can run in parallel in Wave 2)

Pending non-phase-8 work in working tree (untouched, unstaged): apps/backend/app/core/config.py, apps/frontend/src/features/configure/ProviderSelector.tsx, apps/frontend/src/features/results/ResultsStep.tsx, apps/frontend/src/features/results/useResultsExport.ts — pre-existing changes, NOT from this session.

Timestamp: 2026-05-18T12:13:37Z

## Accumulated Context

### Roadmap Evolution
- Phase 02.1 inserted after Phase 2: add turbo (URGENT)
- Phase 02.1 Plan 01 complete: flat frontend/+backend/ migrated to apps/+packages/ Turborepo layout
- Phase 02.1 Plan 02 complete: both apps are full Turborepo workspaces with all turbo task scripts
- Phase 02.1 Plan 03 complete: packages/shared-types with JSON Schema + TypeScript codegen
- Phase 03 Plan 01 complete: backend prerequisites for Processing & Results frontend plans
- Phase 03 Plan 02 complete: ProcessingStep with native WebSocket, ProgressBar, LiveFeed, cancel, 3-strike catastrophic failure, Zustand partialize
- Phase 03 Plan 03 complete: ResultsStep with TanStack Table, editable cells, YARL thumbnails, CSV/JSON export — full wizard end-to-end
- Phase 01 Plan 04 (gap closure) complete: fixed health endpoint double-prefix (/health/health -> /health) and added rewriteWsOrigin:true to Vite proxy for WS upgrade forwarding
- Phase 01 Plan 05 (gap closure) complete: template save/delete UI (SaveTemplateDialog, custom TemplateSelector dropdown, FieldManager Save button) + ImagePreview with 2.5x magnifier in Configure step sidebar
- Phase 01 Plan 06 (gap closure) complete: GET /history + DELETE /{name} backend endpoints, BatchHistoryDashboard React component, AppView Zustand state, sidebar/header navigation
- Phase 01 Plan 09 (gap closure) complete: image preview 200px magnifier at 3.5x zoom, 500px max-height for A5 index card readability
- Phase 01 Plan 08 (gap closure) complete: startup stale session cleanup (24h threshold) + DELETE /upload/{session_id} endpoint for explicit frontend teardown
- Phase 01 Plan 07 (gap closure) complete: BLOCKER fix — asyncio event loop capture in async context + fallback BatchProgress broadcast on all exit paths
- Phase 02 Plan 04 (gap closure) complete: Sidebar clickability enabled for completed steps; handleStepClick guard in Sidebar.tsx; setStep in store remains unrestricted
- Phase 02 Plan 05 (gap closure) complete: WizardNav sticky bottom nav component; inline buttons removed from Upload, Configure, Results steps; ProcessingStep unchanged
- Phase 03.1 inserted after Phase 3: Dynamic prompt generation from field definitions with configurable prompt template (URGENT)
- Phase 03.1 Plan 01 complete: prompt_template added to all 5 data model types (schema, TS, Python, Pydantic) and wired end-to-end through OCR pipeline with {{fields}} substitution and backward-compat fallback.
- Phase 03.1 Plan 02 complete: PromptTemplateEditor React component with live preview, Zustand promptTemplate state, prompt_template wired through all frontend API calls (template save/load + batch creation).
- Phase 03.1 Plan 03 complete: UAT gap closure — removed "aus dem Bereich Musik" from all default prompts (PromptTemplateEditor, ocr_engine, config.py); fixed template_service to persist prompt_template in create/update.
- Phase 06 Plan 01 complete: Feature discovery interview — 8/9 features accepted, Feature 5 (custom_prompt) rejected.
- Phase 06 Plan 02 complete: Branch feat/phase-06-ported-features created off main; backend reimplemented with Features 9 (cancel/results/retry), 6 (OCR resilience), 4 (provider selection + Ollama config).
- Phase 06 Plan 03 complete: Frontend features ported — OcrProvider store (Feature 8), ProviderSelector + ConfigureStep wiring (Feature 4), startBatch with provider/model (Feature 9), recursive WS connect() (Feature 1), Results step with multi-entry expansion + 8 XML exports + hover thumbnails + retryingFilename (Feature 2).
- Phase 06 Plan 06 complete: App branding — ThULB logo link in header, Hack the Heritage banner in sidebar, app title renamed (Feature 7).
- Phase 06 Plan 07 complete: Results table restructure — single Extraction dl/dd column, merged status/retry/error column, shared Lightbox, text-link ThumbnailCell; closes UAT Tests 7 and 9.
- Phase 06 Plan 08 complete: UAT gap closure — EditableCell textarea with auto-resize (Ctrl+Enter commit, Escape cancel, plain Enter newline), filename column removed (entry labels moved to Image column), column order Image/Status/Time/Extraction; closes UAT Tests 1, 5, 7.
- Phase 07 added: UAT Bug Fixes — 15 bugs across 4 clusters (session lifecycle, batch data isolation, navigation, data quality) from comprehensive browser-automated UAT audit.
- Phase 07 Plan 01 complete: Batch data isolation (BUG-06/07) fixed via useMemo field derivation from results data; session lifecycle (BUG-13/15) fixed via batchId guard + explanatory message in ConfigureStep; batch name uniqueness (BUG-05) fixed via time-inclusive default + BatchHistoryCard subtitle.
- Phase 07 Plan 02 complete: Navigation fixes — sidebar Results navigation unlocked when batchId set (BUG-01/02); selectedTemplateName persisted in Zustand store + TemplateSelector initialized from store (BUG-03); file removal toast extended to 10s (BUG-12).
- Phase 07 Plan 03 complete: Data quality fixes — batch status persisted after OCR (BUG-04); EditableCell trims trailing newlines (BUG-08); LIDO export uses generic Karteikarte (BUG-09); page title corrected to "Indexcards OCR" (BUG-10); WebSocket CONNECTING guard prevents console warning (BUG-11). Phase 07 complete.
- Phase 8 added: Validation Rules Engine — per-field regex/vocabulary/LLM-correction rules applied after VLM extraction, surfaced as field status badges in Results and Verify views.
- Phase 9 added: Verification Cockpit — side-by-side image/fields workspace as new wizard step with deep-zoom image, per-field verified/corrected status, keyboard navigation, optional ROI overlay.
- Phase 10 added: OpenRefine-style Cleaning Stage — column-wise data quality view with fingerprint clustering, bulk transforms, faceting, undo/commit audit log over batch results.
- Phase 11 added: Authority Reconciliation — per-field reconciliation against GND/Wikidata/GeoNames/Getty AAT with candidate picker, bulk column mode, cache, and authority URI emission in LIDO/MARCXML/Dublin Core exports.
- Phase 8 CONTEXT captured (commit e849e9b): 4 areas — rule storage on field defs + inline + snapshot + inline outcomes; corrector fires only on rule fail with cheap text-only model and always-propose policy + opt-in batch cap; preset library (year/year-range/ISO+German dates/GND/RKD/AAT/VIAF/configurable prefix/required) + custom regex; vocab case-insensitive exact + opt-in fuzzy with NFC/casefold/diacritic-fold normalization; per-cell badges + filter chips + soft-block export + SummaryBanner counts.
- Phase 8 RESEARCH complete (commit b1c421a): schema-first 5-file pattern (mirrors prompt_template), exact insertion point at ocr_engine._process_card_sync line ~309, _resolve_provider NOT needed for corrector (always OpenRouter text-only via new CORRECTOR_MODEL_NAME), three frontend touchpoints (FieldManager disclosure, ResultsTable dd wrap, useResultsExport sonner gate), one new dep (rapidfuzz), critical pitfall: batchesApi.ts has local TS type copies needing manual update.
- Phase 8 PLANNED (commit dccec3f) — 4 plans across 3 waves: 08-01 schema/codegen → 08-02 backend engine + 08-03 frontend Configure (parallel) → 08-04 frontend Results + export gate. Verified PASSED by gsd-plan-checker (all CONTEXT decisions covered, schema-first sequencing holds, threading pitfalls flagged in plan actions, batchesApi.ts type-copy issue addressed in 08-01 T2). One info note: image-fallback corrector deferred from v1.
- Phase 8 Plan 01 complete (commits 5dc6333, d5a48e3): FieldRule + ValidationOutcome JSON Schema definitions added to template.schema.json + batch.schema.json; turbo generate regenerated generated/ts/index.ts (FieldRule, ValidationOutcome, field_rules, corrector_enabled, corrector_cap, validation in all relevant interfaces); Pydantic models mirrored in schemas.py; batchesApi.ts + templatesApi.ts + wizardStore.ts extended. Python smoke test and TypeScript --noEmit both pass. Backward compat confirmed.
- Phases 9, 10, 11 directories exist but are unplanned (TBD goals, no CONTEXT/RESEARCH/PLAN files).

### Performance Metrics
| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 02.1  | 01   | ~3min    | 3     | 53    |
| 02.1  | 02   | ~2min    | 3     | 5     |
| 02.1  | 03   | ~15min   | 2     | 10    |
| 03    | 01   | ~8min    | 2     | 5     |
| 03    | 02   | ~2min    | 2     | 7     |
| 03    | 03   | ~3min    | 2     | 7     |
| 01    | 04   | ~5min    | 1     | 2     |
| 01    | 05   | ~2min    | 2     | 6     |
| 01    | 06   | ~5min    | 2     | 9     |
| 01    | 09   | <1min    | 1     | 1     |
| 01    | 08   | ~2min    | 2     | 3     |
| 01    | 07   | ~2min    | 2     | 2     |
| 02    | 04   | ~2min    | 1     | 1     |
| 02    | 05   | ~5min    | 2     | 4     |
| 03.1  | 01   | ~4min    | 2     | 9     |
| 03.1  | 02   | ~5min    | 2     | 7     |
| 03.1  | 03   | ~2min    | 2     | 4     |
| 06    | 01   | ~5min    | 1     | 0     |
| 06    | 02   | ~30min   | 2     | 4     |
| 06    | 03   | ~35min   | 6     | 10    |
| 06    | 06   | ~5min    | 1     | 4     |
| 06    | 07   | ~3min    | 2     | 2     |
| 06    | 08   | ~5min    | 2     | 1     |
| 07    | 01   | ~8min    | 2     | 3     |
| 07    | 02   | ~5min    | 2     | 5     |
| 07    | 03   | ~5min    | 2     | 6     |
| 08    | 01   | ~3min    | 2     | 9     |

## Blockers
- None.
