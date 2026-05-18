---
phase: 10-openrefine-style-cleaning-stage
plan: 03
subsystem: ui
tags: [react, typescript, fingerprint-clustering, faceting, text-facet, pattern-facet, regex-safety]

# Dependency graph
requires:
  - phase: 10-01
    provides: "validationRuntime.ts with normalizeValue() (ß→ss workaround) + expandResults.ts DisplayRow type"
provides:
  - "fingerprint.ts: computeFingerprint() + buildClusters() pure TS functions importing normalizeValue from validationRuntime"
  - "ClusterPicker.tsx: table of fingerprint clusters with editable canonical input, Apply/Skip actions, skip-hide session state"
  - "FacetPanel.tsx: tab container switching between TextFacet and PatternFacet with active-facet row-count chip"
  - "TextFacet.tsx: unique-value list with frequency counts, multi-select click-to-filter, Clear button"
  - "PatternFacet.tsx: regex input with try/catch guard, red border + 'Invalid regex' label on malformed input"
affects: ["10-04"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "fingerprint reuses normalizeValue() from validationRuntime — single source of truth; no duplication"
    - "PatternFacet try/catch guard: all regex construction wrapped; patternError flag propagates to parent, never throws to render cycle"
    - "patternMatchCount computed in FacetPanel (parent owns computation); PatternFacet is display-only for input"
    - "ClusterPicker resetKey prop clears skipped/edited state on column switch"

key-files:
  created:
    - apps/frontend/src/features/clean/fingerprint.ts
    - apps/frontend/src/features/clean/ClusterPicker.tsx
    - apps/frontend/src/features/clean/FacetPanel.tsx
    - apps/frontend/src/features/clean/TextFacet.tsx
    - apps/frontend/src/features/clean/PatternFacet.tsx
  modified: []

key-decisions:
  - "fingerprint.ts imports normalizeValue from validationRuntime — no separate normalization implementation; the same ß→ss pipeline powers both vocab matching (Phase 8) and fingerprint clustering"
  - "PatternFacet is display-only: matchCount computed by FacetPanel parent via its own try/catch; two layers of regex safety"
  - "ClusterPicker exposes resetKey prop so parent (ColumnWorkspace in 10-04) can reset skipped/edited-canonical state when user switches columns"
  - "TextFacet max-h-48 with overflow-y-auto: bounded scroll height prevents layout overflow in tall column lists"

# Metrics
duration: ~3min
completed: 2026-05-18
---

# Phase 10 Plan 03: Fingerprint Clustering + Faceting Engine Summary

**fingerprint.ts imports normalizeValue() from validationRuntime (ß→ss, single source of truth); buildClusters() returns near-duplicate groups sorted by rowCount desc; ClusterPicker renders editable merge table; TextFacet + PatternFacet with try/catch regex guard wired in FacetPanel tab container**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-18T09:39:05Z
- **Completed:** 2026-05-18T09:41:35Z
- **Tasks:** 2
- **Files created:** 5

## Accomplishments

- `fingerprint.ts` built as pure TS: `computeFingerprint()` calls `normalizeValue()` imported from `validationRuntime.ts` — identical ß→ss normalization to Phase 8 vocab rules, no duplication risk. Token deduplication added before sort (OpenRefine canonical fingerprint). `buildClusters()` filters to 2+ distinct values, sorts by rowCount descending.
- `ClusterPicker.tsx` table: variants (first 4 + "+N more" overflow), row count, editable canonical input, Apply / Skip per cluster. Skipped clusters hidden for session; `resetKey` prop clears skipped/edited state on column switch.
- `TextFacet.tsx`: `useMemo` derives valueCounts + sortedValues (frequency desc); scrollable list (max-h-48) with click-toggle multi-select, Clear button when selection non-empty.
- `PatternFacet.tsx`: onChange handler wraps `new RegExp(val, 'u')` in try/catch — `hasError = true` on SyntaxError, never propagates to render cycle. Red border + "Invalid regex" label visible when `patternError` is true.
- `FacetPanel.tsx`: tab container (Text facet / Pattern facet) with Filter icon header; computes `patternMatchCount` via its own try/catch for safety; amber chip shows filtered row count when any facet active.
- TypeScript `--noEmit` passes cleanly across all 5 new files and the full project.

## Task Commits

1. **Task 1: fingerprint.ts + ClusterPicker table UI** — `9c51f50` (feat)
2. **Task 2: FacetPanel with TextFacet and PatternFacet (regex guard)** — `c3b38b2` (feat)

## Files Created/Modified

- `apps/frontend/src/features/clean/fingerprint.ts` — (created) computeFingerprint() + buildClusters() importing normalizeValue from validationRuntime
- `apps/frontend/src/features/clean/ClusterPicker.tsx` — (created) cluster table with variants/rowCount/editable-canonical/Apply+Skip
- `apps/frontend/src/features/clean/TextFacet.tsx` — (created) unique-value list with counts + multi-select click-to-filter
- `apps/frontend/src/features/clean/PatternFacet.tsx` — (created) regex input with try/catch guard + red error indicator
- `apps/frontend/src/features/clean/FacetPanel.tsx` — (created) tab container for TextFacet/PatternFacet with active-facet chip

## Decisions Made

- Imported `normalizeValue` from `validationRuntime.ts` rather than duplicating the normalization logic — critical for Phase 8 vocab matches and fingerprint clusters to agree on the same strings
- Added token deduplication (`new Set(tokens)`) before sort in `computeFingerprint` to match OpenRefine canonical fingerprint behavior
- `PatternFacet` is display-only for the input; `patternMatchCount` owned by `FacetPanel` parent — cleaner separation, and the parent already has access to `displayRows` for filtering

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 10-04 can mount `FacetPanel` and `ClusterPicker` into `ColumnWorkspace` using the exposed props
- `ClusterPicker` needs `resetKey` wired to `activeColumn` in `ColumnWorkspace`
- `FacetPanel` props (`displayRows`, `field`, `facetState`, `onFacetChange`, `facetedRowCount`) are all available from `CleanStep` / `useCleanState`

## Self-Check

- `fingerprint.ts` exists: FOUND
- `ClusterPicker.tsx` exists: FOUND
- `FacetPanel.tsx` exists: FOUND
- `TextFacet.tsx` exists: FOUND
- `PatternFacet.tsx` exists: FOUND
- `normalizeValue` imported from `validationRuntime`: PASS
- `try/catch` guard in `PatternFacet.tsx`: PASS
- TypeScript `--noEmit` clean: PASS (no errors)
- Task 1 commit `9c51f50`: FOUND
- Task 2 commit `c3b38b2`: FOUND

## Self-Check: PASSED

---
*Phase: 10-openrefine-style-cleaning-stage*
*Completed: 2026-05-18*
