---
phase: 10-openrefine-style-cleaning-stage
plan: 04
subsystem: ui
tags: [react, typescript, transform-bar, bulk-transforms, undo, cluster-apply, regex-replace, audit-panel, sonner, revalidation]

# Dependency graph
requires:
  - phase: 10-02
    provides: "CleanStep shell, ColumnWorkspace slot props, AuditPanel, useCleanState (pushUndo/popUndo), ephemeral undo stack"
  - phase: 10-03
    provides: "fingerprint.ts (buildClusters/computeFingerprint), ClusterPicker, FacetPanel, TextFacet, PatternFacet"
  - phase: 10-01
    provides: "revalidateCell, normalizeValue, validationRuntime.ts, patchResult with audit_entry, useBatchConfigQuery"
provides:
  - "TransformBar.tsx: 7 v1 transforms (Trim/Upper/Lower/Title/Collapse-ws/Regex…/Set-NULL) with 100-row sonner confirmation toast"
  - "RegexReplaceModal.tsx: find+replace modal with try/catch regex guard and capture group support"
  - "CleanStep.tsx (complete): handleApplyTransform with race-free firstRowPatched, per-cell no-op check, revalidateCell per transform, handleClusterApply, handleUndo restoring cellSnapshot"
  - "All Wave 2/3 slots mounted in ColumnWorkspace: ClusterPicker + FacetPanel + TransformBar"
  - "AuditPanel.onUndo fully wired to handleUndo — clicking Undo reverts operation in Zustand and fires PATCHes"
  - "Phase 10 fully production-ready — complete OpenRefine-style cleaning workflow"
affects: ["11-authority-reconciliation"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "firstRowPatched race-fix: audit_entry carrier evaluated synchronously before setTimeout — never inside callback — prevents N concurrent timeouts all seeing false"
    - "Per-cell no-op check (newValue === currentValue) before any mutation — preserves 'verified' status on unchanged cells (e.g., Upper on already-uppercase 'BERLIN')"
    - "Single PATCH per cell: value + validation_status + audit_entry ride in ONE patchResult call — no second PATCH, no double audit entries"
    - "applyTransformOp pure helper with Unicode-aware Title Case via \\p{L}+ regex"
    - "skippedFingerprints local useState reset via useEffect on activeColumn change — keeps cluster skip state per-column"
    - "handleUndo: restores editedData (virtualFilename key) + validation (pageFilename key) atomically then fires debounced PATCHes without audit_entry"

key-files:
  created:
    - apps/frontend/src/features/clean/TransformBar.tsx
    - apps/frontend/src/features/clean/RegexReplaceModal.tsx
  modified:
    - apps/frontend/src/features/clean/CleanStep.tsx

key-decisions:
  - "firstRowPatched flipped synchronously before setTimeout scheduling — the only correct place; inside setTimeout all callbacks race at ~500ms and all see false (produces N audit entries)"
  - "Per-cell no-op (newValue === currentValue) exits loop iteration before updateResultCell, before revalidateCell, before pushUndo — 'verified' survives Upper on already-uppercase value by touching nothing"
  - "handleClusterApply uses shouldCarryAudit local bool (same synchronous pattern as handleApplyTransform firstRowPatched) for identical race-safety"
  - "100-row confirmation added to cluster apply as well as transform bar — consistent large-batch protection"
  - "No audit_entry on undo PATCHes — undo is implicit in stack removal; backend does not double-append"
  - "skippedFingerprints is local useState (not in useCleanState) — tightly scoped to CleanStep; resets on column switch via useEffect dep on activeColumn"
  - "Export gate inherited automatically: useResultsExport reads same Zustand results array that CleanStep mutates — no additional wiring needed"

requirements-completed: [FR4, FR2]

# Metrics
duration: ~4min
completed: 2026-05-18
---

# Phase 10 Plan 04: TransformBar + RegexReplaceModal + Final CleanStep Integration Summary

**Race-free bulk-transform engine with firstRowPatched synchronous audit_entry gating, per-cell no-op verified-status preservation, cluster apply, undo via cellSnapshot PATCHes, and all Wave 2/3 slots mounted — Phase 10 fully production-ready**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-18T09:45:35Z
- **Completed:** 2026-05-18T09:49:00Z
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 rewritten)

## Accomplishments

- `TransformBar.tsx` built with 7 v1 transform buttons (Trim, UPPER, lower, Title Case, Collapse spaces, Regex…, Set to NULL); scope display shows facetedRows count vs totalRows with "(filtered)" badge; 100+ row sonner `toast.warning` confirmation gate before any apply
- `RegexReplaceModal.tsx` built with find + replace inputs, live try/catch regex validation on every keystroke, red border + "Invalid regex" label on malformed input, Apply disabled when `!findPattern || regexError`; resets on close
- `CleanStep.tsx` fully rewritten with production transform engine: `handleApplyTransform` correctly evaluates `!firstRowPatched` synchronously before each `setTimeout` is scheduled — prevents the audit_entry race condition where N concurrent timers all see `firstRowPatched=false`
- Per-cell no-op check (`newValue === currentValue`) exits loop before any mutation — `verified` status preserved on cells that don't change (e.g., UPPER on already-uppercase "BERLIN")
- `handleClusterApply` uses identical synchronous `shouldCarryAudit = !firstRowPatched; firstRowPatched = true` pattern; removes applied cluster from picker via `skippedFingerprints`
- `handleUndo` restores per-cell before-state from `UndoEntry.cellSnapshot`, updates Zustand `editedData` + `validation`, fires debounced PATCHes (no `audit_entry` on undo), shows `toast.success`
- All three slots mounted in `ColumnWorkspace` from `CleanStep`: `ClusterPicker` (with `resetKey=activeColumn`), `FacetPanel`, `TransformBar`
- `AuditPanel.onUndo` wired to real `handleUndo` — clicking Undo in the panel reverts the operation
- `revalidateCell()` called per-cell after each transform; validation outcome updated atomically in Zustand
- `tsc --noEmit`: zero errors across all Phase 10 files

## Task Commits

1. **Task 1: TransformBar with 7 transforms + RegexReplaceModal** — `76c4d5c` (feat)
2. **Task 2: Final integration — transforms, cluster apply, undo, all slots mounted** — `ea4aac7` (feat)

## Files Created/Modified

- `apps/frontend/src/features/clean/TransformBar.tsx` — (created) 7 transform buttons, 100-row toast.warning, opens RegexReplaceModal for regex-replace op
- `apps/frontend/src/features/clean/RegexReplaceModal.tsx` — (created) find+replace modal, live regex validation, capture group hint, Apply disabled on error
- `apps/frontend/src/features/clean/CleanStep.tsx` — (rewritten) full production implementation with transform engine, cluster apply, undo, facetedRows computation, all slots wired

## Decisions Made

- `firstRowPatched` flipped synchronously before `setTimeout` scheduling (not inside callback) — the only way to prevent N concurrent timers from all reading `false` and each producing an audit entry
- Per-cell no-op exit (`if (newValue === currentValue) continue`) placed BEFORE `updateResultCell`, `revalidateCell`, and `pushUndo` — all three are skipped, so `verified` status is untouched
- `shouldCarryAudit` bool captures the `!firstRowPatched` value synchronously in cluster apply loop — same race-fix pattern as transform apply
- `skippedFingerprints` as local `useState` (not in `useCleanState`) with `useEffect` reset on `activeColumn` — keeps cluster skip state isolated per column
- Export gate inherited automatically because `useResultsExport` reads from Zustand `results` array, which is the same array `CleanStep` mutates via `updateResultCell` — no additional wiring needed

## Deviations from Plan

None — plan executed exactly as written. All critical correctness invariants (race-fix, no-op check, single PATCH, 100-row toast, cellSnapshot undo) implemented as specified.

## Issues Encountered

None.

## User Setup Required

None — all changes are frontend-only, no external service configuration required.

## Next Phase Readiness

- Phase 10 fully complete — CleanStep is production-ready with all 4 plans across 3 waves delivered
- Phase 11 (Authority Reconciliation) can proceed — Clean view is stable, export gate works, audit log persists to checkpoint.json
- Curators can now: activate a column, see near-duplicate cluster suggestions, apply cluster merges, apply 7 bulk transforms to faceted rows, undo any session operation, and export through the Phase 8 validation gate

## Self-Check

- `TransformBar.tsx` exists: FOUND
- `RegexReplaceModal.tsx` exists: FOUND
- `CleanStep.tsx` (rewritten) exists: FOUND
- `toast.warning` in TransformBar.tsx: PASS
- `revalidateCell` in CleanStep.tsx: PASS
- `newValue === currentValue` no-op check in CleanStep.tsx: PASS
- `firstRowPatched` synchronous pattern in CleanStep.tsx: PASS
- `shouldCarryAudit` synchronous pattern in CleanStep.tsx: PASS
- `cellSnapshot` undo snapshot in CleanStep.tsx: PASS
- `handleUndo`/`popUndo` wired in CleanStep.tsx: PASS
- `cluster-merge` in CleanStep.tsx: PASS
- undo stack NOT in persist (useCleanState.ts): PASS
- TypeScript `--noEmit` clean: PASS (zero errors)
- Task 1 commit `76c4d5c`: FOUND
- Task 2 commit `ea4aac7`: FOUND

## Self-Check: PASSED

---
*Phase: 10-openrefine-style-cleaning-stage*
*Completed: 2026-05-18*
