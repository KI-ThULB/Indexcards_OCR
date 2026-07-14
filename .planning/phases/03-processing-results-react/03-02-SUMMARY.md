---
phase: 03-processing-results-react
plan: 02
subsystem: ui
tags: [react, zustand, websocket, tailwind, tanstack-query, sonner]

# Dependency graph
requires:
  - phase: 03-processing-results-react
    plan: 01
    provides: "GET results, POST cancel/retry-image endpoints; cancel_event threading; Vite ws:true proxy"
provides:
  - "ProcessingStep component with real-time WebSocket progress bar, live feed, cancel, catastrophic failure detection, and auto-navigate to results"
  - "useProcessingWebSocket hook — native WebSocket, reconnect on close, stable onMessage ref pattern"
  - "ProgressBar — animated fill, X/Y count, ETA, current filename"
  - "LiveFeed — scrolling log with success/failure card styling, auto-scroll to bottom sentinel"
  - "Zustand processingState and results slices with partialize to exclude from localStorage"
  - "batchesApi: cancelBatch, fetchResults, retryImage, retryBatch + TanStack Query hooks"
affects: [03-03, results-step]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Native WebSocket (not react-use-websocket) to avoid React 19 flushSync incompatibility"
    - "onMessageRef stable ref pattern — callback updates ref each render so WS handler always sees current dispatcher without triggering re-connect"
    - "Zustand partialize — exclude processingState/results from localStorage to prevent cell-edit performance regression"
    - "Catastrophic failure: 3 consecutive false results → close WS + best-effort cancel + show error screen"
    - "Auto-navigate: setTimeout(2000) after status=completed|cancelled; cleared on unmount"

key-files:
  created:
    - apps/frontend/src/features/processing/useProcessingWebSocket.ts
    - apps/frontend/src/features/processing/ProcessingStep.tsx
    - apps/frontend/src/features/processing/ProgressBar.tsx
    - apps/frontend/src/features/processing/LiveFeed.tsx
  modified:
    - apps/frontend/src/store/wizardStore.ts
    - apps/frontend/src/api/batchesApi.ts
    - apps/frontend/src/App.tsx

key-decisions:
  - "Native WebSocket API instead of react-use-websocket — avoids React 19 flushSync incompatibility documented in research"
  - "onMessage callback passed to hook, not returned as state — WebSocket hook dispatches directly to Zustand without causing hook re-renders on every message"
  - "partialize in Zustand persist — processingState and results excluded from localStorage; only step/files/fields/sessionId/batchId persisted"
  - "Catastrophic failure closes WS and fires best-effort cancelBatch — errors suppressed since WS may already be down"
  - "LiveFeed appends new items at bottom with auto-scroll (log-style) rather than reverse order"

patterns-established:
  - "initializedRef guard in useEffect — prevents double-reset on React Strict Mode double-invoke"
  - "navigateToResultsRef guards setTimeout — prevents duplicate navigation timers if multiple completed messages arrive"

# Metrics
duration: 2min
completed: 2026-02-21
---

# Phase 03 Plan 02: Processing Step (React) Summary

**Real-time OCR processing UI with native WebSocket, animated progress bar, scrolling live feed, 3-strike catastrophic failure detection, and auto-navigate to results via Zustand store**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-21T11:07:18Z
- **Completed:** 2026-02-21T11:09:32Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- ProcessingStep wired to live WebSocket at `/api/v1/ws/task/{batchId}` with stable reconnect
- ProgressBar displays percentage fill, X/Y count, ETA, and current filename — all from BatchProgress
- LiveFeed auto-scrolls and renders success cards (key/value grid) and failure cards (error message) in parchment aesthetic
- Cancel button fires POST `/cancel` and shows "Cancelling..." toast; WebSocket's `cancelled` status triggers navigation
- 3 consecutive failures triggers a full-screen error card with troubleshooting hints (API key, internet, logs)
- Zustand persist `partialize` prevents localStorage serialization of heavy live feed and results arrays

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend Zustand store and add API functions** - `b208f9d` (feat)
2. **Task 2: Create WebSocket hook, ProcessingStep, ProgressBar, and LiveFeed** - `1da2759` (feat)

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified

- `apps/frontend/src/features/processing/useProcessingWebSocket.ts` - Native WebSocket hook with reconnect-once-on-close and stable onMessageRef pattern
- `apps/frontend/src/features/processing/ProcessingStep.tsx` - Main orchestrator: WebSocket connection, cancel, catastrophic failure, auto-navigate
- `apps/frontend/src/features/processing/ProgressBar.tsx` - Animated progress bar with percentage, X/Y count, ETA, current filename
- `apps/frontend/src/features/processing/LiveFeed.tsx` - Scrollable log of ExtractionResults with success/failure card styling and bottom-sentinel auto-scroll
- `apps/frontend/src/store/wizardStore.ts` - Added ExtractionResult, BatchProgress, ResultRow, ProcessingState interfaces; processingState and results slices; all actions; partialize
- `apps/frontend/src/api/batchesApi.ts` - Added cancelBatch, fetchResults, retryImage, retryBatch functions; useCancelBatchMutation, useRetryImageMutation, useRetryBatchMutation, useResultsQuery hooks
- `apps/frontend/src/App.tsx` - Replaced processing placeholder div with `<ProcessingStep />`

## Decisions Made

- **Native WebSocket over react-use-websocket:** Research (Pitfall 1) documented a React 19 `flushSync` incompatibility in react-use-websocket. Native WebSocket API used throughout — no new dependencies added.
- **Callback-based onMessage, not hook state:** The hook accepts an `onMessage` callback and dispatches directly to Zustand. This avoids the WS hook holding its own state that would cause re-renders on every message, keeping the hook lightweight.
- **partialize excludes processingState and results:** Without this, every cell edit in the Results step would serialize the entire results array to localStorage (potentially thousands of key/value pairs). Partialize limits persisted state to only what's needed across page reloads.
- **initializedRef guards the mount effect:** React Strict Mode double-invokes effects in development. Without the ref guard, `resetProcessing` would fire twice, clearing progress that arrived between the two invocations.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Processing step is fully functional end-to-end
- The Results step (Plan 03) can import `useResultsQuery`, `useRetryImageMutation`, `useRetryBatchMutation`, and `ResultRow` from the existing API and store
- `results` array in Zustand store is populated by the Results step after calling `fetchResults` and transforming to `ResultRow[]` via `setResults`
- WebSocket auto-navigates to `results` step — Plan 03 only needs to render the results already in store or fetched fresh on mount

## Self-Check: PASSED

All 8 key files found. Both task commits (b208f9d, 1da2759) verified in git history.
