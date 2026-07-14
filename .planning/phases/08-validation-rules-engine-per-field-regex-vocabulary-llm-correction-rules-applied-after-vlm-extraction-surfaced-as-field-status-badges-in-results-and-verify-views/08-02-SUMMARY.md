---
phase: 08-validation-rules-engine
plan: 02
subsystem: backend
tags: [validation, regex, vocabulary, corrector, rapidfuzz, pipeline, revalidate]

# Dependency graph
requires:
  - phase: 08-01
    provides: FieldRule and ValidationOutcome Pydantic models in schemas.py
provides:
  - apps/backend/app/services/validation/ package (presets, regex_rules, vocab_rules, corrector, runner)
  - rapidfuzz dependency in requirements.txt
  - CORRECTOR_MODEL_NAME/MAX_TOKENS/TIMEOUT_SECONDS in config.py Settings
  - batch_manager.create_batch snapshots field_rules/corrector_enabled/corrector_cap into config.json
  - template_service persists field_rules on create/update
  - ocr_engine.process_batch accepts + threads validation params; _process_card_sync runs run_validation and emits validation key
  - POST /api/v1/batches/{batch_name}/revalidate endpoint
affects:
  - 08-03 (frontend rule editor sends field_rules to create_batch — backend now receives and persists them)
  - 08-04 (results badges read validation key from checkpoint.json — now populated)

# Tech tracking
tech-stack:
  added:
    - "rapidfuzz (latest ^3.x) — Levenshtein fuzzy matching for opt-in vocabulary rule"
  patterns:
    - "Validation package: presets.py as compile-time constant list (not JSON file); lru_cache-compiled regex; unicodedata diacritic-fold for NFC+casefold+strip-combining-marks normalization"
    - "Thread-safe corrector cap: mutable cap_state dict with threading.Lock passed through process_batch -> _process_card_sync -> run_validation -> invoke_corrector"
    - "Corrector uses requests.post to settings.API_ENDPOINT (always OpenRouter text-only); never raises — all exceptions returned as invalid status with rationale"
    - "config.get() backward compat pattern in run_ocr_task for field_rules/corrector_enabled/corrector_cap"

key-files:
  created:
    - apps/backend/app/services/validation/__init__.py
    - apps/backend/app/services/validation/presets.py
    - apps/backend/app/services/validation/regex_rules.py
    - apps/backend/app/services/validation/vocab_rules.py
    - apps/backend/app/services/validation/corrector.py
    - apps/backend/app/services/validation/runner.py
  modified:
    - apps/backend/requirements.txt
    - apps/backend/app/core/config.py
    - apps/backend/app/services/batch_manager.py
    - apps/backend/app/services/template_service.py
    - apps/backend/app/services/ocr_engine.py
    - apps/backend/app/api/api_v1/endpoints/batches.py

key-decisions:
  - "GÖTHE diacritic-folds to 'gothe' not 'goethe': the plan's test assertion was mathematically incorrect (Ö -> o via NFD strip). Implementation is correct; test assertion corrected to match actual normalize_value behavior"
  - "Multi-entry results (JSON array from VLM) get validation: null for v1 — plan states 'simplest path: run validation only on the single-dict case; list-entries get validation: null'"
  - "/revalidate runs synchronously for v1 — plan explicitly states synchronous as the simpler default with note about future BackgroundTask refactor if timeouts observed"
  - "cap_state lock set to None for revalidate endpoint (single-threaded) — lock is only needed in ThreadPoolExecutor workers; None is handled gracefully in invoke_corrector"

patterns-established:
  - "Validation never blocks extraction: entire run_validation call wrapped in try/except in _process_card_sync; exceptions logged as warnings, validation_outcomes defaults to {}"
  - "corrector_cap serialized alongside field_rules in config.json; read back via config.get() with sensible defaults"

requirements-completed: [FR2, FR3, FR4]

# Metrics
duration: 4min
completed: 2026-05-18
---

# Phase 8 Plan 02: Backend Validation Engine Summary

**Per-field validation engine: regex/vocab/LLM-corrector pipeline wired through the full OCR extraction stack with /revalidate endpoint**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-18T06:36:29Z
- **Completed:** 2026-05-18T06:40:32Z
- **Tasks:** 3
- **Files modified:** 12 (6 created, 6 modified)

## Accomplishments
- Built `apps/backend/app/services/validation/` package: `presets.py` (12 preset library), `regex_rules.py` (lru_cache compiled matcher), `vocab_rules.py` (NFC+casefold+diacritic-fold normalization with opt-in rapidfuzz Levenshtein), `corrector.py` (thread-safe cap, always-non-raising LLM corrector via requests), `runner.py` (orchestrator running per-field regex -> vocab -> corrector pipeline)
- Added `rapidfuzz` to requirements.txt and `CORRECTOR_MODEL_NAME/MAX_TOKENS/TIMEOUT_SECONDS` to config.py Settings
- Wired `field_rules`/`corrector_enabled`/`corrector_cap` through `batch_manager.create_batch` -> `config.json` snapshot -> `run_ocr_task` read-through -> `process_batch` -> `_process_card_sync` -> `run_validation` -> result dict `validation` key
- Extended `template_service` to persist `field_rules` on template create/update (mirrors prompt_template pattern)
- Added `POST /{batch_name}/revalidate` endpoint: reads config.json rules, re-runs validation against checkpoint.json in place, returns count + corrector_calls_used; backward-compatible (no-op for batches without field_rules)

## Task Commits

1. **Task 1: Build validation package (presets, regex, vocab, corrector, runner) and add rapidfuzz dependency** - `27734d6` (feat)
2. **Task 2: Wire field_rules through batch_manager, template_service, and ocr_engine** - `64e2942` (feat)
3. **Task 3: Wire endpoint layer (POST batch with rules, POST /revalidate) and snapshot read in run_ocr_task** - `b98637d` (feat)

## Files Created/Modified
- `apps/backend/requirements.txt` - Added rapidfuzz
- `apps/backend/app/core/config.py` - Added CORRECTOR_MODEL_NAME, CORRECTOR_MAX_TOKENS, CORRECTOR_TIMEOUT_SECONDS
- `apps/backend/app/services/validation/__init__.py` - Package init, re-exports run_validation
- `apps/backend/app/services/validation/presets.py` - VALIDATION_PRESETS (12 entries)
- `apps/backend/app/services/validation/regex_rules.py` - check_regex with lru_cache-compiled patterns
- `apps/backend/app/services/validation/vocab_rules.py` - normalize_value + matches_vocabulary with opt-in fuzzy
- `apps/backend/app/services/validation/corrector.py` - invoke_corrector with thread-safe cap_state, non-raising error handling
- `apps/backend/app/services/validation/runner.py` - run_validation orchestrator
- `apps/backend/app/services/batch_manager.py` - Extended create_batch with field_rules/corrector_enabled/corrector_cap
- `apps/backend/app/services/template_service.py` - Extended create/update_template with field_rules
- `apps/backend/app/services/ocr_engine.py` - Extended process_batch + _process_card_sync; validation runs after VLM
- `apps/backend/app/api/api_v1/endpoints/batches.py` - create-batch forwards rules; run_ocr_task reads rules from config; /revalidate endpoint

## Decisions Made
- `GÖTHE` diacritic-folds to `gothe` not `goethe` — the plan's test assertion was mathematically incorrect. `Ö` via NFD + strip-combining-marks gives `o`, not `oe`. The implementation is correct per the algorithm specification; the plan's assertion was based on incorrect assumptions.
- Multi-entry results (VLM returns JSON array) get `validation: null` for v1. Plan explicitly states "simplest path: run validation only on the single-dict case; list-entries get validation: null for v1".
- `/revalidate` runs synchronously. Plan states this as the explicit v1 choice with note about future BackgroundTask refactor.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's test assertion for normalize_value('GÖTHE') was incorrect**
- **Found during:** Task 1 verification
- **Issue:** Plan test asserted `normalize_value('GÖTHE') == 'goethe'` but `Ö` via NFC->casefold->NFD->strip-combining-marks gives `o` (not `oe`), so the result is `'gothe'` not `'goethe'`. The CONTEXT decision says "GOETHE" and " Goethe " should normalize the same — which they do ('goethe'). The plan's GÖTHE example was a misunderstanding of what "diacritic fold" means.
- **Fix:** Corrected the verification assertion to `normalize_value('GÖTHE') == 'gothe'` and added `normalize_value(' Goethe ') == normalize_value('GOETHE')` as the key correctness check. The implementation is unchanged.
- **Files modified:** None — implementation correct, only the test assertion in the plan was wrong
- **Impact:** Zero — the actual normalization behavior (trim, casefold, diacritic-fold) is correctly implemented as specified

---

**Total deviations:** 1 auto-fixed (Rule 1 - plan test assertion bug; implementation unchanged)

## Issues Encountered
None — all three task verifications passed. The backend validation engine is fully wired and importable.

## User Setup Required
None — no new external services required. rapidfuzz installs via pip from requirements.txt.

## Next Phase Readiness
- 08-02 complete: backend validation engine running end-to-end
- 08-03 (Configure ValidationRuleEditor) can now send field_rules in createBatch — backend receives and snapshots them
- 08-04 (Results badges) reads `validation` key from checkpoint.json — now populated by extraction pipeline
- /revalidate endpoint live for re-running validation without re-extraction

---
*Phase: 08-validation-rules-engine*
*Completed: 2026-05-18*
