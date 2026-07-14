---
phase: 07-uat-bug-fixes-session-lifecycle-batch-data-isolation-navigation-data-quality
plan: 03
subsystem: api, ui
tags: [batch-status, ocr, websocket, lido-xml, typescript]

# Dependency graph
requires:
  - phase: 07-uat-bug-fixes-session-lifecycle-batch-data-isolation-navigation-data-quality
    provides: Phase 07 plan context — UAT bug clusters and research notes
provides:
  - Batch archive displays correct completion status (completed/cancelled/failed) after OCR finishes
  - EditableCell commit strips trailing newlines (Ctrl+Enter or blur no longer injects \n)
  - LIDO-XML export uses generic "Karteikarte" instead of hardcoded "Tonbandkarteikarte"
  - Browser tab title shows "Indexcards OCR" instead of "frontend"
  - WebSocket cleanup guards CONNECTING state to prevent console warning
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "update_batch_status: read-modify-write JSON pattern matching existing batch_manager style"
    - "WebSocket CONNECTING guard: defer close() via onopen callback when readyState === CONNECTING"
    - "trailing newline trim: draft.replace(/\\n+$/, '') in EditableCell commit — preserves internal newlines"

key-files:
  created: []
  modified:
    - apps/backend/app/services/batch_manager.py
    - apps/backend/app/api/api_v1/endpoints/batches.py
    - apps/frontend/src/features/results/ResultsTable.tsx
    - apps/frontend/src/features/results/useResultsExport.ts
    - apps/frontend/src/features/processing/useProcessingWebSocket.ts
    - apps/frontend/index.html

key-decisions:
  - "update_batch_status placed in try block (success) and except block (failure) separately — not in finally — because status value differs between paths"
  - "Only trailing newlines stripped in EditableCell (not leading/spaces/internal) to preserve intentional multi-line content"
  - "Karteikarte is the generic German archival term for any index card type — correct replacement for Tonbandkarteikarte which was music-archive-specific"
  - "WebSocket CONNECTING guard: set onopen = () => ref.close() rather than calling close() immediately to avoid browser console warning"

patterns-established:
  - "Batch status lifecycle: uploaded → completed/cancelled/failed persisted via update_batch_status after run_ocr_task"

# Metrics
duration: ~5min
completed: 2026-02-23
---

# Phase 07 Plan 03: Data Quality and Cosmetic Bug Fixes Summary

**Batch status now persists to batches.json after OCR (completed/cancelled/failed); EditableCell trims trailing newlines; LIDO export uses generic Karteikarte; page title corrected; WebSocket cleanup guarded against CONNECTING race condition**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-23T19:50:12Z
- **Completed:** 2026-02-23T19:55:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- BUG-04: Batch archive now shows "completed", "cancelled", or "failed" after OCR finishes instead of staying stuck at "uploaded"
- BUG-08/09/10/11: Four frontend fixes in one commit — trailing newline trim, generic LIDO term, correct page title, WS race condition guard

## Task Commits

Each task was committed atomically:

1. **Task 1: Persist batch status after OCR completion (BUG-04)** - `9bfcfc8` (fix)
2. **Task 2: Fix trailing newline, LIDO hardcode, page title, WS race condition (BUG-08/09/10/11)** - `ca999b8` (fix)

**Plan metadata:** see final commit below

## Files Created/Modified
- `apps/backend/app/services/batch_manager.py` - Added `update_batch_status(batch_name, status)` method
- `apps/backend/app/api/api_v1/endpoints/batches.py` - Calls `update_batch_status` at end of try block and except block in `run_ocr_task`
- `apps/frontend/src/features/results/ResultsTable.tsx` - EditableCell commit trims trailing newlines via `draft.replace(/\n+$/, '')`
- `apps/frontend/src/features/results/useResultsExport.ts` - LIDO classification term changed from "Tonbandkarteikarte" to "Karteikarte"
- `apps/frontend/src/features/processing/useProcessingWebSocket.ts` - Cleanup defers `close()` via `onopen` callback when `readyState === CONNECTING`
- `apps/frontend/index.html` - Title changed from "frontend" to "Indexcards OCR"

## Decisions Made
- `update_batch_status` is placed in the try block and except block separately (not in finally) because the status value differs: try path uses `"cancelled" if cancel_event.is_set() else "completed"`, except path uses `"failed"`.
- Only trailing newlines stripped (not leading, not spaces, not internal newlines) to preserve intentional multi-line extracted text.
- "Karteikarte" is the correct generic German archival term for any index card type; "Tonbandkarteikarte" was a hardcoded music-archive-specific term that was inappropriate for other collection types.
- WebSocket CONNECTING guard pattern: set `ref.onopen = () => ref.close()` rather than calling `close()` directly to avoid the browser console warning "WebSocket is closed before connection is established".

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 5 data quality and cosmetic bugs from the plan are fixed (BUG-04, BUG-08, BUG-09, BUG-10, BUG-11)
- Phase 07 is now complete across all 3 plans (01: session lifecycle, 02: navigation + batch isolation, 03: data quality)
- BUG-14 (OCR field overflow) remains deferred as a prompt engineering issue per plan scope decision

---
*Phase: 07-uat-bug-fixes-session-lifecycle-batch-data-isolation-navigation-data-quality*
*Completed: 2026-02-23*

## Self-Check: PASSED

- FOUND: `.planning/phases/07-uat-bug-fixes.../07-03-SUMMARY.md`
- FOUND: `9bfcfc8` — fix(07-03): persist batch status after OCR completion (BUG-04)
- FOUND: `ca999b8` — fix(07-03): trailing newline, LIDO hardcode, page title, WS race condition
- FOUND: `5b6418e` — docs(07-03): complete data quality fixes plan
