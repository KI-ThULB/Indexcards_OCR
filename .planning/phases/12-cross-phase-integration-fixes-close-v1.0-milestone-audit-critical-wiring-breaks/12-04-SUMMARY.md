---
phase: 12-cross-phase-integration-fixes-close-v1.0-milestone-audit-critical-wiring-breaks
plan: 04
subsystem: frontend, store
tags: [edited-data, hydration, zustand, typescript, persistence, fr5]

# Dependency graph
requires:
  - phase: 12-cross-phase-integration-fixes (plan 01)
    provides: edited_data field in ExtractionResult JSON Schema + Pydantic model (Wave 1 foundation)
  - phase: 09-verification-cockpit
    provides: PATCH endpoint writes edited_data to checkpoint.json; GET /results returns it verbatim

provides:
  - edited_data?: Record<string, string> | null on ExtractionResult TypeScript interface in wizardStore.ts
  - ResultsStep hydration merge — backend r.edited_data wins over Zustand localStorage for matching keys; in-session-only Zustand keys preserved
  - VerifyStep hydration merge — identical strategy applied symmetrically

affects: [FR5, curator-edit-round-trip, localStorage-clear-resilience]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Backend-wins merge spread: { ...existingZustandEdits, ...r.edited_data } — Zustand first so backend can override"
    - "Conditional hydration: r.edited_data truthy → merge; absent/null → Zustand-only fallback then {}"
    - "Symmetric hydration pattern: ResultsStep and VerifyStep apply identical fix — DRY at the call-site level"

key-files:
  created: []
  modified:
    - apps/frontend/src/store/wizardStore.ts
    - apps/frontend/src/features/results/ResultsStep.tsx
    - apps/frontend/src/features/verify/VerifyStep.tsx

key-decisions:
  - "edited_data added to ExtractionResult interface only in wizardStore.ts — batchesApi.ts imports ExtractionResult from wizardStore so the field propagates automatically; no change to batchesApi.ts"
  - "Merge strategy: backend keys take precedence over Zustand localStorage (backend is the durable source via PATCH checkpoint.json); Zustand-only keys (in-session edits not yet debounce-flushed) are preserved"
  - "Spread order { ...existingEditsMap.get(r.filename), ...r.edited_data } achieves backend-wins; simpler r.edited_data ?? existingEditsMap.get(...) would lose in-flight edits — rejected"

patterns-established:
  - "Phase 6 STATE.md decision extension: Phase 6 preserved Zustand editedData across hydration; Phase 12 extends this by letting backend edited_data override Zustand for matching keys when backend has durable edits"

requirements-completed:
  - FR5

# Metrics
duration: ~4min
completed: 2026-05-19
---

# Phase 12 Plan 04: edited_data Round-Trip — TypeScript Type + Hydration Merge Summary

**ExtractionResult TypeScript interface gains edited_data field; ResultsStep and VerifyStep hydration merges backend-persisted curator edits — backend wins over Zustand localStorage for matching keys, closing the FR5 localStorage-clear gap**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-19T05:20:32Z
- **Completed:** 2026-05-19T05:24:00Z
- **Tasks:** 2
- **Files modified:** 3 (wizardStore.ts, ResultsStep.tsx, VerifyStep.tsx)

## Accomplishments

- Added `edited_data?: Record<string, string> | null` to `ExtractionResult` interface in `wizardStore.ts` — batchesApi.ts picks up the field automatically via its existing import; no changes to batchesApi.ts
- Updated ResultsStep.tsx hydration: `editedData` assignment now merges `r.edited_data` from the API response using `{ ...existingZustandEdits, ...r.edited_data }` spread — backend wins; in-session Zustand-only keys preserved
- Updated VerifyStep.tsx hydration: identical merge pattern applied symmetrically
- Backward compat confirmed: pre-Phase-9 batches where `r.edited_data` is absent or null fall back to `existingEditsMap.get(r.filename) ?? {}` unchanged
- TypeScript compiles cleanly with no new errors (`npx tsc --noEmit` exits with no output)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add edited_data to ExtractionResult TypeScript interface in wizardStore.ts** — `ffaeeee`
2. **Task 2: Hydration merge in ResultsStep and VerifyStep — backend edited_data wins over Zustand** — `9b204fe`

## Files Created/Modified

- `apps/frontend/src/store/wizardStore.ts` — Added `edited_data?: Record<string, string> | null` to ExtractionResult interface (single line addition after `validation` field)
- `apps/frontend/src/features/results/ResultsStep.tsx` — Replaced `editedData: existingEditsMap.get(r.filename) ?? {}` with conditional merge spread
- `apps/frontend/src/features/verify/VerifyStep.tsx` — Same replacement applied symmetrically (identical 3-line pattern)

## Decisions Made

- **wizardStore.ts is the TS type owner** — batchesApi.ts already imports `ExtractionResult` from wizardStore (line 4: `import type { ExtractionResult } from '../store/wizardStore'`); adding the field to wizardStore propagates automatically. Adding it to both would create type drift risk.
- **Backend-wins merge strategy** — Phase 6 decision was "preserve Zustand editedData across hydration". Phase 12 extends this: backend durable edits (from PATCH checkpoint.json) override Zustand for matching keys. Spread order `{ ...zustandEdits, ...r.edited_data }` achieves this. The simpler `r.edited_data ?? zustandEdits ?? {}` was rejected because it would lose in-flight edits (debounce window not closed yet).

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None.

## Next Phase Readiness

- FR5 gap closed: clearing localStorage and reloading a batch with curator edits now shows the edits (loaded from backend checkpoint.json via GET /results)
- Phase 12 Wave 2 is fully complete: 12-02 (CleanStep clear_reconciliation), 12-03 (CockpitBadge Link2), 12-04 (this plan) all executed
- FR2 (authority_bindings template_service), FR4 (clear_reconciliation + CockpitBadge), FR5 (edited_data round-trip) all addressed across Phase 12
- Ready for `/gsd:audit-milestone` re-run; expect FR2, FR4, FR5 to advance from partial → satisfied

---
*Phase: 12-cross-phase-integration-fixes-close-v1.0-milestone-audit-critical-wiring-breaks*
*Completed: 2026-05-19*
