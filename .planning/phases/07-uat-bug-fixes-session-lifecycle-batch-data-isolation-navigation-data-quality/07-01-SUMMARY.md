---
phase: 07-uat-bug-fixes-session-lifecycle-batch-data-isolation-navigation-data-quality
plan: 01
subsystem: ui
tags: [react, zustand, typescript, results, export, batch-history, session-lifecycle]

# Dependency graph
requires:
  - phase: 06-merge-features-of-main-and-current-branch
    provides: ResultsStep with useResultsExport, ConfigureStep with WizardNav, BatchHistoryCard with review action
provides:
  - ResultsStep derives field labels from results[].data keys via useMemo — not from store fields[]
  - ConfigureStep disables Commence Processing when batchId is already set with explanatory message
  - Default batch name includes HH:MM timestamp for same-day disambiguation
  - BatchHistoryCard shows unique batch_name as monospace subtitle
affects:
  - 07-02 (navigation fixes)
  - 07-03 (data quality fixes)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "useMemo field derivation: field labels computed from result data keys, not from wizard store — archives own their field names"
    - "batchId guard pattern: button disabled + explanatory message when session has existing batch — prevents duplicate batch creation"

key-files:
  created: []
  modified:
    - apps/frontend/src/features/results/ResultsStep.tsx
    - apps/frontend/src/features/configure/ConfigureStep.tsx
    - apps/frontend/src/features/history/BatchHistoryCard.tsx

key-decisions:
  - "Field labels derived from results[].data keys via useMemo, not store fields[] — archived batch reviews always show correct columns"
  - "Map-based insertion-order preservation for field key deduplication across all result rows"
  - "batchId !== null guard on Commence Processing button disables resubmission without navigation redirect"
  - "Batch default name uses slice(0,16).replace('T','_') to produce Batch_2026-02-23_14:30 format"
  - "BatchHistoryCard subtitle uses font-mono text-[10px] with truncate+title for overflow on long batch IDs"

patterns-established:
  - "Results field derivation: always derive columns from actual data, never from wizard session state — decouples review from active session"
  - "Session state guard: read batchId from store at render time to conditionally disable actions that would create duplicate backend resources"

# Metrics
duration: 8min
completed: 2026-02-23
---

# Phase 07 Plan 01: Session Lifecycle, Batch Data Isolation, and Name Uniqueness Summary

**ResultsStep now derives field columns from batch results data (not wizard session state), eliminating corrupted exports when reviewing archived batches; ConfigureStep guards against duplicate batch creation with a clear explanatory message.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-02-23T19:50:00Z
- **Completed:** 2026-02-23T19:58:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Fixed BUG-06 (wrong fields shown on archived batch review) and BUG-07 (corrupted exports) by deriving fieldLabels from `results[].data` keys via `useMemo` — completely decoupled from wizard store `fields[]`
- Fixed BUG-13/BUG-15 (cryptic 400 error on re-processing): ConfigureStep reads `batchId` from store and disables "Commence Processing" when a batch already exists, showing a clear "use Start New Batch" message
- Fixed BUG-05 (indistinguishable same-day batch names): default batch name now includes `HH:MM` time component; BatchHistoryCard shows full `batch_name` (with timestamp+UUID suffix) as a monospace subtitle

## Task Commits

Each task was committed atomically:

1. **Task 1: Derive field labels from results data via useMemo (BUG-06 + BUG-07)** - `543b00b` (feat)
2. **Task 2: Guard stale session re-processing + batch name uniqueness (BUG-05, BUG-13, BUG-15)** - `b6d7027` (feat)

## Files Created/Modified
- `apps/frontend/src/features/results/ResultsStep.tsx` - Replaced `fields.map((f) => f.label)` with `useMemo` that collects unique keys from `results[].data`; removed `fields` from store destructure; added `useMemo` to React import
- `apps/frontend/src/features/configure/ConfigureStep.tsx` - Added `batchId` to store destructure; `batchId !== null` on button `disabled` prop; explanatory message when `batchId` is set; default batch name uses `slice(0,16).replace('T','_')`
- `apps/frontend/src/features/history/BatchHistoryCard.tsx` - Wrapped `<h3>` in `<div className="flex flex-col gap-0.5">` and added `<span>` with `batch.batch_name` as monospace subtitle

## Decisions Made
- Field labels derived from `results[].data` keys via `useMemo`, not `store.fields[]` — archived batch reviews always display the correct field names from the actual OCR output, completely independent of the current wizard session state
- `Map`-based insertion-order preservation for field key deduplication: first occurrence across all result rows defines column order
- `batchId !== null` guard disables re-processing without redirecting; explanatory message tells user to use "Start New Batch" from the Results step
- Batch name default format: `Batch_2026-02-23_14:30` produced by `slice(0,16).replace('T','_')` — same-day batches are now distinguishable
- BatchHistoryCard subtitle uses `font-mono text-[10px] truncate` with `title` attribute for accessible overflow tooltip on long batch IDs

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - TypeScript compiled cleanly on first attempt after all changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- BUG-06, BUG-07 (batch data isolation) fully resolved — archived batch export is now correct
- BUG-13, BUG-15 (session lifecycle) fully resolved — no more 400 errors from stale session re-processing
- BUG-05 (batch name uniqueness) fully resolved — both at creation time (unique default) and in the archive view (subtitle)
- Ready to proceed to Plan 02 (navigation fixes) and Plan 03 (data quality fixes)

---
*Phase: 07-uat-bug-fixes-session-lifecycle-batch-data-isolation-navigation-data-quality*
*Completed: 2026-02-23*

## Self-Check: PASSED

- FOUND: apps/frontend/src/features/results/ResultsStep.tsx
- FOUND: apps/frontend/src/features/configure/ConfigureStep.tsx
- FOUND: apps/frontend/src/features/history/BatchHistoryCard.tsx
- FOUND: .planning/phases/07-.../07-01-SUMMARY.md
- FOUND: commit 543b00b (Task 1)
- FOUND: commit b6d7027 (Task 2)
