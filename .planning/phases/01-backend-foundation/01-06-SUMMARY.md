---
phase: 01-backend-foundation
plan: 06
subsystem: batch-history
tags: [batch-management, history, dashboard, frontend, backend]
dependency_graph:
  requires:
    - 03-03 (ResultsStep — loadBatchForReview navigates to results view)
    - apps/backend/app/services/batch_manager.py (existing _record_history mechanism)
  provides:
    - GET /api/v1/batches/history
    - DELETE /api/v1/batches/{name}
    - BatchHistoryDashboard React component with full CRUD actions
  affects:
    - apps/frontend/src/App.tsx (view-level routing)
    - apps/frontend/src/store/wizardStore.ts (view state)
    - apps/frontend/src/components/Sidebar.tsx (navigation)
    - apps/frontend/src/components/Header.tsx (navigation)
tech_stack:
  added: []
  patterns:
    - AppView type in Zustand store for wizard/history routing
    - useBatchHistoryQuery / useDeleteBatchMutation via TanStack Query
    - Route ordering: /history placed before /{batch_name} to avoid FastAPI param collision
key_files:
  created:
    - apps/frontend/src/features/history/BatchHistoryDashboard.tsx
    - apps/frontend/src/features/history/BatchHistoryCard.tsx
  modified:
    - apps/backend/app/api/api_v1/endpoints/batches.py
    - apps/backend/app/models/schemas.py
    - apps/backend/app/services/batch_manager.py
    - apps/frontend/src/api/batchesApi.ts
    - apps/frontend/src/store/wizardStore.ts
    - apps/frontend/src/App.tsx
    - apps/frontend/src/components/Sidebar.tsx
    - apps/frontend/src/components/Header.tsx
decisions:
  - Route ordering: GET /history placed before /{batch_name} routes in FastAPI router to prevent 'history' being parsed as a batch name parameter
  - loadBatchForReview sets batchId + step:'results' + view:'wizard' atomically — ResultsStep uses existing useResultsQuery(batchId) to hydrate from backend
  - view state added to Zustand persist partialize so selected view survives page refresh
  - delete_batch returns False for non-existent batch whether missing from disk or history file; 404 is only raised when neither location has the batch
metrics:
  duration: ~5min
  completed: "2026-02-22"
  tasks: 2
  files: 9
---

# Phase 01 Plan 06: Batch History Dashboard Summary

Batch history backend endpoints + a full React dashboard with per-batch Review, Retry, and Delete actions, wired into app navigation via sidebar and header.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Add batch history and delete endpoints to backend | 3aff2a9 |
| 2 | Build BatchHistoryDashboard and wire into app navigation | 1e8a87d |

## What Was Built

### Backend (Task 1)

**`schemas.py`** — Added `BatchHistoryItem` Pydantic model with `batch_name`, `custom_name`, `created_at`, `status`, `files_count`, `fields`, `has_errors`, `error_count` fields.

**`batch_manager.py`** — Added two methods:
- `get_history()`: reads batches.json, enriches each entry with live file count (from disk if dir exists, else stored value) and `has_errors`/`error_count` from `_errors/` directory.
- `delete_batch()`: removes batch directory with `shutil.rmtree` and strips the entry from batches.json; returns `True/False` based on whether anything was found.

**`batches.py`** — Added two routes:
- `GET /history` — returns `List[BatchHistoryItem]` from `batch_manager.get_history()`, placed before `/{batch_name}` routes to prevent FastAPI treating "history" as a path parameter.
- `DELETE /{batch_name}` — returns 204 on success, 404 if batch not found.

### Frontend (Task 2)

**`batchesApi.ts`** — Added `BatchHistoryItem` interface, `useBatchHistoryQuery()` (queryKey: `['batch-history']`), and `useDeleteBatchMutation()` (invalidates `['batch-history']` on success, shows toast).

**`wizardStore.ts`** — Added `AppView = 'wizard' | 'history'` type, `view` state (default `'wizard'`), `setView()` action, and `loadBatchForReview(batchName)` helper that sets `batchId`, `step:'results'`, `view:'wizard'`. Added `view` to persist partialize.

**`BatchHistoryCard.tsx`** — Parchment-themed card showing: batch name (font-serif), colored status pill, date/file count/field count row, error count in red (if has_errors), action buttons (Review Results, Retry, Delete with sonner confirmation toast).

**`BatchHistoryDashboard.tsx`** — Main dashboard with loading/empty/error states, batches sorted newest-first, responsive grid (`grid-cols-1 md:grid-cols-2 xl:grid-cols-3`), New Batch button.

**`App.tsx`** — Reads `view` from wizardStore; renders `<BatchHistoryDashboard />` when `view === 'history'`, else existing wizard step switch.

**`Sidebar.tsx`** — Added Batch Archive link (Archive icon, active when `view === 'history'`) and conditional New Batch link (Plus icon, shown only in history view). Both use `setView()` and `resetWizard()`.

**`Header.tsx`** — In wizard view: shows both "Batch Archive" (BookOpen) and "Start Fresh" (RotateCcw) buttons. In history view: shows "New Batch" (Plus) button.

## Deviations from Plan

None — plan executed exactly as written.

## Verification

- `GET /api/v1/batches/history` returns 200 with full batch metadata array (verified with curl against live server)
- `DELETE /api/v1/batches/nonexistent` returns 404 (verified)
- `npx tsc --noEmit` passes with zero errors
- All artifact files exist and meet line count requirements (Dashboard: 83 lines, Card: 131 lines)
- All key links verified: Dashboard uses `useBatchHistoryQuery`, Card uses `useDeleteBatchMutation`, App.tsx has `view === 'history'` routing

## Self-Check: PASSED

All 9 artifact files exist on disk. Both task commits (3aff2a9, 1e8a87d) present in git log.
