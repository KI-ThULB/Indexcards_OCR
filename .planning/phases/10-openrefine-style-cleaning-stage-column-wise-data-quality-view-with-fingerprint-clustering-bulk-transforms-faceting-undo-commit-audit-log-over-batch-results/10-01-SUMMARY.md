---
phase: 10-openrefine-style-cleaning-stage
plan: 01
subsystem: api, ui
tags: [fastapi, react, typescript, checkpoint-migration, audit-log, validation, fingerprint-clustering]

# Dependency graph
requires:
  - phase: 09-verification-cockpit
    provides: "PATCH /results/{filename} endpoint, ResultPatch schema, WizardStep 'verify', editedData/validation Zustand shape"
  - phase: 08-validation-rules-engine
    provides: "vocab_rules.normalize_value() as TS port target, FieldRule/ValidationOutcome types, field_rules in config.json"
provides:
  - "read_checkpoint()/write_checkpoint() shared helpers with auto-migration from flat-array to {results,audit} object format"
  - "AuditEntry Pydantic model + ResultPatch.audit_entry field in schemas.py"
  - "GET /batches/{name}/config endpoint returning {fields, field_rules}"
  - "GET /batches/{name}/results returns {results:[...], audit:[...]} — new canonical shape"
  - "AuditEntry TypeScript interface + BatchConfig in batchesApi.ts"
  - "fetchResults/{results,audit}, patchResult(audit_entry), fetchBatchConfig, useBatchConfigQuery, useBatchResultsRawQuery"
  - "useResultsQuery select:(data)=>data.results shim — all existing callers unchanged"
  - "WizardStep union includes 'clean'; Sidebar 4-insertion-points complete"
  - "expandResults.ts shared utility — DisplayRow type + expandResults() extracted from ResultsTable"
  - "validationRuntime.ts — normalizeValue() TS port with ß→ss workaround + revalidateCell() with verified-preservation"
  - "CleanStep.tsx placeholder stub for Wave 2"
affects: ["10-02", "10-03", "10-04"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "read_checkpoint()/write_checkpoint() as the exclusive checkpoint.json I/O — auto-migrates legacy flat-array on first access"
    - "useResultsQuery select: shim — transforms raw fetch shape without touching callers"
    - "TS port of Python normalization pipeline for cross-language fingerprint parity"
    - "expandResults() pure function extracted to shared utility to avoid duplication across ResultsTable and CleanStep"

key-files:
  created:
    - apps/frontend/src/features/results/expandResults.ts
    - apps/frontend/src/features/clean/validationRuntime.ts
    - apps/frontend/src/features/clean/CleanStep.tsx
  modified:
    - apps/backend/app/api/api_v1/endpoints/batches.py
    - apps/backend/app/models/schemas.py
    - apps/frontend/src/api/batchesApi.ts
    - apps/frontend/src/store/wizardStore.ts
    - apps/frontend/src/components/Sidebar.tsx
    - apps/frontend/src/App.tsx
    - apps/frontend/src/features/results/ResultsTable.tsx

key-decisions:
  - "checkpoint.json migrated from flat array to {results,audit} object format via shared read_checkpoint() auto-migration helper on first access — no explicit migration script needed"
  - "useResultsQuery select:(data)=>data.results shim preserves ExtractionResult[] for all existing callers — ResultsStep.tsx and VerifyStep.tsx unchanged"
  - "GET /batches/{name}/config placed before DELETE /{batch_name} to avoid FastAPI greedy path-parameter matching (same pattern as /history before /{batch_name} from Phase 1)"
  - "ß→ss replace applied BEFORE toLowerCase() in validationRuntime.ts to match Python casefold() behavior for German archival data"
  - "expandResults.ts uses same label format as original ResultsTable (idx+1 / total) to preserve behavior"
  - "useBatchResultsRawQuery added without select: shim — gives CleanStep access to {results,audit} full shape for AuditPanel hydration"

patterns-established:
  - "read_checkpoint/write_checkpoint: all checkpoint.json I/O MUST go through these helpers — no direct json.load/dump on checkpoint paths"
  - "audit_entry in PATCH payload: sent ONCE per bulk operation on first affected row only (backend appends idempotently)"

requirements-completed: [FR4, FR2, FR5]

# Metrics
duration: 5min
completed: 2026-05-18
---

# Phase 10 Plan 01: OpenRefine Foundation Summary

**checkpoint.json migrated to {results, audit} object format via shared read_checkpoint() helper; AuditEntry types added backend + frontend; 'clean' wired as 6th wizard step; expandResults.ts extracted; validationRuntime.ts TS port with ß→ss casefold fix**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-18T09:29:11Z
- **Completed:** 2026-05-18T09:35:00Z
- **Tasks:** 2
- **Files modified:** 10 (7 modified, 3 created)

## Accomplishments

- Backend checkpoint.json format migrated from flat JSON array to `{results: [...], audit: [...]}` object via `read_checkpoint()`/`write_checkpoint()` helpers with automatic legacy format detection and in-place migration — all 4 checkpoint-reading endpoints updated atomically
- AuditEntry Pydantic model and extended ResultPatch (with `audit_entry`) added to schemas.py; `GET /batches/{name}/config` endpoint added for field_rules access by CleanStep; registered before DELETE to avoid greedy route matching
- Frontend: AuditEntry + BatchConfig TS interfaces; fetchResults returns `{results, audit}`; useResultsQuery `select` shim preserves ExtractionResult[] for existing callers; patchResult accepts audit_entry; fetchBatchConfig + useBatchConfigQuery + useBatchResultsRawQuery added
- WizardStep union extended to include 'clean'; Sidebar updated at all 4 mandatory insertion points (STEPS array with Scissors icon, stepOrder array, handleStepClick guard, isClickable condition); App.tsx routes 'clean' to CleanStep
- expandResults.ts pure utility extracted from ResultsTable with shared DisplayRow type; ResultsTable refactored to use it
- validationRuntime.ts TS port of vocab_rules.py normalize_value() with deliberate ß→ss before toLowerCase() for German archival data parity; revalidateCell() with no-op verified-preservation check

## Task Commits

1. **Task 1: Backend — checkpoint migration + helpers + 4 endpoints + GET /config + extended ResultPatch** - `f223cda` (feat)
2. **Task 2: Frontend — batchesApi audit types + WizardStep + Sidebar 4-point + App.tsx + expandResults + validationRuntime** - `ac0a0da` (feat)

## Files Created/Modified

- `apps/backend/app/models/schemas.py` — AuditEntry model added; ResultPatch.audit_entry optional field added
- `apps/backend/app/api/api_v1/endpoints/batches.py` — read_checkpoint/write_checkpoint helpers; all 4 endpoints migrated; GET /config added
- `apps/frontend/src/api/batchesApi.ts` — AuditEntry + BatchConfig interfaces; fetchResults shape updated; useResultsQuery select shim; patchResult + fetchBatchConfig + useBatchConfigQuery + useBatchResultsRawQuery added
- `apps/frontend/src/store/wizardStore.ts` — WizardStep union extended with 'clean'
- `apps/frontend/src/components/Sidebar.tsx` — Scissors icon import; 4 'clean' insertion points
- `apps/frontend/src/App.tsx` — CleanStep import + 'clean' case in switch
- `apps/frontend/src/features/results/ResultsTable.tsx` — uses expandResults() from shared utility; DisplayRow type removed inline
- `apps/frontend/src/features/results/expandResults.ts` — (created) shared DisplayRow + expandResults() pure function
- `apps/frontend/src/features/clean/validationRuntime.ts` — (created) normalizeValue() with ß→ss + revalidateCell()
- `apps/frontend/src/features/clean/CleanStep.tsx` — (created) placeholder stub for Wave 2

## Decisions Made

- Used `select: (data) => data.results` shim on `useResultsQuery` so all existing callers (ResultsStep, VerifyStep) continue receiving `ExtractionResult[]` without modification — cleanest backward compat path
- Added `useBatchResultsRawQuery` (no select shim) for CleanStep to access full `{results, audit}` shape needed for AuditPanel hydration on entry
- Applied ß→ss replace BEFORE `toLowerCase()` in validationRuntime.ts — Python casefold() expands ß but JS toLowerCase() does not; this fix ensures "Straße" and "STRASSE" cluster together in German archival data

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Wave 1 gate satisfied: checkpoint migration live, WizardStep union includes 'clean', expandResults.ts shared utility available, validationRuntime.ts TS port ready
- Wave 2 (10-02 CleanStep shell + ClusterPicker, 10-03 FacetPanel) can proceed in parallel — all foundation pieces are in place
- CleanStep.tsx placeholder currently returns null; Wave 2 replaces it with the full component

---
*Phase: 10-openrefine-style-cleaning-stage*
*Completed: 2026-05-18*
