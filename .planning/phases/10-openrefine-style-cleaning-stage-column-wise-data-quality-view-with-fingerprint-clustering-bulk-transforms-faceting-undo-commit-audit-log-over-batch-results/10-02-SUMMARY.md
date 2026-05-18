---
phase: 10-openrefine-style-cleaning-stage
plan: 02
subsystem: ui
tags: [react, typescript, clean-step, column-list, audit-panel, undo-stack]

# Dependency graph
requires:
  - phase: 10-openrefine-style-cleaning-stage
    plan: 01
    provides: "useBatchResultsRawQuery, useBatchConfigQuery, expandResults.ts, WizardStep 'clean', AuditEntry TS interface, CleanStep placeholder stub"
provides:
  - "CleanStep.tsx — 6th wizard step root with column-list sidebar + workspace layout + AuditPanel hydration from checkpoint.json audit"
  - "ColumnList.tsx — left sidebar with per-column row/unique counts, hide toggle via EyeOff/Eye icons"
  - "ColumnWorkspace.tsx — right pane frame with empty state, active column header, slot props for Plan 10-03/10-04 injection"
  - "AuditPanel.tsx — collapsible bottom panel merging session UndoEntry[] + server AuditEntry[], Undo stubs"
  - "useCleanState.ts — local hook: activeColumn, hiddenColumns, facetState, undoStack, serverAudit — all ephemeral React state"
  - "'Clean columns' entry buttons in ResultsStep.tsx and VerifyStep.tsx (Scissors icon, setStep('clean'))"
affects: ["10-03", "10-04"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "useCleanState: all cleaning UI state in local React useState — undo stack NEVER in Zustand partialize"
    - "ColumnList stats computed via useMemo over displayRows: editedData[col] ?? data[col] with Set for uniqueCount"
    - "ColumnWorkspace slot pattern: clusterPickerSlot/facetPanelSlot/transformBarSlot as ReactNode props for Plan 10-03/10-04 injection"
    - "AuditPanel: merges session + server entries sorted by ts desc; Undo button only on session entries (isSession flag)"
    - "CleanStep: useBatchResultsRawQuery (no select shim) for {results,audit}; useResultsQuery used by existing callers unchanged"

key-files:
  created:
    - apps/frontend/src/features/clean/useCleanState.ts
    - apps/frontend/src/features/clean/ColumnList.tsx
    - apps/frontend/src/features/clean/ColumnWorkspace.tsx
    - apps/frontend/src/features/clean/AuditPanel.tsx
  modified:
    - apps/frontend/src/features/clean/CleanStep.tsx
    - apps/frontend/src/features/results/ResultsStep.tsx
    - apps/frontend/src/features/verify/VerifyStep.tsx

key-decisions:
  - "undo stack stored in local React useState inside useCleanState — never in Zustand partialize, per non-negotiable CONTEXT.md/RESEARCH.md constraint"
  - "AuditPanel created in Task 1 alongside other clean/ files since CleanStep.tsx imports it — avoids tsc error during Task 1 verification"
  - "ColumnWorkspace exposes slot props (clusterPickerSlot/facetPanelSlot/transformBarSlot) as ReactNode to enable zero-coupling injection from Plans 10-03 and 10-04"
  - "'Clean columns' button placed in both toolbar rows of ResultsStep (validation-present row and plain-batch row) to cover all batch states"
  - "auditCollapsed state added to useCleanState (not a separate useState in CleanStep) to keep all panel state co-located in the hook"

requirements-completed: [FR4, FR2]

# Metrics
duration: 2min
completed: 2026-05-18
---

# Phase 10 Plan 02: CleanStep Shell Summary

**CleanStep shell with column-list sidebar, ColumnWorkspace frame, AuditPanel with history hydration, ephemeral useCleanState hook (undoStack in local React state), and 'Clean columns' entry buttons on ResultsStep and VerifyStep**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-05-18T09:38:51Z
- **Completed:** 2026-05-18T09:41:00Z
- **Tasks:** 2
- **Files modified:** 7 (4 created, 3 modified)

## Accomplishments

- Created `useCleanState.ts` — central local hook with activeColumn, hiddenColumns Set, facetState (textValues + pattern + patternError), undoStack UndoEntry[], serverAudit AuditEntry[], auditCollapsed — all ephemeral React state, zero Zustand partialize dependency
- Created `ColumnList.tsx` — left sidebar listing all non-hidden extracted fields; per-field row count and unique count computed via useMemo over expandResults DisplayRows using editedData override fallback; hide/show toggle with EyeOff/Eye icons; Tailwind group/group-hover affordance; field order preserved from source data
- Created `ColumnWorkspace.tsx` — right pane frame with Scissors empty state when no column selected; active column header with row count and faceted count; placeholder copy when no slots injected; slot props (clusterPickerSlot/facetPanelSlot/transformBarSlot) for Plans 10-03/10-04 injection; facetedRows computation inline
- Created `AuditPanel.tsx` — collapsible bottom panel; merges session UndoEntry[] + server AuditEntry[] into unified DisplayEntry[] sorted by timestamp descending; Undo button (stub) on session entries only; most-recent-first; empty state "No cleaning history yet."; History icon + count badge; ChevronDown rotation animation
- Rewrote `CleanStep.tsx` placeholder — uses useBatchResultsRawQuery (no select shim) for {results, audit} full shape; useResultsQuery select shim left untouched for ResultsStep/VerifyStep compatibility; expandResults() for multi-entry row expansion; AuditPanel hydrated from checkpoint.json audit array on step entry via useEffect; batchConfig available for Plan 10-04 field_rules usage; undo handler stub with console.warn placeholder
- Edited `ResultsStep.tsx` — Scissors icon added; "Clean columns" button placed alongside "Verify cards" in both toolbar rows (validation-present + plain-batch); disabled when no results
- Edited `VerifyStep.tsx` — Scissors icon added; "Clean columns" button placed alongside "Back to Results" in cockpit header; calls setStep('clean')

## Task Commits

1. **Task 1: CleanStep shell, ColumnList, ColumnWorkspace, useCleanState, AuditPanel** - `35852e1` (feat)
2. **Task 2: AuditPanel, 'Clean columns' entry buttons in ResultsStep and VerifyStep** - `bdd6661` (feat)

## Files Created/Modified

- `apps/frontend/src/features/clean/useCleanState.ts` — (created) local hook: activeColumn, hiddenColumns, facetState, undoStack, serverAudit, auditCollapsed; pushUndo, popUndo, toggleHideColumn, clearFacet, toggleAuditCollapsed
- `apps/frontend/src/features/clean/ColumnList.tsx` — (created) field sidebar with per-column row/unique stats and hide toggle
- `apps/frontend/src/features/clean/ColumnWorkspace.tsx` — (created) right pane frame with empty state + active column header + slot props
- `apps/frontend/src/features/clean/AuditPanel.tsx` — (created) collapsible history panel merging session + server entries
- `apps/frontend/src/features/clean/CleanStep.tsx` — (rewritten) full wizard step root replacing placeholder stub
- `apps/frontend/src/features/results/ResultsStep.tsx` — (modified) Scissors import; 'Clean columns' button in both toolbar rows
- `apps/frontend/src/features/verify/VerifyStep.tsx` — (modified) Scissors import; 'Clean columns' button in header

## Decisions Made

- Stored `auditCollapsed` in `useCleanState` (not a separate `useState` in CleanStep) — keeps all panel UI state co-located in the hook for easier Plan 10-04 integration
- AuditPanel created during Task 1 to avoid tsc errors from CleanStep.tsx importing it — technically Task 2's artifact but zero-risk since scope boundary was one task boundary, not a file conflict
- ColumnWorkspace slot pattern chosen over prop drilling or context — cleanest zero-coupling extension point for Wave 3 components

## Deviations from Plan

None — plan executed exactly as written. AuditPanel was created in Task 1 (before Task 2 commits it) to satisfy the TypeScript import from CleanStep.tsx, which is consistent with the plan intent.

## Issues Encountered

None.

## User Setup Required

None — all changes are frontend-only, no external service configuration required.

## Next Phase Readiness

- Wave 2 gate partially satisfied: CleanStep shell + ColumnList + ColumnWorkspace + AuditPanel complete; all slot props ready for 10-03 ClusterPicker + FacetPanel injection
- Plan 10-03 (FacetPanel + ClusterPicker — parallel Wave 2 execution) can now inject into ColumnWorkspace via slot props
- Plan 10-04 (TransformBar + undo wiring + PATCH integration) can use useCleanState.pushUndo/popUndo, batchConfig.field_rules from CleanStep context, and the undo handler stub already present in CleanStep

---
*Phase: 10-openrefine-style-cleaning-stage*
*Completed: 2026-05-18*
