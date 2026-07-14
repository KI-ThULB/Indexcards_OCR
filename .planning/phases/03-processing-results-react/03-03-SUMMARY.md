---
phase: 03-processing-results-react
plan: 03
subsystem: ui
tags: [react, zustand, tanstack-table, yet-another-react-lightbox, tailwind, csv-export, json-export]

# Dependency graph
requires:
  - phase: 03-processing-results-react
    plan: 01
    provides: "GET /batches/{name}/results, POST /retry-image, POST /retry, StaticFiles /batches-static"
  - phase: 03-processing-results-react
    plan: 02
    provides: "useResultsQuery, useRetryBatchMutation, useRetryImageMutation, ResultRow, Zustand results slice"
provides:
  - "ResultsStep component: fetches and displays OCR results in sortable/editable table"
  - "ResultsTable: TanStack React Table v8 with dynamic field columns, inline editing with audit trail dot indicator, status color-coding, per-row retry"
  - "ThumbnailCell: img with YARL lightbox overlay and ImageOff fallback"
  - "SummaryBanner: stat grid + Download CSV/JSON/Retry All Failed buttons"
  - "useResultsExport: CSV with UTF-8 BOM + CRLF, JSON with per-field ocr/edited audit trail"
affects: []

# Tech tracking
tech-stack:
  added:
    - "@tanstack/react-table@8.21.3 — sortable data table with dynamic columns"
    - "yet-another-react-lightbox@3.29.1 — full-size image lightbox overlay"
  patterns:
    - "Tailwind JIT-safe status colors: static lookup map instead of string concatenation"
    - "EditableCell: display/edit toggle with draft state, blur+Enter commit, edit indicator dot"
    - "hydratedRef guard: prevents duplicate setResults if parent re-renders while useResultsQuery resolves"
    - "Merge existing editedData over fresh backend data: preserves user corrections across re-mounts"
    - "UTF-8 BOM (\\uFEFF) + CRLF for CSV Excel compatibility"
    - "JSON audit trail: per-field { ocr, edited? } — edited key only included if user modified value"

key-files:
  created:
    - apps/frontend/src/features/results/ResultsStep.tsx
    - apps/frontend/src/features/results/SummaryBanner.tsx
    - apps/frontend/src/features/results/ResultsTable.tsx
    - apps/frontend/src/features/results/ThumbnailCell.tsx
    - apps/frontend/src/features/results/useResultsExport.ts
  modified:
    - apps/frontend/package.json
    - apps/frontend/src/App.tsx

key-decisions:
  - "Hydrate from GET /batches/{name}/results on mount (not WS stream alone) — WS can have gaps from reconnects; REST endpoint is authoritative"
  - "hydratedRef prevents double-setResults on React Strict Mode double-invoke"
  - "Merge editedData from existing store over fresh API data — preserves user corrections within session"
  - "Tailwind JIT lookup map for status colors — string concatenation (text-${status}-700) would be purged"
  - "retryImage navigates to processing step — single-image retry starts a new WS stream; handleRetryAllFailed uses retryBatch mutation which fires POST /retry"

# Metrics
duration: ~3min
completed: 2026-02-21
---

# Phase 03 Plan 03: Results Step (React) Summary

**Sortable/editable TanStack Table results view with YARL lightbox thumbnails, inline cell editing with audit trail, per-row and bulk retry, and UTF-8 BOM CSV + structured JSON export**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-21T11:13:04Z
- **Completed:** 2026-02-21T11:15:39Z
- **Tasks:** 2
- **Files created:** 5
- **Files modified:** 2

## Accomplishments

- ResultsStep fetches authoritative results from `GET /batches/{name}/results`, transforms to `ResultRow[]`, and merges existing `editedData` to preserve user corrections across re-mounts
- ResultsTable renders a sortable `@tanstack/react-table` v8 table with dynamic field columns, EditableCell with display/edit toggle and edit indicator dot, status badge with safe color lookup map, per-row Retry button for failed images
- ThumbnailCell shows `w-16 h-12` thumbnail from `/batches-static/{batch}/{file}` with YARL lightbox on click and `ImageOff` fallback on load error
- SummaryBanner displays processed/success/error count, total duration, batch name, and Download CSV/JSON/Retry All Failed action buttons
- useResultsExport generates UTF-8 BOM CSV with `_ocr`/`_edited` columns per field and JSON with conditional `edited` key (audit trail)
- App.tsx replaces placeholder div with `<ResultsStep />`; no placeholder divs remain

## Task Commits

Each task was committed atomically:

1. **Task 1: Install deps, build ResultsTable, ThumbnailCell, SummaryBanner** - `310da65` (feat)
2. **Task 2: Create useResultsExport, ResultsStep, wire App.tsx** - `2221dee` (feat)

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified

- `apps/frontend/src/features/results/ResultsStep.tsx` - Main orchestrator: fetches results, merges edits, delegates to SummaryBanner + ResultsTable, handles retry navigation and new batch reset
- `apps/frontend/src/features/results/ResultsTable.tsx` - TanStack React Table v8: sortable columns, EditableCell, status lookup, dynamic field columns, error column, retry button
- `apps/frontend/src/features/results/ThumbnailCell.tsx` - img thumbnail with YARL lightbox and error fallback
- `apps/frontend/src/features/results/SummaryBanner.tsx` - stat grid + action buttons (CSV/JSON/retry-all)
- `apps/frontend/src/features/results/useResultsExport.ts` - CSV (UTF-8 BOM, CRLF, _ocr/_edited) and JSON (per-field ocr+edited audit trail) export via Blob + anchor
- `apps/frontend/package.json` - Added @tanstack/react-table and yet-another-react-lightbox
- `apps/frontend/src/App.tsx` - Replaced results placeholder div with `<ResultsStep />`

## Decisions Made

- **Hydrate from REST, not WS stream:** WS stream can have gaps from reconnects. `useResultsQuery(batchId)` hitting `GET /batches/{name}/results` is the authoritative source of truth.
- **hydratedRef guard:** Prevents `setResults` from double-firing on React Strict Mode double-invoke, which would overwrite a first-pass results array with a second-pass empty merge.
- **Merge editedData on hydration:** Fresh API data overwrites `data` fields but the existing `editedData` map is preserved. Museum staff corrections survive re-navigating to results within a session.
- **Tailwind JIT-safe status colors:** Static `statusStyles` lookup map instead of template literals (`text-${status}-700`) which Tailwind JIT purges at build time.
- **retryImage navigates to processing step:** Single-image retry starts a new WS stream; the user must watch processing to see the retry result. Bulk retry uses `retryBatch` (POST /retry) for the same reason.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None.

## Next Phase Readiness

- Phase 03 is now complete: all three plans (backend prerequisites, processing step, results step) are implemented
- The full wizard flow is end-to-end: Upload → Configure → Processing (WebSocket) → Results (editable table + export)
- No further frontend work planned; next phases would be polish, testing, or deployment

## Self-Check: PASSED
