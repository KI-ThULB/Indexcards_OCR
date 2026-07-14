---
phase: 11-authority-reconciliation
plan: 04
subsystem: ui
tags: [typescript, react, zustand, authority-reconciliation, clean-step, verify-step, reconcile-pane, candidate-drawer, bulk-mode]

# Dependency graph
requires:
  - phase: 11-authority-reconciliation
    plan: "01"
    provides: "ReconciliationOutcome, AuthorityBinding, postReconcile(), patchResult(clear_reconciliation), batchesApi.ts types"
  - phase: 11-authority-reconciliation
    plan: "02"
    provides: "POST /api/v1/reconcile fully wired for all 4 authorities"
  - phase: 11-authority-reconciliation
    plan: "03"
    provides: "authority_bindings on batch config.json; useBatchConfigQuery returns authority_bindings"
  - phase: 10-openrefine-cleaning-stage
    provides: "ColumnWorkspace slot pattern, TransformBar 100-row sonner confirmation toast pattern, AuditEntry/patchResult, normalizeValue in validationRuntime.ts"
provides:
  - "ColumnWorkspace.tsx accepts reconcilePaneSlot?: ReactNode alongside existing 3 slots (zero coupling)"
  - "ReconcilePane.tsx — bulk Reconcile-column button with 100-row sonner confirmation; per-cell sequential loop with auto-accept on exact-match single candidate (normalizeValue from validationRuntime); Needs-review queue with expand/collapse; Clear cache DELETE endpoint"
  - "CandidateDrawer.tsx — fixed bottom panel; top-5 candidates with label/description/URI/Pick-this; No-match button; Search-again input with Enter trigger; Escape-to-close"
  - "CleanStep.tsx — reconcilePaneSlot wired; handleCellReconciled updates Zustand + fires PATCH; openDrawer queries postReconcile and manages drawerState; CandidateDrawer at CleanStep level"
  - "CleanStep.tsx — reconciliation-clearing-on-edit in handleApplyTransform: clear_reconciliation:true + Zustand clear on value change"
  - "CleanStep.tsx — reconciliation-clearing-on-edit in executeClusterApply: same clear_reconciliation pattern for cluster merges"
  - "FieldsPane.tsx — reconciliation-clearing-on-edit in handleCommit: clear_reconciliation:true in PATCH + Zustand clear when field value changes in Verify cockpit"
affects: [11-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "reconcilePaneSlot slot injection pattern — same zero-coupling ReactNode slot as Phase 10 transform/cluster/facet slots"
    - "Fixed-bottom CandidateDrawer panel (not full modal) — familiar OpenRefine pattern without leaving column workspace"
    - "clear_reconciliation: bool flag in PATCH (NOT reconciliation: null) — per Phase 11 Plan 01 backend convention"
    - "normalizeValue imported from validationRuntime.ts — single source of truth for NFC+ß→ss+casefold+strip-marks pipeline"

key-files:
  created:
    - apps/frontend/src/features/clean/CandidateDrawer.tsx
    - apps/frontend/src/features/clean/ReconcilePane.tsx
  modified:
    - apps/frontend/src/features/clean/ColumnWorkspace.tsx
    - apps/frontend/src/features/clean/CleanStep.tsx
    - apps/frontend/src/features/verify/FieldsPane.tsx

key-decisions:
  - "CandidateDrawer rendered at CleanStep level (not ColumnWorkspace) — drawer needs to escape the overflow-hidden ColumnWorkspace container; fixed inset-x-0 bottom-0 positioning works naturally at CleanStep level"
  - "Needs-review list uses expand/collapse toggle in ReconcilePane (not a separate modal) — lightweight inline pattern avoids additional modal state"
  - "handleCellReconciled omits reconciliation key on no-match (null outcome) — PATCH for no-match only sends audit_entry without reconciliation field to avoid overwriting with null vs absent"
  - "reconciliation-clearing-on-edit applied to both handleApplyTransform AND executeClusterApply — cluster merges change values so the same invariant applies"

requirements-completed: [FR2, FR4]

# Metrics
duration: ~4min
completed: 2026-05-18
---

# Phase 11 Plan 04: Clean-view Reconcile Pane Summary

**ReconcilePane bulk mode with 100-row confirmation toast, CandidateDrawer inline picker with Escape-to-close, ColumnWorkspace reconcilePaneSlot extension, and reconciliation-clearing-on-edit in both CleanStep transform/cluster paths and FieldsPane Verify cockpit**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-18T12:36:27Z
- **Completed:** 2026-05-18T12:40:43Z
- **Tasks:** 2
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments

- Created ReconcilePane.tsx (211 lines): bulk reconcile button with 100-row sonner confirmation toast; sequential per-cell postReconcile loop; auto-accept on exactly 1 candidate AND normalizeValue(label) === normalizeValue(cellValue); Needs-review queue with expand/collapse list where clicking any item opens CandidateDrawer; Clear cache via DELETE /api/v1/batches/{batchId}/authority-cache; disabled/message state when no authority bound
- Created CandidateDrawer.tsx (153 lines): fixed bottom panel showing top-5 candidates with label/description/URI link/Pick-this button; No-match button; Search-again input with Enter key and Search button; Escape-to-close via useEffect event listener; syncs refinedQuery to cellValue on prop change
- Extended ColumnWorkspace.tsx with reconcilePaneSlot (rendered between transformBarSlot and clusterPickerSlot); updated empty-state guard to include reconcilePaneSlot
- Wired CleanStep.tsx: AUTHORITY_LABELS map; activeColumnAuthority derived from configData.authority_bindings; drawerState for per-cell query management; openDrawer() handler; handleCellReconciled() with Zustand update + PATCH; ReconcilePane in reconcilePaneSlot; CandidateDrawer at CleanStep level with all 4 handlers
- Reconciliation-clearing-on-edit in handleApplyTransform and executeClusterApply: detects hasReconciliation on currentOutcome, clears Zustand reconciliation, and adds clear_reconciliation: true to PATCH payload when value changes
- Reconciliation-clearing-on-edit in FieldsPane.handleCommit: valueChanging + hasReconciliation check; adds clear_reconciliation: true to axios.patch payload; clears Zustand reconciliation alongside verified status flip

## Task Commits

1. **Task 1: ColumnWorkspace reconcilePaneSlot + CandidateDrawer + ReconcilePane** - `2633a30` (feat)
2. **Task 2: Wire ReconcilePane + CandidateDrawer into CleanStep; reconciliation-clearing-on-edit** - `a00031b` (feat)

## Files Created/Modified

- `apps/frontend/src/features/clean/ColumnWorkspace.tsx` — added reconcilePaneSlot?: ReactNode prop; renders between transformBarSlot and clusterPickerSlot; updated empty-state guard
- `apps/frontend/src/features/clean/CandidateDrawer.tsx` — NEW: fixed-bottom candidate picker panel; top-5 candidates; Pick/No-match/Search-again; Escape-to-close
- `apps/frontend/src/features/clean/ReconcilePane.tsx` — NEW: bulk reconcile with 100-row toast; auto-accept exact-match single candidate using normalizeValue; Needs-review queue; Clear cache button
- `apps/frontend/src/features/clean/CleanStep.tsx` — AUTHORITY_LABELS; activeColumnAuthority; drawerState; openDrawer handler; handleCellReconciled handler; ReconcilePane wired in reconcilePaneSlot; CandidateDrawer portal at CleanStep level; reconciliation-clearing-on-edit in handleApplyTransform + executeClusterApply
- `apps/frontend/src/features/verify/FieldsPane.tsx` — reconciliation-clearing-on-edit in handleCommit: clear_reconciliation:true when valueChanging && hasReconciliation; Zustand reconciliation cleared atomically with verified status flip

## Decisions Made

- CandidateDrawer rendered at CleanStep level (not inside ColumnWorkspace) because the ColumnWorkspace uses overflow-hidden which would clip the fixed-bottom drawer. Fixed bottom positioning at CleanStep level escapes the clipping context correctly.
- Needs-review queue uses inline expand/collapse toggle rather than a separate modal — keeps the pane simple and avoids additional modal state management.
- `handleCellReconciled` for no-match case (outcome=null) sends only the audit_entry in the PATCH payload (no reconciliation key). This avoids overwriting with null vs absent — the backend's `clear_reconciliation: bool` flag is the correct signal for explicit clear, but no-match simply doesn't set a reconciliation outcome.
- Reconciliation-clearing-on-edit applied to `executeClusterApply` in addition to `handleApplyTransform` because cluster merges change cell values and must also respect the "editing a reconciled cell drops the reconciliation" invariant.

## Deviations from Plan

None - plan executed exactly as written. All plan notes were implemented precisely:
1. normalizeValue imported from validationRuntime.ts (not duplicated)
2. 100-row confirmation toast reuses same sonner pattern as Phase 10 TransformBar
3. Auto-accept uses exactly-1-candidate AND normalized label match (no similarity threshold)
4. clear_reconciliation: true flag used in ALL three edit paths (transform, cluster, FieldsPane) — never reconciliation: null
5. Audit sources: reconciliation-auto, reconciliation-manual, reconciliation-no-match, reconciliation-cleared-by-edit all present

## Self-Check

Checking file existence and commits:

- `apps/frontend/src/features/clean/ColumnWorkspace.tsx` — FOUND (reconcilePaneSlot)
- `apps/frontend/src/features/clean/CandidateDrawer.tsx` — FOUND (153 lines, > 80 min)
- `apps/frontend/src/features/clean/ReconcilePane.tsx` — FOUND (211 lines, > 120 min)
- `apps/frontend/src/features/clean/CleanStep.tsx` — FOUND (reconcilePaneSlot, clear_reconciliation, handleCellReconciled)
- `apps/frontend/src/features/verify/FieldsPane.tsx` — FOUND (clear_reconciliation)
- Commit `2633a30` — FOUND
- Commit `a00031b` — FOUND
- TypeScript --noEmit: PASSED (zero errors)

## Self-Check: PASSED

## Issues Encountered

None. TypeScript compiled cleanly after all changes. All 8 plan verification checks passed on first attempt.

## Next Phase Readiness

- Wave 3 Plan 11-05 (URI emission in LIDO/MARCXML/Dublin Core + reconciliation Link2 badge) can execute
- ReconciliationOutcome.uri is available in results.validation[field].reconciliation.uri for export functions
- CandidateDrawer pattern established for potential reuse in Results table inline per-cell reconciliation
- No blockers

---
*Phase: 11-authority-reconciliation*
*Completed: 2026-05-18*
