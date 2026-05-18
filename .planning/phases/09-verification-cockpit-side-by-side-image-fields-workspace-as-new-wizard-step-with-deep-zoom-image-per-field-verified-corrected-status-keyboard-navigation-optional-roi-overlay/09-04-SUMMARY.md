---
phase: 09-verification-cockpit
plan: "04"
subsystem: ui
tags:
  - react
  - zustand
  - keyboard
  - validation
  - integration
dependency_graph:
  requires:
    - phase: "09-02"
      provides: "VerifyStep shell with CockpitLayout, ImagePane, Filmstrip; App.tsx routing; Sidebar 5th step"
    - phase: "09-03"
      provides: "FieldsPane, CockpitBadge, useVerifyKeyboard — field interaction components"
  provides:
    - "VerifyStep.tsx: fully integrated cockpit with FieldsPane in right pane, useVerifyKeyboard wired (J/K/V/Enter), Back to Results header, batch-level progress indicator"
    - "ResultsStep.tsx: 'Verify cards' button (ShieldCheck, archive-700) calling setStep('verify') in toolbar; visible with and without validation data"
    - "ValidationBadge.tsx: 'verified' status case (CheckCircle2, emerald-700) — distinct from plain valid (CheckCircle, emerald-600)"
  affects:
    - "Full Phase 9 feature: Results → cockpit → edit → back → badge flow complete"

tech_stack:
  added: []
  patterns:
    - "handleMarkVerified uses useWizardStore.setState direct call for V-shortcut status flip — same pattern as FieldsPane.handleCommit"
    - "Auto-save on cockpit exit is implicit: FieldsPane debounced PATCHes (300ms) flush naturally before Results view re-renders"
    - "verifiedCardCount useMemo counts cards with any verified field — batch-level progress without new store action"

key_files:
  created: []
  modified:
    - apps/frontend/src/features/verify/VerifyStep.tsx
    - apps/frontend/src/features/results/ResultsStep.tsx
    - apps/frontend/src/features/results/ValidationBadge.tsx

key-decisions:
  - "Verify cards button placed alongside ValidationFilterChips (not in WizardNav) — toolbar-level action visible at same scroll position as filter chips; also shown standalone for plain batches"
  - "verifiedCardCount progress indicator placed in cockpit header row (not Filmstrip) — global batch context while navigating cards"
  - "Auto-save on cockpit exit is implicit via debounce: no explicit flush needed; documented in comment in VerifyStep"

requirements-completed:
  - FR4
  - FR2

duration: ~2min
completed: "2026-05-18T07:59:28Z"
---

# Phase 9 Plan 04: Integration Summary

**Full cockpit wired end-to-end: FieldsPane in VerifyStep right pane, J/K/V/Enter keyboard shortcuts, 'Verify cards' entry button in ResultsStep, 'verified' status in ValidationBadge — Phase 9 production-ready.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-05-18T07:57:26Z
- **Completed:** 2026-05-18T07:59:28Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- VerifyStep now renders real FieldsPane (not placeholder) as the right pane of CockpitLayout
- useVerifyKeyboard wired with four handlers: J/K (next/prev card updating activeCardIndex), V (flip first pending field to verified via direct Zustand setState + debounced PATCH), Enter (accept first corrected proposal via existing acceptCorrectorProposal action)
- Back to Results button in cockpit header (ArrowLeft icon) calls setStep('results'); auto-save implicit via FieldsPane's 300ms debounce
- Batch-level progress indicator: "N of M cards touched" derived via useMemo from results array
- ResultsStep gains a "Verify cards" button (ShieldCheck icon, archive-700 background) shown alongside ValidationFilterChips; also visible for plain batches without validation data
- ValidationBadge now handles all 5 status values: skipped (null), valid (CheckCircle emerald-600), invalid (XCircle red-600), corrected (Wand2 amber-600), verified (CheckCircle2 emerald-700); previously fell through to `return null` for 'verified'

## Task Commits

1. **Task 1: Integrate FieldsPane + useVerifyKeyboard into VerifyStep** - `5c97647` (feat)
2. **Task 2: 'Verify cards' button in ResultsStep + ValidationBadge 'verified' status** - `4321a0b` (feat)

## Files Created/Modified

- `apps/frontend/src/features/verify/VerifyStep.tsx` — replaced placeholder right pane with FieldsPane; added useVerifyKeyboard with all four handlers; added Back to Results header button + progress indicator; activeCardIndex clamped via useEffect on filteredCards.length; imports: ArrowLeft, axios, FieldsPane, useVerifyKeyboard, useCallback, acceptCorrectorProposal
- `apps/frontend/src/features/results/ResultsStep.tsx` — added ShieldCheck import; added 'Verify cards' button calling setStep('verify'); button appears next to ValidationFilterChips and also standalone for batches with no validation data
- `apps/frontend/src/features/results/ValidationBadge.tsx` — added CheckCircle2 import; added 'verified' case with CheckCircle2 (emerald-700) before the `else { return null; }` fallthrough

## Decisions Made

- "Verify cards" button placed alongside ValidationFilterChips rather than in WizardNav — the toolbar-level placement is visible without scrolling, matching the "entry from results" design intent in CONTEXT.md
- A second standalone button block renders for batches without validation data per CONTEXT.md: "curators can use the cockpit even for fully-clean batches"
- V-shortcut uses the same `useWizardStore.setState` direct call pattern as FieldsPane.handleCommit — consistent with the Phase 9 Plan 03 decision to avoid a new setValidationStatus store action
- Auto-save on cockpit exit is implicit (debounce flushes within 300ms); documented as a comment in VerifyStep to explain the design intent to future maintainers

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 9 fully complete: upload → process → results → Verify cards → cockpit → edit field → badge turns verified → Back to Results → badge shows verified in both views
- ValidationBadge now handles all 5 status values; no silent badge failure for verified fields in Results view
- Phase 10 (OpenRefine-style Cleaning Stage) can begin: reads ResultRow.validation shape unchanged; 'verified' is now a first-class status in the contract

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `apps/frontend/src/features/verify/VerifyStep.tsx` | FOUND |
| `apps/frontend/src/features/results/ResultsStep.tsx` | FOUND |
| `apps/frontend/src/features/results/ValidationBadge.tsx` | FOUND |
| Commit 5c97647 | FOUND |
| Commit 4321a0b | FOUND |
| grep FieldsPane VerifyStep.tsx | PASS |
| grep useVerifyKeyboard VerifyStep.tsx | PASS |
| grep "Verify cards" ResultsStep.tsx | PASS |
| grep "verified" ValidationBadge.tsx | PASS |
| grep "CheckCircle2" ValidationBadge.tsx | PASS |
| tsc --noEmit (exit 0) | PASS |

---
*Phase: 09-verification-cockpit*
*Completed: 2026-05-18*
