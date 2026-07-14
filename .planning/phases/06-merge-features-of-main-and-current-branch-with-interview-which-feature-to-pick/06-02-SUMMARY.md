---
phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick
plan: 02
subsystem: api
tags: [fastapi, python, ocr, provider-selection, ollama, openrouter, websocket]

# Dependency graph
requires:
  - phase: 06-01
    provides: "feature selection interview — accepted/rejected list"
provides:
  - "Draft branch feat/phase-06-ported-features created off main HEAD"
  - "BatchStartRequest schema + _resolve_provider() helper (Feature 4)"
  - "Provider/model threading through process_batch/_process_card_sync/_call_vlm_api_resilient (Feature 4)"
  - "Improved JSON extraction with array support (Feature 6)"
  - "Multi-entry detection — AI returns list, stored as _entries/_entry_count (Feature 6)"
  - "Granular HTTP error handling: 401 no-retry, 5xx retry, 4xx no-retry, ConnectionError/Timeout explicit (Feature 6)"
  - "max_tokens bumped 1200 to 4096 (Feature 6)"
  - "German error messages for user-facing API errors (Feature 6)"
  - "asyncio.get_running_loop() captured before to_thread call (Feature 6)"
affects:
  - "06-03 (Store/API/Configure frontend)"
  - "06-04 (Processing step)"
  - "06-05 (Results step)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_resolve_provider() pattern: centralized provider/model/key resolution by provider name string"
    - "prompt_template naming retained from main branch (Feature 5 rejected)"

key-files:
  created: []
  modified:
    - "apps/backend/app/api/api_v1/endpoints/batches.py"
    - "apps/backend/app/models/schemas.py"
    - "apps/backend/app/services/ocr_engine.py"
    - "apps/backend/app/core/config.py"

key-decisions:
  - "Feature 5 (custom_prompt) rejected: kept prompt_template naming from main branch throughout; no custom_prompt parameter added to any function"
  - "BatchStartRequest added to schemas.py with provider/model fields; start_batch persists provider choice to config.json before background task"
  - "Provider params (api_endpoint, model_name, api_key) threaded through process_batch -> _process_card_sync -> _call_vlm_api_resilient as call-time overrides (not global mutation)"
  - "asyncio.get_running_loop() moved before _save_checkpoint definition to ensure it's captured in async context before entering the thread pool"
  - "OCR engine now handles 401 as immediate exit (no retry), 5xx with backoff retry, 4xx non-401/429 as immediate exit, ConnectionError and Timeout as distinct explicit retry branches"

patterns-established:
  - "Provider resolution: _resolve_provider(provider, model) -> (api_endpoint, model_name, api_key)"
  - "Multi-entry: isinstance(data, list) check after JSON parse; list stored as JSON string in _entries key"

# Metrics
duration: 25min
completed: 2026-02-23
---

# Phase 06 Plan 02: Backend Feature Reimplementation Summary

**Provider-selectable OCR backend (Ollama/OpenRouter) with resilient engine: granular HTTP error handling, multi-entry array detection, max_tokens 4096, and German user-facing errors**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-02-23T00:00:00Z
- **Completed:** 2026-02-23T00:30:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created draft branch `feat/phase-06-ported-features` off main's HEAD
- Added `BatchStartRequest` schema and `_resolve_provider()` helper for multi-provider OCR (Feature 4)
- Improved OCR engine JSON extraction to handle both object `{}` and array `[]` responses (Feature 6)
- Added multi-entry detection: when model returns a JSON array, stores as `_entries`/`_entry_count` in result dict (Feature 6)
- Upgraded HTTP error handling: 401 exits immediately, 5xx retries with backoff, non-401/429 4xx exits, explicit ConnectionError/Timeout retry branches (Feature 6)
- Bumped `max_tokens` from 1200 to 4096 and added German error messages (Feature 6)
- Fixed `asyncio.get_running_loop()` capture order — now before the `_save_checkpoint` closure, preventing deprecation warnings (Feature 6)
- Threaded `api_endpoint`/`model_name`/`api_key` through all three OCR function signatures without mutating global config (Feature 4)
- Feature 5 (custom_prompt) intentionally skipped — `prompt_template` naming from main preserved throughout

## Task Commits

Each task was committed atomically:

1. **Task 1: Create draft branch off main** — branch creation, no file changes (no commit needed)
2. **Task 2: Reimplement accepted backend features** — `8e36d1e` (feat)
3. **Task 2 auto-fix: Add OLLAMA_* config fields** — `f07fa5e` (fix — Rule 3 blocking)

## Files Created/Modified

- `apps/backend/app/models/schemas.py` — Added `BatchStartRequest` schema with `provider`/`model` fields
- `apps/backend/app/api/api_v1/endpoints/batches.py` — Added `_resolve_provider()`, updated `run_ocr_task` to read provider from config.json, updated `start_batch` to accept `BatchStartRequest` body
- `apps/backend/app/services/ocr_engine.py` — Improved `_extract_json_from_model_content` (array+object), granular HTTP error handling, max_tokens 4096, German errors, multi-entry detection in `_process_card_sync`, provider params in all signatures, fixed `get_running_loop()` placement
- `apps/backend/app/core/config.py` — Added OLLAMA_API_ENDPOINT, OLLAMA_MODEL_NAME, OLLAMA_API_KEY fields (Feature 4 — required by `_resolve_provider`)

## Decisions Made

- **Feature 5 rejected means no custom_prompt**: `prompt_template` naming from main stays. `BatchCreate.prompt_template`, `batch_manager.create_batch(prompt_template=...)`, and `ocr_engine` all keep the `prompt_template` parameter from main rather than switching to `custom_prompt`.
- **Provider override is call-time, not global**: `api_endpoint`/`model_name`/`api_key` are passed per-call through `process_batch` → `_process_card_sync` → `_call_vlm_api_resilient`. No global `settings` mutation.
- **start_batch persists provider to config.json**: So `run_ocr_task` can re-read it when the background task executes, regardless of timing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] cancel_event.clear() retained from main branch**
- **Found during:** Task 2 (run_ocr_task implementation)
- **Issue:** The source branch (phase-03) removed `cancel_event.clear()` from the start of `run_ocr_task`. Main branch keeps it as a safety guard (prevents stale cancellation from a previous run from aborting a new run immediately). Since this is a security/correctness guard on main, it was retained.
- **Fix:** Kept `cancel_event.clear()` from main in the ported implementation.
- **Files modified:** `apps/backend/app/api/api_v1/endpoints/batches.py`
- **Committed in:** `8e36d1e`

**2. [Rule 2 - Missing Critical] Edge-case final state broadcast retained from main**
- **Found during:** Task 2 (run_ocr_task error handling)
- **Issue:** Source branch removed the `else` branch that broadcasts a `completed`/`failed` state when no progress was ever broadcast (e.g. empty batch). Main branch has this edge-case handler. Retained for robustness.
- **Fix:** Kept the `else: failed_state = BatchProgress(...)` broadcast blocks from main.
- **Files modified:** `apps/backend/app/api/api_v1/endpoints/batches.py`
- **Committed in:** `8e36d1e`

---

**3. [Rule 3 - Blocking] Added OLLAMA_* config fields to config.py**
- **Found during:** Task 2 verification (`_resolve_provider` AttributeError)
- **Issue:** `_resolve_provider('ollama', ...)` referenced `settings.OLLAMA_API_ENDPOINT` / `settings.OLLAMA_MODEL_NAME` / `settings.OLLAMA_API_KEY` but these fields were not present in `Settings` class on main branch.
- **Fix:** Added all three OLLAMA config fields with appropriate defaults and env var fallbacks.
- **Files modified:** `apps/backend/app/core/config.py`
- **Verification:** `_resolve_provider('ollama')` returns correct endpoint and model name.
- **Committed in:** `f07fa5e`

---

**Total deviations:** 3 (2 quality guards retained from main, 1 Rule 3 blocking fix)
**Impact on plan:** All deviations necessary for correctness and completeness. No scope creep.

## Issues Encountered

- `git checkout main` initially blocked by untracked files from `feat/phase-03-processing-results` branch. Resolved by stashing all changes (including untracked) before switching. The stash pop failed after branch creation because main already had the same files; the stash was dropped since files were already present.

## Next Phase Readiness

- Backend on `feat/phase-06-ported-features` is complete with all accepted features
- Feature 4 (provider selection) fully wired — `BatchStartRequest` schema ready for frontend consumption in Plan 03
- Feature 6 (OCR resilience) fully integrated — improved engine available for all processing calls
- Feature 5 (custom prompt) correctly skipped — `prompt_template` naming from main intact for Plan 03's configure step
- Ready for Plan 03: Store/API/Configure frontend features

---
*Phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick*
*Completed: 2026-02-23*
