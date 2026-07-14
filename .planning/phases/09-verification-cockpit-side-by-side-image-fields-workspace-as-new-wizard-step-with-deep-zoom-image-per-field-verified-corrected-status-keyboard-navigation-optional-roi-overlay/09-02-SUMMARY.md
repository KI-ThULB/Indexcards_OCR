---
phase: 09-verification-cockpit
plan: "02"
subsystem: ui
tags:
  - react
  - zustand
  - tailwind
  - image-zoom
  - drag-pan
  - filmstrip
  - sidebar

dependency_graph:
  requires:
    - phase: 09-01
      provides: "WizardStep 'verify' in wizardStore; cockpitSplitPercent state + setCockpitSplitPercent; useResultsQuery pattern"
  provides:
    - "VerifyStep.tsx — top-level cockpit container with useResultsQuery hydration, filter state, activeCardIndex, renders CockpitLayout + Filmstrip"
    - "CockpitLayout.tsx — resizable 50/50 horizontal split with drag handle; reads/writes cockpitSplitPercent to Zustand"
    - "ImagePane.tsx — full-res JPEG with CSS transform wheel-zoom (passive:false) + drag-pan + double-click-reset"
    - "Filmstrip.tsx — horizontal thumbnail strip with filter chips (all/invalid/corrected/valid/verified), status dots, active-card highlight + auto-scroll"
    - "App.tsx: case 'verify' renders VerifyStep"
    - "Sidebar: 5th step 'Verify' with ShieldCheck icon; stepOrder includes 'verify'; handleStepClick explicit 'verify' case gated on batchId"
    - "ValidationFilter type extended to include 'verified'; ValidationFilterChips extended with 'Curator Verified' chip"
  affects:
    - apps/frontend/src/features/verify/FieldsPane.tsx
    - "09-03 plan (FieldsPane plugs into the right slot of CockpitLayout via VerifyStep)"
    - "09-04 plan (VerifyStep shell is the integration target)"

tech_stack:
  added: []
  patterns:
    - "useRef for image transform state (scale/tx/ty) avoids re-renders on every animation frame"
    - "addEventListener with { passive: false } on wheel events — required to call preventDefault() for zoom-within-pane"
    - "Drag-handle uses local splitPercent state for live drag, writes to Zustand only on mouseup (avoid store thrash)"
    - "Filmstrip filterCards() pure helper exported for testing; auto-scroll via scrollIntoView({ inline: 'center' })"

key_files:
  created:
    - apps/frontend/src/features/verify/VerifyStep.tsx
    - apps/frontend/src/features/verify/CockpitLayout.tsx
    - apps/frontend/src/features/verify/ImagePane.tsx
    - apps/frontend/src/features/verify/Filmstrip.tsx
  modified:
    - apps/frontend/src/App.tsx
    - apps/frontend/src/components/Sidebar.tsx
    - apps/frontend/src/features/results/ValidationFilterChips.tsx
    - apps/frontend/src/features/results/ResultsTable.tsx
    - apps/frontend/src/features/verify/FieldsPane.tsx

key-decisions:
  - "ImagePane uses CSS transform scale+translate on <img> ref — no library, same approach as existing ImagePreview; useRef for transform state avoids re-render storm"
  - "Filmstrip filterCards() exported as pure helper to allow VerifyStep to reuse filtering logic for its own activeCard derivation"
  - "Sidebar isClickable extended: 'verify' is clickable only when batchId is set (mirrors 'results' pattern)"
  - "ValidationFilter extended to include 'verified' — backward-compatible (counts.verified optional in ResultsStep, chip shows count 0)"

requirements-completed:
  - FR4

duration: "~5min"
completed: "2026-05-18T07:53:15Z"
---

# Phase 9 Plan 02: Cockpit Shell Summary

**Resizable 50/50 split cockpit shell with CSS transform wheel-zoom image pane, filmstrip card navigator, and Sidebar/App.tsx routing — complete navigable skeleton for the Verify wizard step**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-18T07:47:29Z
- **Completed:** 2026-05-18T07:53:15Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Full cockpit shell: CockpitLayout (resizable split), ImagePane (wheel-zoom + drag-pan + double-click-reset), VerifyStep (card carousel + filter state), Filmstrip (thumbnail strip + filter chips + status dots)
- Sidebar wired with explicit 'verify' case in handleStepClick (gated on batchId) and 5th step entry with ShieldCheck icon
- App.tsx routes 'verify' step to VerifyStep; TypeScript compiles clean with no new errors
- Extended ValidationFilter type to include 'verified'; added 'Curator Verified' chip to ValidationFilterChips

## Task Commits

Each task was committed atomically:

1. **Task 1: CockpitLayout + ImagePane + VerifyStep shell** - `1f31946` (feat)
2. **Task 2: Filmstrip + App.tsx routing + Sidebar 5th step** - `388e610` (feat)

**Plan metadata:** (created after state updates)

## Files Created/Modified
- `apps/frontend/src/features/verify/VerifyStep.tsx` — top-level cockpit container; useResultsQuery hydration; filter/activeCard state; renders CockpitLayout + Filmstrip
- `apps/frontend/src/features/verify/CockpitLayout.tsx` — 50/50 resizable split pane with drag handle; reads cockpitSplitPercent from Zustand; writes only on mouseup
- `apps/frontend/src/features/verify/ImagePane.tsx` — full-res JPEG viewer; wheel zoom with { passive: false } addEventListener; drag-pan; double-click-reset; hint overlay
- `apps/frontend/src/features/verify/Filmstrip.tsx` — horizontal thumbnail strip; per-filter counts; status dots (red/amber/green/teal/grey); auto-scroll active thumbnail
- `apps/frontend/src/App.tsx` — added `case 'verify': return <VerifyStep />`; imported VerifyStep
- `apps/frontend/src/components/Sidebar.tsx` — stepOrder extended; handleStepClick 'verify' case; isClickable includes verify; STEPS array 5th entry; ShieldCheck icon
- `apps/frontend/src/features/results/ValidationFilterChips.tsx` — ValidationFilter type extended to include 'verified'; 'verified' count optional in props; count ?? 0 guard
- `apps/frontend/src/features/results/ResultsTable.tsx` — pre-existing TS2367 bug fixed (unreachable `=== 'all'` comparison)
- `apps/frontend/src/features/verify/FieldsPane.tsx` — pre-existing TS6133 bug fixed (unused React default import from 09-03 commit)

## Decisions Made
- ImagePane transform state stored in useRef (not useState) — eliminates re-renders on every wheel/mouse event frame, matches existing ImagePreview pattern
- Drag-handle writes to Zustand only on mouseup (not during live drag) — prevents store thrash from continuous mousemove events
- Filmstrip filterCards() exported as a pure helper function — VerifyStep imports it to derive the activeCard from the same filter logic without duplication
- ValidationFilter 'verified' count is optional in ValidationFilterChips props — existing ResultsStep callers unchanged, chip shows 0 in Results view (harmless)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed unreachable type comparison in ResultsTable.tsx**
- **Found during:** Task 2 (TypeScript compilation check)
- **Issue:** Pre-existing TS2367 error at line 65: `validationFilter === 'all'` inside a branch already guarded by `if (validationFilter === 'all') return results` at line 63, making the inner comparison unreachable and flagged by TypeScript. Not caused by this plan — pre-existed before Wave 2.
- **Fix:** Changed `return validationFilter === 'all'` to `return false` (correct behavior: rows without validation data are excluded from non-'all' filters)
- **Files modified:** `apps/frontend/src/features/results/ResultsTable.tsx`
- **Committed in:** 388e610 (Task 2 commit)

**2. [Rule 1 - Bug] Removed unused React default import in FieldsPane.tsx**
- **Found during:** Task 2 (TypeScript compilation check)
- **Issue:** Pre-existing TS6133 error — `React` imported but never used in FieldsPane.tsx (committed by 09-03 before this plan ran). Not in scope per the plan boundary, but caused a TypeScript error in the project.
- **Fix:** Changed `import React, { useState, ... }` to `import { useState, ... }` (React 19 JSX transform doesn't need the default import)
- **Files modified:** `apps/frontend/src/features/verify/FieldsPane.tsx`
- **Committed in:** 388e610 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — pre-existing TypeScript errors from prior plan commits)
**Impact on plan:** Both fixes necessary for clean TypeScript compilation. No scope creep — both were direct causes of compilation failures discovered during this plan's verification step.

## Issues Encountered
- Plan 09-03 had already partially executed (committed CockpitBadge.tsx, useVerifyKeyboard.ts, FieldsPane.tsx to HEAD) before this plan started. No file overlap per the plan's parallel isolation boundary — all three Task 1 files (CockpitLayout, ImagePane, VerifyStep) were untracked. Wave 2 parallel execution confirmed safe.

## User Setup Required
None - no external service configuration required. The cockpit shell is navigable immediately from the Sidebar.

## Next Phase Readiness
- Cockpit shell fully navigable: Sidebar 'Verify' step → VerifyStep renders with image pane and filmstrip
- FieldsPane (from 09-03) ready to replace the placeholder `<div>Field pane (Plan 09-03)</div>` — that integration is the target of 09-04
- Wave 3 plan (09-04): wire FieldsPane into VerifyStep, keyboard shortcuts, 'Verify cards' entry in ResultsStep, ValidationBadge 'verified' icon

---
*Phase: 09-verification-cockpit*
*Completed: 2026-05-18*
