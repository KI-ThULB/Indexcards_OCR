---
phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick
plan: 08
subsystem: ui
tags: [react, tanstack-table, textarea, tailwindcss, uat-gap-closure]

# Dependency graph
requires:
  - phase: 06-07
    provides: "ResultsTable restructure — single Extraction dl/dd column, merged status column, shared Lightbox"
provides:
  - "EditableCell with auto-resizing textarea (Ctrl+Enter commit, Escape cancel, plain Enter newline)"
  - "whitespace-pre-wrap display for multiline OCR values"
  - "Filename column removed; entry labels relocated into Image column"
  - "Column order: Image, Status, Time, Extraction"
affects: [results-table, uat-tests]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Auto-resize textarea pattern: set height to 'auto' then scrollHeight on mount and onChange"
    - "Keyboard modifiers for textarea commit: Ctrl+Enter or Cmd+Enter to commit, Escape to cancel, plain Enter for newline"

key-files:
  created: []
  modified:
    - apps/frontend/src/features/results/ResultsTable.tsx

key-decisions:
  - "EditableCell uses textarea with resize-none overflow-hidden and explicit auto-resize logic instead of browser-native resize handle"
  - "Entry labels for multi-entry rows moved into Image column (thumbnail column) — primary row shows ThumbnailCell + badge below; sub-rows show badge only"
  - "Column order fixed as Image, Status, Time, Extraction — Extraction widest/last per UAT requirement"

patterns-established:
  - "whitespace-pre-wrap on EditableCell display span preserves multiline OCR output line breaks"
  - "Ctrl/Cmd+Enter to commit textarea edit is the explicit commit gesture; onBlur also commits"

# Metrics
duration: 5min
completed: 2026-02-23
---

# Phase 06 Plan 08: UAT Gap Closure — textarea editing, remove filename column, reorder columns

**EditableCell converted to auto-resizing textarea with Ctrl+Enter commit; redundant filename column removed and entry labels moved into Image column; column order fixed to Image, Status, Time, Extraction**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-23T18:10:46Z
- **Completed:** 2026-02-23T18:16:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- UAT Test 1 (major) resolved: EditableCell now renders `<textarea>` with auto-resize on mount and onChange; Ctrl+Enter or Cmd+Enter commits, Escape cancels, plain Enter inserts newline; display mode uses `whitespace-pre-wrap` for multiline values
- UAT Test 5 (minor) resolved: Filename column (`id: 'filename'`) removed entirely; entry labels for multi-entry rows (Findmittel) relocated into the Image column cell — primary multi-entry row shows ThumbnailCell plus entry badge below; sub-rows show entry badge only
- UAT Test 7 (cosmetic) resolved: Column order is now Image, Status, Time, Extraction — Duration column moved before Extraction so widest column is last

## Task Commits

Each task was committed atomically:

1. **Task 1 + Task 2: Convert EditableCell to textarea, remove filename column, reorder columns** - `49e4c25` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `apps/frontend/src/features/results/ResultsTable.tsx` - EditableCell textarea conversion; filename column removed; entry labels in Image column; column order updated to Image, Status, Time, Extraction

## Decisions Made

- Entry labels previously shown in a separate "File" column are now rendered inside the Image column: the primary row of a multi-entry page shows a `flex-col` with ThumbnailCell and an entry badge; sub-rows show only the entry badge. This keeps all image/file identity information in a single column.
- Auto-resize logic implemented with the standard `height = 'auto'` then `height = scrollHeight + 'px'` pattern, applied both on edit-mode mount (useEffect) and on every change event.
- `resize-none overflow-hidden` Tailwind classes prevent the user from dragging the textarea handle while still allowing programmatic height expansion.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three UAT gap items (Tests 1, 5, 7) are now addressed in code.
- TypeScript typecheck passes with zero errors.
- Ready for UAT re-verification: visit the Results step with multi-entry or multiline OCR data, confirm textarea editing, confirm 4-column layout with no filename column, confirm Time before Extraction.

---
*Phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick*
*Completed: 2026-02-23*

## Self-Check: PASSED

- FOUND: `apps/frontend/src/features/results/ResultsTable.tsx`
- FOUND: `.planning/phases/06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick/06-08-SUMMARY.md`
- FOUND: commit `49e4c25` — feat(06-08): close UAT gaps — textarea editing, remove filename column, reorder columns
