---
phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick
plan: 07
subsystem: ui
tags: [react, tanstack-table, yet-another-react-lightbox, tailwindcss, typescript]

# Dependency graph
requires:
  - phase: 06-03
    provides: ResultsTable with multi-entry expansion, ThumbnailCell with hover preview and per-row Lightbox

provides:
  - ResultsTable with 5 fixed columns (thumbnail, filename, status, extraction, time)
  - Single shared Lightbox instance driven by lightboxSrc state
  - ThumbnailCell as text-link component with onOpenLightbox callback
  - Status column with inline error tooltip (title attribute) and retry button
  - Extraction column with all fields as dl/dd key-value pairs inside one cell

affects: [UAT-Test-7, UAT-Test-9, ResultsStep, phase-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single shared Lightbox pattern: one lightboxSrc state drives one <Lightbox> instance for all rows"
    - "dl/dd key-value grid: grid-cols-[auto_1fr] for field label + EditableCell pairs inside single table cell"
    - "Error as tooltip: title={r.error || undefined} on status chip instead of separate display area"

key-files:
  created: []
  modified:
    - apps/frontend/src/features/results/ThumbnailCell.tsx
    - apps/frontend/src/features/results/ResultsTable.tsx

key-decisions:
  - "Single shared Lightbox in ResultsTable (not per-row): one lightboxSrc state + one <Lightbox> instance; ThumbnailCell calls onOpenLightbox callback prop"
  - "Error message as native browser tooltip on status chip (title attribute) — no separate display area or column"
  - "Retry button rendered inside status column below status chip — no separate actions column"
  - "Extraction column uses dl/dd definition list with grid-cols-[auto_1fr] for aligned key-value pairs"
  - "ThumbnailCell renders text link with Image icon — zero <img> DOM nodes per row; eliminates DOM explosion at 500+ rows"
  - "Visible fields filter: fields.filter(f => !f.startsWith('_')) excludes internal fields (_entries, _entry_count) from Extraction column"

patterns-established:
  - "Callback-based lightbox: child component receives (imageUrl: string) => void prop, parent owns open/close state"
  - "Merged column pattern: status/retry/error co-located in single cell as flex-col items-start for vertical stack"

# Metrics
duration: ~3min
completed: 2026-02-23
---

# Phase 06 Plan 07: Results Table Layout Restructure & Thumbnail DOM Performance Summary

**ResultsTable restructured to 5 columns with single Extraction dl/dd column, merged status/retry/error cell, and shared Lightbox — closes UAT Tests 7 and 9**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-23T17:40:15Z
- **Completed:** 2026-02-23T17:43:15Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- ThumbnailCell rewritten as lightweight text-link (Image icon + filename) with `onOpenLightbox` callback prop — zero `<img>` DOM nodes per row, eliminating DOM explosion at 500+ rows (UAT Test 9)
- ResultsTable restructured: N per-field columns replaced with single "Extraction" column rendering all fields as `<dl>` key-value pairs using `grid-cols-[auto_1fr]` layout (UAT Test 7)
- Separate "actions" column removed; retry button and error tooltip merged into status column — error appears as native browser tooltip via `title={r.error}`, retry button renders below status chip for failed rows
- Single shared `<Lightbox>` instance added at component level driven by `lightboxSrc` state; `ThumbnailCell` receives `onOpenLightbox` callback; Lightbox import moved from ThumbnailCell to ResultsTable

## Task Commits

Each task was committed atomically:

1. **Task 1: Simplify ThumbnailCell to text link with shared lightbox callback** - `950136c` (refactor)
2. **Task 2: Restructure ResultsTable — single Extraction column, merged status column, shared Lightbox** - `a833ade` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `apps/frontend/src/features/results/ThumbnailCell.tsx` - Rewritten as text-link button with Image icon; `onOpenLightbox` callback prop replaces per-row Lightbox; all image/hover/preview logic removed
- `apps/frontend/src/features/results/ResultsTable.tsx` - Column definitions restructured: field spread removed, single `extraction` column with `<dl>` added, `actions` column removed, retry+error merged into `status` column, shared `<Lightbox>` added at component level

## Decisions Made

- Single shared Lightbox in ResultsTable (not per-row): one `lightboxSrc` state + one `<Lightbox>` instance; ThumbnailCell calls `onOpenLightbox` callback prop — eliminates N Lightbox mount/unmount cycles
- Error message as native browser tooltip on status chip (`title` attribute) — no separate display area or column
- Retry button rendered inside status column below status chip — no separate actions column
- Extraction column uses `dl/dd` definition list with `grid-cols-[auto_1fr]` for aligned key-value pairs
- Visible fields filter: `fields.filter(f => !f.startsWith('_'))` excludes internal fields (`_entries`, `_entry_count`) from Extraction column

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. TypeScript typecheck and production build both passed on first attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- UAT Tests 7 and 9 are resolved — results table is usable for 500+ row batches
- Extraction column provides compact key-value view; all fields visible without horizontal scrolling
- Status column is self-contained: chip + tooltip + retry in one cell
- Ready for final UAT sign-off

## Self-Check: PASSED

- FOUND: apps/frontend/src/features/results/ThumbnailCell.tsx
- FOUND: apps/frontend/src/features/results/ResultsTable.tsx
- FOUND: .planning/phases/06-.../06-07-SUMMARY.md
- FOUND commit 950136c: refactor(06-07): simplify ThumbnailCell to text-link
- FOUND commit a833ade: feat(06-07): restructure ResultsTable

---
*Phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick*
*Completed: 2026-02-23*
