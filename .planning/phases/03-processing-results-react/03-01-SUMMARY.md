---
phase: 03-processing-results-react
plan: 01
subsystem: api
tags: [fastapi, websocket, threading, staticfiles, vite, cancellation, checkpoint]

# Dependency graph
requires:
  - phase: 02-frontend-scaffold-configuration-react
    provides: batches API, batch_manager service, ocr_engine service, ws_manager service
provides:
  - "GET /api/v1/batches/{name}/results — reads checkpoint.json and returns results array"
  - "POST /api/v1/batches/{name}/cancel — cooperative threading.Event cancellation"
  - "POST /api/v1/batches/{name}/retry-image/{filename} — single-image retry from _errors/"
  - "/batches-static/ StaticFiles mount serving data/batches/ as HTTP"
  - "cancel_event integrated into run_ocr_task and process_batch"
  - "Vite proxy ws:true on /api + /batches-static proxy entry"
affects: [03-02, 03-03, processing-step, results-step]

# Tech tracking
tech-stack:
  added: [threading.Event (stdlib), fastapi.staticfiles.StaticFiles]
  patterns:
    - "Cooperative cancellation via threading.Event (not asyncio.Event — thread-safe for to_thread workers)"
    - "cancel_event cleared at start of every run_ocr_task to prevent stale state"
    - "StaticFiles mount after include_router so API routes take priority"
    - "Vite ws:true on /api proxy to handle WebSocket upgrade on /api/v1/ws/... paths"

key-files:
  created: []
  modified:
    - apps/backend/app/services/ws_manager.py
    - apps/backend/app/services/ocr_engine.py
    - apps/backend/app/api/api_v1/endpoints/batches.py
    - apps/backend/app/main.py
    - apps/frontend/vite.config.ts

key-decisions:
  - "threading.Event (not asyncio.Event) for cancellation — is_set() is thread-safe from ThreadPoolExecutor workers"
  - "cancel_event cleared at start of run_ocr_task (not just on retry) to prevent any stale state"
  - "Per-image cancel granularity: one image may complete after cancel pressed; checkpoint saved before check so partial results are kept"
  - "StaticFiles mount placed after include_router so /api routes always take priority"
  - "Removed /ws Vite proxy entry (matched no real routes); added ws:true to /api entry which covers /api/v1/ws/..."
  - "retry-image endpoint manually strips checkpoint entry for retried file before restart"

patterns-established:
  - "run_ocr_task owns cancel_event lifecycle: clear at start, check at end, clean up in finally"
  - "retry endpoints (both bulk and single) clear stale cancel events before starting"

# Metrics
duration: 8min
completed: 2026-02-21
---

# Phase 03 Plan 01: Backend Prerequisites for Processing & Results

**cooperative threading.Event cancellation, GET/POST results/cancel/retry-image endpoints, and StaticFiles mount for batch image thumbnails**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-02-21T11:02:07Z
- **Completed:** 2026-02-21T11:10:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Cooperative cancellation with `threading.Event` wired through `ws_manager`, `ocr_engine`, and `run_ocr_task`
- Three new API endpoints enabling frontend Processing and Results steps to function
- StaticFiles mount at `/batches-static/` so the frontend can display image thumbnails
- Vite proxy corrected to pass WebSocket upgrade on `/api/v1/ws/...` paths

## Task Commits

Each task was committed atomically:

1. **Task 1: Add cooperative cancellation to ws_manager and ocr_engine** - `d468262` (feat)
2. **Task 2: Add results, cancel, retry-image endpoints and StaticFiles mount** - `92c1c31` (feat)

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified

- `apps/backend/app/services/ws_manager.py` - Added `cancel_events` dict, `get_or_create_cancel_event`, `cancel_batch`, `clear_cancel_event` methods
- `apps/backend/app/services/ocr_engine.py` - Added `import threading`, `cancel_event` param to `process_batch`, cancel check after each image in `_run_batch`
- `apps/backend/app/api/api_v1/endpoints/batches.py` - Updated `run_ocr_task` with cancel_event lifecycle; added `get_batch_results`, `cancel_batch`, `retry_image` endpoints; updated `retry_batch` to clear stale cancel event
- `apps/backend/app/main.py` - Added `StaticFiles` mount at `/batches-static/` after `include_router`
- `apps/frontend/vite.config.ts` - Added `ws: true` to `/api` proxy; added `/batches-static` proxy; removed unused `/ws` entry

## Decisions Made

- **threading.Event over asyncio.Event:** `asyncio.Event` is not safe to call from `asyncio.to_thread` worker threads. `threading.Event.is_set()` is explicitly thread-safe.
- **cancel_event always cleared at task start:** Rather than only clearing on retry paths, `run_ocr_task` always clears the event at the top. This guarantees a fresh state regardless of which endpoint invoked the task.
- **Per-image granularity:** The cancel check runs after checkpoint save, meaning partial results are always persisted. One image may complete after cancel is pressed — this is by design.
- **StaticFiles after include_router:** FastAPI matches routes in registration order, so placing StaticFiles after the router ensures API routes always win.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All backend prerequisites are in place for Phase 03 Plans 02 and 03 (frontend Processing and Results steps)
- The frontend can now: poll results, cancel a running batch, retry individual failed images, and display thumbnails from `/batches-static/{batch_name}/{filename}`
- WebSocket connections on `/api/v1/ws/task/{batch_id}` will now correctly upgrade through the Vite dev proxy

## Self-Check: PASSED

All key files found. Both task commits verified in git history.

---
*Phase: 03-processing-results-react*
*Completed: 2026-02-21*
