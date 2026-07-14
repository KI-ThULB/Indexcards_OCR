---
phase: 12-cross-phase-integration-fixes
plan: "03"
subsystem: frontend-verify
tags: [cockpit-badge, reconciliation, link2, ux-consistency, fr4]
dependency_graph:
  requires: ["12-01"]
  provides: ["CockpitBadge Link2 reconciliation icon + tooltip"]
  affects: ["apps/frontend/src/features/verify/CockpitBadge.tsx"]
tech_stack:
  added: []
  patterns: ["onMouseEnter/Leave tooltip", "reconTooltipOpen independent state", "sibling badge pattern"]
key_files:
  created: []
  modified:
    - apps/frontend/src/features/verify/CockpitBadge.tsx
key_decisions:
  - "Port ValidationBadge reconciliation block verbatim — same tooltip markup, classes, and onMouseEnter/Leave pattern"
  - "reconTooltipOpen state is fully independent of primary tooltipOpen — no interference with Accept/Reject corrected-status tooltip"
  - "Early-return guard for skipped/null outcome now checks reconciliation first and renders Link2-only span before returning null — matches ValidationBadge lines 22-51 nuance exactly"
  - "Main return restructured from single relative span to two-sibling pattern (status icon span + reconciliation badge span)"
  - "Preserved status !== 'corrected' onMouseLeave guard on primary status tooltip unchanged"
  - "Import source kept as '../../api/batchesApi' (not wizardStore) — CockpitBadge pattern unchanged"
metrics:
  duration: ~3min
  completed: 2026-05-19
  tasks_completed: 1
  files_modified: 1
requirements: [FR4]
---

# Phase 12 Plan 03: CockpitBadge Reconciliation Link2 Badge Summary

**One-liner:** Ported Phase 11's Link2 reconciliation icon + tooltip from ValidationBadge (Results view) to CockpitBadge (Verify cockpit), including the skipped-status-shows-reconciliation edge-case nuance.

## What Was Built

Fix 3 of Phase 12: curators in the Verify cockpit now see the Link2 reconciliation icon alongside the validation status icon on any field that has been reconciled against an authority (GND, Wikidata, GeoNames, Getty AAT). Hovering the icon shows a tooltip with the reconciliation label, authority name, and a clickable URI that opens in a new tab.

This closes the FR4 UX consistency gap documented in `v1.0-MILESTONE-AUDIT.md` — curators no longer have to switch to the Results view to check whether a field has a reconciliation URI.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Port reconciliation Link2 badge from ValidationBadge into CockpitBadge | 927516d | apps/frontend/src/features/verify/CockpitBadge.tsx |

## Implementation Detail

Four targeted additions to `CockpitBadge.tsx`:

1. **Import**: Added `Link2` to existing lucide-react import (alongside CheckCircle, CheckCircle2, XCircle, Wand2).
2. **State**: Added `const [reconTooltipOpen, setReconTooltipOpen] = useState(false)` after existing `tooltipOpen`.
3. **Reconciliation extraction**: Added `const reconciliation = outcome?.reconciliation ?? null` before the early-return guard so it is available in both branches.
4. **Early-return nuance**: The existing `if (!outcome || outcome.status === 'skipped') return null` was extended — it now checks for reconciliation first and renders a Link2-only span (no status icon) when reconciliation is set, matching ValidationBadge lines 22–51 exactly.
5. **Main return**: Restructured from a single `<span>` wrapping status icon + primary tooltip into the two-sibling pattern from ValidationBadge: status icon span (with existing `status !== 'corrected'` onMouseLeave guard preserved) followed by a conditional reconciliation badge span.

## Deviations from Plan

None — plan executed exactly as written. The plan's 5 numbered additions (import, state, extraction, early-return nuance, main return) were all applied. The ValidationBadge tooltip markup was ported verbatim including `pointer-events-auto` on the tooltip span for hover-stability and `aria-label` on the Link2 icon.

## Verification

- `grep -E "Link2|reconciliation|reconTooltipOpen"` — all three strings found in CockpitBadge.tsx
- `npx tsc --noEmit` — exit code 0, no TypeScript errors
- `grep -q "Link2" apps/frontend/src/features/verify/CockpitBadge.tsx` — exits 0
- `grep -q "reconTooltipOpen" apps/frontend/src/features/verify/CockpitBadge.tsx` — exits 0
- `grep -q "reconciliation" apps/frontend/src/features/verify/CockpitBadge.tsx` — exits 0

## Self-Check: PASSED

Files exist:
- FOUND: apps/frontend/src/features/verify/CockpitBadge.tsx

Commits exist:
- FOUND: 927516d (feat(12-03): port reconciliation Link2 badge from ValidationBadge to CockpitBadge)
