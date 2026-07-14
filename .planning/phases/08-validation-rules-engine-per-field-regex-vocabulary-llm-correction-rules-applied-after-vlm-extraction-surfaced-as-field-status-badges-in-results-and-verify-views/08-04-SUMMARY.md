---
phase: 08-validation-rules-engine
plan: 04
subsystem: frontend-results
tags: [react, zustand, validation, badges, filter-chips, sonner, export-gate, summary-banner]

# Dependency graph
requires:
  - phase: 08-01
    provides: ValidationOutcome type in wizardStore.ts (ResultRow.validation field)
  - phase: 08-02
    provides: validation key populated in checkpoint.json by OCR pipeline
  - phase: 08-03
    provides: acceptCorrectorProposal/rejectCorrectorProposal actions in wizardStore
provides:
  - ValidationBadge per-cell component (valid/invalid/corrected icons + tooltip + Accept/Reject)
  - ValidationFilterChips (All/Invalid/Auto-corrected/Verified OK) with row counts
  - ResultsTable row filtering by validation status
  - ResultsStep hydrates validation from API + renders filter chips above table
  - SummaryBanner invalidCount + correctedCount stat columns
  - useResultsExport checkValidationGate soft-block for all 8 download functions
affects:
  - 09 (Verify cockpit) — ResultRow.validation shape is now the Phase 9 data contract; no further data-shape changes required

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ValidationBadge: hover tooltip via useState + onMouseEnter/Leave (corrected status stays open for button interaction)"
    - "ValidationFilterChips: Parchment-styled rounded-full chip buttons with count badges"
    - "checkValidationGate: sonner toast.warning with action+cancel (same pattern as FieldManager.tsx lines 32-44)"
    - "Validation filter applied to results before Findmittel sub-row expansion in displayRows useMemo"

key-files:
  created:
    - apps/frontend/src/features/results/ValidationBadge.tsx
    - apps/frontend/src/features/results/ValidationFilterChips.tsx
  modified:
    - apps/frontend/src/features/results/ResultsTable.tsx
    - apps/frontend/src/features/results/ResultsStep.tsx
    - apps/frontend/src/features/results/SummaryBanner.tsx
    - apps/frontend/src/features/results/useResultsExport.ts

key-decisions:
  - "ValidationBadge uses useState + onMouseEnter/Leave for tooltip; corrected status keeps tooltip open on mouse-enter to allow button interaction — prevents tooltip closing before Accept/Reject can be clicked"
  - "ValidationFilterChips rendered only when at least one row has validation data (invalid+corrected+valid > 0) — hides entirely for old batches with no validation outcomes"
  - "Filter applied at ResultsTable level against original results array before Findmittel sub-row expansion — consistent with how results are filtered elsewhere"
  - "checkValidationGate defined as a local function inside the hook body (not exported) — transparent to callers, wraps all 8 download functions with identical behavior"
  - "corrected proposals do NOT trigger the export gate — only open invalid status does, per CONTEXT.md"

patterns-established:
  - "ResultRow.validation shape is the Phase 9 contract — Verify cockpit reads it unchanged"
  - "backward compat: r.validation ?? null in hydration — old batches without validation render cleanly with no badges"

requirements-completed: [FR4]

# Metrics
duration: 3min
completed: 2026-05-18
---

# Phase 8 Plan 04: Results Validation UI Summary

**Per-cell ValidationBadge with hover tooltips and Accept/Reject, ValidationFilterChips, SummaryBanner aggregate counts, and sonner soft-block export gate across all 8 download formats**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-18T06:44:01Z
- **Completed:** 2026-05-18T06:47:21Z
- **Tasks:** 3
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments

- Created `ValidationBadge.tsx`: per-cell badge with CheckCircle/XCircle/Wand2 icons for valid/invalid/corrected status; hover tooltip revealing rule failure detail, original value, and for corrected status a proposed value + rationale + Accept/Reject buttons that call `acceptCorrectorProposal`/`rejectCorrectorProposal` from wizardStore; null-renders for skipped/no outcome
- Created `ValidationFilterChips.tsx`: four Parchment-styled rounded-full chip buttons (All/Invalid/Auto-corrected/Verified OK) with per-status row counts; active chip filled in archive-sepia color
- Extended `ResultsTable.tsx`: added `validationFilter` prop; `filteredResults` useMemo filters by validation status before Findmittel sub-row expansion; each `<dd>` in the extraction column now wraps `<ValidationBadge>` inline before `<EditableCell>`
- Extended `ResultsStep.tsx`: hydrates `validation: r.validation ?? null` from API (backward compat); adds `validationFilter` state and `validationCounts` useMemo; renders `<ValidationFilterChips>` above the table when any validation data present; passes `invalidCount`/`correctedCount` to SummaryBanner and `validationFilter` to ResultsTable
- Extended `SummaryBanner.tsx`: added optional `invalidCount`/`correctedCount` props; adds amber "Invalid" and blue "Proposals" stat columns after Duration, hidden when zero — clean for batches without validation
- Extended `useResultsExport.ts`: added `checkValidationGate()` local helper that counts rows with any `status === 'invalid'` outcome; wraps all 8 download functions (CSV/JSON/LIDO/EAD/DarwinCore/DublinCore/MARCXML/METSMOD) with the gate; shows sonner toast.warning with "Export anyway" + "Cancel" buttons for 10 seconds; exports with no validation data proceed immediately

## Task Commits

1. **Task 1: Build ValidationBadge + ValidationFilterChips, integrate badges into ResultsTable** - `5e7e687` (feat)
2. **Task 2: Wire ResultsStep hydration + filter chips + SummaryBanner counts** - `7998b42` (feat)
3. **Task 3: Soft-block export gate via sonner confirmation in useResultsExport** - `ccda596` (feat)

## Files Created/Modified

- `apps/frontend/src/features/results/ValidationBadge.tsx` — Created: ~100 lines; per-cell badge with icons, hover tooltip, Accept/Reject for corrected proposals
- `apps/frontend/src/features/results/ValidationFilterChips.tsx` — Created: ~55 lines; four Parchment chip buttons with counts
- `apps/frontend/src/features/results/ResultsTable.tsx` — Extended: added ValidationBadge import + ValidationFilter type; filteredResults useMemo; badge in each dd
- `apps/frontend/src/features/results/ResultsStep.tsx` — Extended: validation hydration; validationFilter state + validationCounts; ValidationFilterChips rendered above table; invalidCount/correctedCount passed to SummaryBanner
- `apps/frontend/src/features/results/SummaryBanner.tsx` — Extended: invalidCount/correctedCount optional props; two new stat columns after Duration
- `apps/frontend/src/features/results/useResultsExport.ts` — Extended: checkValidationGate helper + all 8 download functions wrapped

## Decisions Made

- `ValidationBadge` uses `useState` + `onMouseEnter/Leave` rather than a `group-hover` CSS approach because the corrected status tooltip contains interactive buttons (Accept/Reject) — CSS-only hover would close the tooltip as the cursor moves from icon to buttons. The tooltip stays open on `onMouseEnter` over the tooltip container itself.
- `ValidationFilterChips` is conditionally rendered only when at least one row has a non-trivial validation outcome (invalid+corrected+valid > 0). Batches without validation rules show no chips — the UI stays clean.
- Filter applied to the original `results` array before Findmittel sub-row expansion. This ensures that filtering "Only invalid" on a Findmittel page with a failed field shows the entire page (all sub-rows) — consistent with how the table already handles multi-entry pages.
- `checkValidationGate` is a local function (not exported, not a hook) — it closes over `results` from the hook scope, keeping the implementation self-contained and the exported API unchanged.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

The BOM character (`﻿`) in the CSV `triggerDownload` call prevented string-match edits via the Edit tool. Resolved by using Python line-number-based file manipulation to apply the `checkValidationGate` wrapping to the CSV and all other download functions. Final result is identical to the plan's intended wrapping.

## User Setup Required

None — all changes are frontend-only React/TypeScript. No new dependencies.

## Next Phase Readiness

- Phase 8 complete: all 4 plans (schema → backend engine → configure UI → results UI) are done
- `ResultRow.validation` shape is the Phase 9 (Verify cockpit) data contract — the Verify step can read `r.validation` unchanged
- `acceptCorrectorProposal`/`rejectCorrectorProposal` are live and wired; Phase 9 Verify cockpit can also call them for inline corrections during side-by-side review
- Old batches (no `validation` key in checkpoint.json) render without badges and without errors — backward compat confirmed

---
*Phase: 08-validation-rules-engine*
*Completed: 2026-05-18*
