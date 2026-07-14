# Phase 3: Processing & Results (React) - Research

**Researched:** 2026-02-21
**Domain:** React WebSocket real-time progress, sortable/editable table, lightbox, CSV/JSON export
**Confidence:** HIGH (codebase-verified) / MEDIUM (library APIs)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Progress Experience
- Rich per-image updates: progress bar + current image name + X/Y count + estimated time remaining
- Live feed of extracted data streams in below the progress bar as each image completes
- Cancel button available during processing — partial results are kept and shown in results
- Auto-navigate to Results step after completion (short "Complete!" delay ~2s)
- Early stop on catastrophic failure: after 3 consecutive failures, stop processing and show error screen with troubleshooting hints (e.g. "API connection failed — check your OPENROUTER_API_KEY")

#### Results Presentation
- Data table layout (spreadsheet-like): one row per image, columns for each extracted field
- Summary banner at top: total processed, success count, error count, total duration, batch name
- Inline editing: click a cell to correct OCR mistakes before exporting
- Thumbnail column with lightbox: small thumbnail per row, click to open full-size image overlay for verifying OCR accuracy
- Table should be sortable by columns

#### Error Handling UX
- Failed images appear inline in the same results table with a red status indicator and error message
- Both per-image "Retry" button on each failed row AND a "Retry All Failed" button at the top
- Retry re-runs OCR on just the failed image(s) and updates the table in-place
- During live feed: Claude's discretion on how failures appear (red inline entry vs toast)

#### CSV/Export Behavior
- "Download CSV" and "Download JSON" buttons in the results summary banner — manual trigger, not auto-download
- CSV includes ALL images with a "Status" column (success/failed) — preserves the full picture
- If user edited data inline, CSV/JSON contains BOTH original OCR value and edited value for changed cells (audit trail)
- CSV format: UTF-8 with BOM for Excel compatibility (per existing requirement)

### Claude's Discretion
- Live feed error display approach (red inline entry vs toast notification)
- Exact progress bar styling within the museum/parchment aesthetic
- Lightbox implementation choice
- Table component library (or hand-rolled)
- Transition animation between Processing and Results steps
- "Complete!" delay duration before auto-navigate

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

---

## Summary

This phase wires the Processing and Results wizard steps. The backend already has all the required infrastructure: a WebSocket endpoint at `/api/v1/ws/task/{batch_id}` that broadcasts `BatchProgress` messages, a `/api/v1/batches/{batch_name}/start` endpoint (called from ConfigureStep), and a `/api/v1/batches/{batch_name}/retry` endpoint. The frontend currently shows placeholder divs for both steps. The work is entirely on the frontend side, plus two backend additions: a results-read endpoint (currently missing) and image serving.

The three non-trivial technical choices are: (1) WebSocket client library — `react-use-websocket` has a known React 19 compatibility issue (`flushSync` usage); a thin custom hook using native `WebSocket` is safer for this React 19 project. (2) Table library — `@tanstack/react-table` v8 is the standard headless choice and is React 19 compatible; it requires approximately 80 lines of setup but gives full control for the parchment aesthetic. (3) Cancel — the backend uses `BackgroundTasks` which cannot be cancelled after dispatch; the cancel button on the frontend must signal via a dedicated endpoint, and the OCR engine needs a cooperative cancellation flag (`asyncio.Event`).

**Primary recommendation:** Use a hand-written `useProcessingWebSocket` hook (20–30 lines, zero deps), `@tanstack/react-table` v8 for the results table, `yet-another-react-lightbox` for image overlay, and native Blob/anchor for CSV/JSON export. Add two backend endpoints: `GET /batches/{name}/results` and `GET /batches/{name}/cancel`.

---

## Existing Backend Infrastructure (Codebase-Verified)

### What already exists

| Piece | Location | Notes |
|-------|----------|-------|
| WebSocket broadcast | `apps/backend/app/services/ws_manager.py` | `ws_manager.broadcast_progress(batch_id, BatchProgress)` |
| WS endpoint | `apps/backend/app/api/api_v1/endpoints/ws.py` | `ws://host/api/v1/ws/task/{batch_id}` |
| OCR engine | `apps/backend/app/services/ocr_engine.py` | `process_batch()` with `progress_callback`, `ThreadPoolExecutor` |
| Batch start | `POST /api/v1/batches/{name}/start` | Already called from `ConfigureStep` |
| Retry failed | `POST /api/v1/batches/{name}/retry` | Moves `_errors/` files back and re-runs |
| Checkpoint | `checkpoint.json` in each batch dir | Tracks per-file success/fail, used for resume |
| `BatchProgress` schema | `apps/backend/app/models/schemas.py` | `{batch_name, current, total, percentage, eta_seconds, last_result, status}` |
| `ExtractionResult` schema | same | `{filename, batch, success, data, error, duration}` |
| Wizard store | `apps/frontend/src/store/wizardStore.ts` | `batchId`, `step`, `setStep` already present |

### What is MISSING and must be built

| Gap | What to build |
|-----|---------------|
| No results-read endpoint | `GET /api/v1/batches/{name}/results` — reads `checkpoint.json`, returns `List[ExtractionResult]` |
| No cancel endpoint | `POST /api/v1/batches/{name}/cancel` — sets a cancellation flag the OCR loop checks |
| No image serving | Mount `StaticFiles` at `/batches-static/{batch_name}/` pointing to `data/batches/` |
| No per-image retry | Endpoint for `POST /api/v1/batches/{name}/retry-image/{filename}` (moves single file back from `_errors/`) |
| No catastrophic-fail detection | Frontend must count consecutive `last_result.success == false` from WS messages |
| No Zustand processing/results state | `wizardStore.ts` has no `processingState` or `results` slice yet |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@tanstack/react-table` | ^8.21 | Headless sortable/editable table | React 19 compatible, zero opinion on UI, official example for editable data, sorting built-in |
| `yet-another-react-lightbox` | ^3.x | Image thumbnail lightbox | React 19 compatible (16.8+), maintained, CSS import pattern, per-slide `src` |
| Hand-written `useProcessingWebSocket` hook | — | WS connection, reconnect, parse | `react-use-websocket` has React 19 `flushSync` bug (issue #256) — safer to write ~25 lines |
| Native `Blob` + `<a download>` | — | CSV and JSON download | No library needed; UTF-8 BOM = `\uFEFF` prefix |
| `zustand` (already installed, v5) | ^5.0.11 | Processing + results state | Already in the project |
| `lucide-react` (already installed) | ^0.575 | Icons | Already in the project |
| `sonner` (already installed) | ^2.0.7 | Toast for errors/cancel | Already in the project |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `immer` middleware for Zustand | built-in to zustand v5 | Nested state mutation for table rows | When updating a single cell in a large results array |
| CSS `@keyframes` / Tailwind `animate-` | — | Progress bar animation, "Complete!" transition | Use Tailwind's `transition-all`, `duration-700` consistent with existing steps |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-written WS hook | `react-use-websocket` | react-use-websocket has React 19 flushSync incompatibility (issue #256, open); hand-written hook is 25 lines and zero risk |
| `@tanstack/react-table` | Hand-rolled table | TanStack handles sorting state, column visibility, cell meta pattern — saves ~200 lines |
| `yet-another-react-lightbox` | Simple modal with `<img>` | YARL handles keyboard nav, touch, zoom for free; simple modal is viable but takes 50+ lines to match |
| Client-side CSV generation | Backend `/batches/{name}/export` endpoint | Client-side is simpler; no round-trip; audit trail (original + edited) is already in frontend state |

### Installation

```bash
# From apps/frontend/
npm install @tanstack/react-table yet-another-react-lightbox
```

No other packages needed.

---

## Architecture Patterns

### Recommended Project Structure

```
apps/frontend/src/
├── api/
│   └── batchesApi.ts          # Add: fetchResults, cancelBatch, retryImage mutations
├── features/
│   ├── processing/
│   │   ├── ProcessingStep.tsx        # Main step component
│   │   ├── ProgressBar.tsx           # Animated bar + label + ETA
│   │   ├── LiveFeed.tsx              # Scrolling log of completed images
│   │   └── useProcessingWebSocket.ts # Custom WS hook
│   └── results/
│       ├── ResultsStep.tsx           # Main step component
│       ├── SummaryBanner.tsx         # Stats + Download buttons
│       ├── ResultsTable.tsx          # TanStack table, sortable, editable
│       ├── ThumbnailCell.tsx         # Thumbnail + YARL trigger per row
│       └── useResultsExport.ts       # CSV/JSON generation logic
├── store/
│   └── wizardStore.ts         # Extend: processingState + results slices
```

```
apps/backend/app/
├── api/api_v1/endpoints/
│   └── batches.py             # Add: GET results, POST cancel, POST retry-image
├── services/
│   ├── ocr_engine.py          # Add: cancel_event parameter to process_batch
│   └── ws_manager.py          # Add: active_tasks dict for cancellation
├── main.py                    # Add: StaticFiles mount for batch images
```

### Pattern 1: Custom WebSocket Hook

**What:** A hook that connects to the batch WS, parses JSON, reconnects on close, and exposes `lastProgress`.
**When to use:** Every time the frontend needs real-time progress from the backend.

```typescript
// Source: native WebSocket API — no library needed
// apps/frontend/src/features/processing/useProcessingWebSocket.ts
import { useEffect, useRef, useState } from 'react';
import type { BatchProgress } from '../../../packages/shared-types'; // or inline type

export function useProcessingWebSocket(batchId: string | null) {
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!batchId) return;

    const wsUrl = `ws://${location.host}/api/v1/ws/task/${batchId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const data: BatchProgress = JSON.parse(event.data);
        setProgress(data);
      } catch {
        console.error('WS parse error', event.data);
      }
    };

    ws.onclose = () => {
      // Re-attach re-sends last state from ws_manager.batch_states
      // For simple cases, reconnect once after 1s
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [batchId]);

  return progress;
}
```

**Key insight:** The backend's `ws_manager.connect()` already re-sends the last `BatchProgress` on re-attach, so a simple single reconnect is sufficient.

### Pattern 2: TanStack Table with Editable Cells and Sorting

**What:** `useReactTable` configured with `getCoreRowModel`, `getSortedRowModel`, and a `meta.updateData` callback.
**When to use:** ResultsTable component.

```typescript
// Source: https://tanstack.com/table/v8/docs/framework/react/examples/editable-data
// and https://tanstack.com/table/v8/docs/guide/sorting
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table';

// Row type — one row per image
interface ResultRow {
  filename: string;
  status: 'success' | 'failed';
  error?: string;
  data: Record<string, string>;           // OCR values
  editedData: Record<string, string>;     // User-edited values (subset)
  duration: number;
}

const columnHelper = createColumnHelper<ResultRow>();

// Dynamic columns from fields list + fixed columns
const columns = [
  columnHelper.display({ id: 'thumbnail', header: 'Image', /* ThumbnailCell */ }),
  columnHelper.accessor('filename', { header: 'File', enableSorting: true }),
  columnHelper.accessor('status', { header: 'Status', enableSorting: true }),
  // Per-field columns built dynamically from fields array:
  ...fields.map(field =>
    columnHelper.display({
      id: field,
      header: field,
      cell: ({ row }) => <EditableCell row={row} field={field} onUpdate={updateCell} />,
    })
  ),
  columnHelper.display({ id: 'actions', header: '', /* Retry button */ }),
];

const [sorting, setSorting] = useState<SortingState>([]);
const [data, setData] = useState<ResultRow[]>(initialData);

const table = useReactTable({
  data,
  columns,
  state: { sorting },
  onSortingChange: setSorting,
  getCoreRowModel: getCoreRowModel(),
  getSortedRowModel: getSortedRowModel(),
  meta: {
    updateData: (rowIndex: number, field: string, value: string) => {
      setData(old =>
        old.map((row, idx) =>
          idx === rowIndex
            ? { ...row, editedData: { ...row.editedData, [field]: value } }
            : row
        )
      );
    },
  },
});
```

### Pattern 3: Cancellable OCR Task (Backend)

**What:** Replace `BackgroundTasks.add_task` with `asyncio.create_task`, store a cancellation `asyncio.Event` per batch in `ws_manager`, expose `POST /batches/{name}/cancel`.
**When to use:** When the user clicks Cancel during processing.

```python
# apps/backend/app/services/ws_manager.py — add cancel_events
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.batch_states: Dict[str, BatchProgress] = {}
        self.cancel_events: Dict[str, asyncio.Event] = {}  # NEW

    def get_or_create_cancel_event(self, batch_id: str) -> asyncio.Event:
        if batch_id not in self.cancel_events:
            self.cancel_events[batch_id] = asyncio.Event()
        return self.cancel_events[batch_id]

    def cancel_batch(self, batch_id: str):
        event = self.cancel_events.get(batch_id)
        if event:
            event.set()

# apps/backend/app/services/ocr_engine.py — check cancel_event in loop
async def process_batch(self, ..., cancel_event: Optional[asyncio.Event] = None):
    # In the _run_batch function, after each future completes:
    if cancel_event and cancel_event.is_set():
        logger.info(f"Batch {batch_name} cancelled by user")
        break  # Exit the for loop — partial results saved by checkpoint
```

**Note:** `ThreadPoolExecutor.submit()` cannot be cancelled mid-execution. The cancel check between completed futures gives per-image granularity — one image may still complete after cancel is pressed. This is acceptable and matches the "partial results are kept" requirement.

### Pattern 4: CSV Generation with Audit Trail

**What:** Client-side generation using `Blob` with `\uFEFF` BOM prefix.
**When to use:** "Download CSV" button click.

```typescript
// apps/frontend/src/features/results/useResultsExport.ts
export function useResultsExport(results: ResultRow[], fields: string[]) {
  const downloadCSV = () => {
    const headers = ['File', 'Status', 'Error', 'Duration(s)',
      ...fields.flatMap(f => [`${f}_ocr`, `${f}_edited`])
    ];

    const rows = results.map(row => [
      row.filename,
      row.status,
      row.error ?? '',
      row.duration.toFixed(2),
      ...fields.flatMap(f => [
        row.data?.[f] ?? '',
        row.editedData?.[f] ?? '',  // empty if not edited
      ]),
    ]);

    const csv = [headers, ...rows]
      .map(r => r.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\r\n');

    // UTF-8 BOM for Excel compatibility
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${batchName}_results.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadJSON = () => {
    const payload = results.map(row => ({
      filename: row.filename,
      status: row.status,
      error: row.error,
      duration: row.duration,
      fields: Object.fromEntries(
        fields.map(f => [f, {
          ocr: row.data?.[f] ?? '',
          edited: row.editedData?.[f] ?? undefined,  // omit if not edited
        }])
      ),
    }));
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${batchName}_results.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return { downloadCSV, downloadJSON };
}
```

### Pattern 5: Serve Batch Images via FastAPI StaticFiles

**What:** Mount the `data/batches/` directory as static files so the frontend can show thumbnails.
**When to use:** ResultsTable thumbnail column.

```python
# apps/backend/app/main.py
from fastapi.staticfiles import StaticFiles
from app.core.config import settings

app.mount(
    "/batches-static",
    StaticFiles(directory=settings.BATCHES_DIR),
    name="batches-static"
)
# Thumbnail URL pattern: /batches-static/{batch_name}/{filename}
```

Frontend thumbnail URL: `/batches-static/${batchName}/${row.filename}`

### Pattern 6: Zustand Store Extension

**What:** Add `processingState` and `results` slices to `wizardStore.ts`.
**When to use:** Sharing processing progress and results between ProcessingStep and ResultsStep.

```typescript
// Extend wizardStore.ts
interface ProcessingState {
  consecutiveFailures: number;
  liveFeedItems: ExtractionResult[];
  lastProgress: BatchProgress | null;
  isCancelled: boolean;
}

interface ResultRow { /* as above */ }

interface WizardState {
  // existing...
  processingState: ProcessingState;
  results: ResultRow[];
  // actions
  appendLiveFeedItem: (item: ExtractionResult) => void;
  setLastProgress: (p: BatchProgress) => void;
  setResults: (rows: ResultRow[]) => void;
  updateResultCell: (filename: string, field: string, value: string) => void;
  resetProcessing: () => void;
}
```

**Caution on persist middleware:** `results` may contain many large strings. Consider excluding `results` and `processingState.liveFeedItems` from the `persist` middleware using the `partialize` option.

### Anti-Patterns to Avoid

- **Storing `BatchProgress` updates directly in persisted Zustand:** Each WS message triggers a persist write. Use `partialize` to exclude live progress from localStorage.
- **Rendering the full `results` array on every WS update:** Keep `processingState.liveFeedItems` separate from `results`. The live feed is ephemeral; results are built from the final checkpoint.
- **Reading results from WS messages alone:** The WS stream can have gaps (reconnects). Always hydrate the results table from `GET /batches/{name}/results` (checkpoint.json) on step mount.
- **Calling `cancel` via WS message:** Cancel must be a REST `POST` call, not a WS message. The backend WS handler currently only listens and does nothing with client messages.
- **Using `BackgroundTasks` for cancellable work:** `BackgroundTasks` has no cancellation API. Must switch to `asyncio.create_task` + `asyncio.Event`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sortable table headers | Custom sort logic | `getSortedRowModel()` from `@tanstack/react-table` | Multi-column sort, sort direction toggle, stable sort — done in 3 lines |
| Image lightbox/overlay | Custom modal + keyboard nav | `yet-another-react-lightbox` | Keyboard nav, touch swipe, zoom, accessibility — 50+ line custom impl with bugs |
| CSV UTF-8 encoding | TextEncoder + Uint8Array concat | `'\uFEFF' + csvString` as Blob | The BOM character prepended to a string Blob achieves the same result; TextEncoder approach is over-engineering |
| WS reconnect | Exponential backoff timer | Single 1s reconnect is enough | Backend re-sends current state on reconnect; complex backoff is overkill for local/LAN use |

**Key insight:** The hardest part of this phase is state coordination between the WS stream, the ProcessingStep, and the ResultsStep. Lean on the existing checkpoint.json as the source of truth for results — don't try to reconstruct results purely from WS events.

---

## Common Pitfalls

### Pitfall 1: react-use-websocket React 19 Incompatibility
**What goes wrong:** `flushSync` inside the library causes errors or warnings under React 19 (the project uses React 19.2).
**Why it happens:** react-use-websocket uses `flushSync` internally (issue #211, open). The maintainer confirmed React 19 is not yet supported (issue #256).
**How to avoid:** Write a ~25-line custom hook using native `WebSocket`. It covers all required functionality (connect, parse, close on unmount).
**Warning signs:** "flushSync was called inside a lifecycle method" console errors.

### Pitfall 2: Consecutive Failure Count Resets on Reconnect
**What goes wrong:** If the WS disconnects and reconnects, `consecutiveFailures` counter resets, missing the threshold for early stop.
**Why it happens:** Counter lives in component state, not Zustand.
**How to avoid:** Store `consecutiveFailures` in Zustand (persisted across reconnects within the same session).

### Pitfall 3: Image URL 404 Before StaticFiles Is Mounted
**What goes wrong:** Thumbnails in the results table return 404 because the backend has no image-serving route yet.
**Why it happens:** `data/batches/{name}/{filename}` is not exposed via HTTP — only accessible on disk.
**How to avoid:** Add the `StaticFiles` mount to `main.py` BEFORE wiring the thumbnail column. Test with `curl http://localhost:8000/batches-static/{batch_name}/{filename}` before building the cell.

### Pitfall 4: Results Table Renders Before Results Endpoint Exists
**What goes wrong:** `ResultsStep` mounts but the `GET /batches/{name}/results` endpoint returns 404 or doesn't exist.
**Why it happens:** The endpoint is not yet implemented in `batches.py`.
**How to avoid:** Implement the results endpoint first (reads `checkpoint.json`, returns `List[ExtractionResult]`). This is a prerequisite for the results table.

### Pitfall 5: Tailwind JIT Misses Dynamic Column Class Names
**What goes wrong:** Dynamic class names like `border-red-500` built from a variable string are purged.
**Why it happens:** Tailwind 3.4 JIT scans source files for complete class strings; dynamic concatenation breaks scanning.
**How to avoid:** Use a lookup map: `const statusClass = { success: 'border-green-600', failed: 'border-red-500' }[row.status]`. Never construct Tailwind classes from string concatenation.

### Pitfall 6: Persist Middleware Serializing Large Results Array
**What goes wrong:** Zustand's `persist` middleware serializes the full `results` array (potentially 500+ rows) to localStorage on every cell edit.
**Why it happens:** Default `persist` persists everything.
**How to avoid:** Use `partialize` to exclude `results` and `processingState.liveFeedItems`:
```typescript
persist(
  (set, get) => ({ ... }),
  {
    name: 'wizard-storage',
    partialize: (state) => ({
      step: state.step,
      files: state.files,
      fields: state.fields,
      sessionId: state.sessionId,
      batchId: state.batchId,
    }),
  }
)
```

### Pitfall 7: Cancel Endpoint Doesn't Stop the ThreadPoolExecutor
**What goes wrong:** User clicks Cancel, endpoint is called, but processing continues for several more images.
**Why it happens:** `ThreadPoolExecutor` tasks cannot be pre-empted. `cancel_event.set()` is only checked between futures completing.
**How to avoid:** This is expected behavior — document it in the UX. "Cancel was requested — finishing the current image." The live feed shows this clearly.

---

## Code Examples

### WebSocket Message Shape (Verified from schemas.py)

```typescript
// What arrives on ws.onmessage
interface BatchProgress {
  batch_name: string;
  current: number;      // images processed so far
  total: number;        // total images in batch
  percentage: number;   // 0-100
  eta_seconds: number | null;
  last_result: ExtractionResult | null;
  status: 'running' | 'completed' | 'failed' | 'retrying';
}

interface ExtractionResult {
  filename: string;
  batch: string;
  success: boolean;
  data: Record<string, string> | null;  // null on failure
  error: string | null;
  duration: number;
}
```

### Progress Bar Component Pattern

```tsx
// Tailwind 3.4, parchment aesthetic consistent with existing steps
<div className="space-y-2">
  <div className="flex justify-between text-xs uppercase tracking-widest text-archive-ink/40 font-semibold">
    <span>{progress.current} / {progress.total} items</span>
    {progress.eta_seconds && (
      <span>~{Math.ceil(progress.eta_seconds)}s remaining</span>
    )}
  </div>
  <div className="h-2 bg-parchment-dark rounded overflow-hidden">
    <div
      className="h-full bg-archive-sepia transition-all duration-500 ease-out"
      style={{ width: `${progress.percentage}%` }}
    />
  </div>
  <p className="text-sm font-mono text-archive-ink/60 truncate">
    Processing: {progress.last_result?.filename}
  </p>
</div>
```

### TanStack Table Sort Header (Verified pattern from official docs)

```tsx
{table.getHeaderGroups().map(headerGroup => (
  <tr key={headerGroup.id}>
    {headerGroup.headers.map(header => (
      <th
        key={header.id}
        onClick={header.column.getToggleSortingHandler()}
        className={`cursor-pointer select-none px-4 py-2 text-left text-xs uppercase tracking-widest ${
          header.column.getCanSort() ? 'hover:text-archive-sepia' : ''
        }`}
      >
        {flexRender(header.column.columnDef.header, header.getContext())}
        {{ asc: ' ↑', desc: ' ↓' }[header.column.getIsSorted() as string] ?? ''}
      </th>
    ))}
  </tr>
))}
```

### YARL Lightbox Usage (Verified from official docs)

```tsx
import Lightbox from 'yet-another-react-lightbox';
import 'yet-another-react-lightbox/styles.css';

// In ThumbnailCell:
const [open, setOpen] = useState(false);
const imageUrl = `/batches-static/${batchName}/${filename}`;

return (
  <>
    <img
      src={imageUrl}
      alt={filename}
      className="w-16 h-12 object-cover rounded cursor-pointer border border-parchment-dark hover:opacity-80 transition-opacity"
      onClick={() => setOpen(true)}
    />
    <Lightbox
      open={open}
      close={() => setOpen(false)}
      slides={[{ src: imageUrl }]}
    />
  </>
);
```

### Results Endpoint (Backend — to be built)

```python
# apps/backend/app/api/api_v1/endpoints/batches.py
@router.get("/{batch_name}/results")
async def get_batch_results(batch_name: str):
    """Returns all results from checkpoint.json."""
    batch_path = batch_manager.get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail="Batch not found")
    checkpoint_path = batch_path / "checkpoint.json"
    if not checkpoint_path.exists():
        return []  # Not yet started or no results
    with open(checkpoint_path, "r") as f:
        return json.load(f)

@router.post("/{batch_name}/cancel")
async def cancel_batch(batch_name: str):
    """Signals the running OCR task to stop after the current image."""
    ws_manager.cancel_batch(batch_name)  # sets asyncio.Event
    return {"message": "Cancel requested", "batch_name": batch_name}

@router.post("/{batch_name}/retry-image/{filename}")
async def retry_single_image(batch_name: str, filename: str, background_tasks: BackgroundTasks):
    """Moves a single file from _errors back to batch dir and retries it."""
    batch_path = batch_manager.get_batch_path(batch_name)
    error_file = batch_path / "_errors" / filename
    if not error_file.exists():
        raise HTTPException(status_code=404, detail="Error file not found")
    import shutil
    shutil.move(str(error_file), str(batch_path / filename))
    # Remove from checkpoint so it gets re-processed
    checkpoint_path = batch_path / "checkpoint.json"
    if checkpoint_path.exists():
        with open(checkpoint_path, "r") as f:
            data = json.load(f)
        data = [r for r in data if r["filename"] != filename]
        with open(checkpoint_path, "w") as f:
            json.dump(data, f, indent=2)
    background_tasks.add_task(run_ocr_task, batch_name)
    return {"message": f"Retry started for {filename}"}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `react-table` (v7, useSortBy plugin) | `@tanstack/react-table` v8 (`getSortedRowModel`) | 2022 | Full rewrite — hooks-first, TypeScript-first, no plugin system |
| `react-image-lightbox` | `yet-another-react-lightbox` | 2022–2023 | YARL is actively maintained; react-image-lightbox is unmaintained |
| `FlushSync`-based WS libraries | Custom hook / native WebSocket | React 19 (2024) | Libraries using flushSync break under React 19 Strict Mode |
| `BackgroundTasks` for long jobs | `asyncio.create_task` + cancel events | FastAPI best practice | BackgroundTasks has no cancellation; create_task gives handle for explicit cancel |

**Deprecated/outdated:**
- `react-table` (without @tanstack scope): v7, unmaintained, do not use
- `react-image-lightbox`: no longer maintained, last release 2021
- `react-use-websocket` with React 19: open incompatibility (flushSync), avoid until resolved

---

## Open Questions

1. **Per-image retry while another retry is already running**
   - What we know: The retry endpoint starts a full `run_ocr_task` in `BackgroundTasks`, which processes all non-completed files.
   - What's unclear: If user clicks "Retry" on image A, then immediately "Retry" on image B, two background tasks run. The OCR engine's `ThreadPoolExecutor` will process all pending files, which may include both — this is probably fine because of checkpoint deduplication, but it's untested.
   - Recommendation: For the initial implementation, disable retry buttons while any processing is running. Track a `isProcessing` boolean in Zustand.

2. **OCR engine cancel event threading issue**
   - What we know: `_run_batch` runs in `asyncio.to_thread`. The cancel event check happens in the thread. `asyncio.Event.is_set()` is thread-safe (it's just reading a flag).
   - What's unclear: Whether the main event loop's `asyncio.Event` is safely readable from a thread pool thread.
   - Recommendation: Use `threading.Event` instead of `asyncio.Event` for the cancel flag — it's designed for cross-thread signaling. Store it in `ws_manager.cancel_events` as a `threading.Event`.

3. **Image file format for thumbnails**
   - What we know: The batch directory contains `.jpg`, `.jpeg`, and (based on test data) `.png` files. `StaticFiles` serves them all.
   - What's unclear: Whether uploaded PNGs were converted to JPEG during upload (they weren't — `upload.py` does a raw `shutil.copyfileobj`).
   - Recommendation: Use the raw filename from `ExtractionResult.filename`; do not assume extension. The `<img>` tag handles all formats.

---

## Sources

### Primary (HIGH confidence)
- Codebase: `apps/backend/app/services/ws_manager.py` — verified WS API shape
- Codebase: `apps/backend/app/models/schemas.py` — verified `BatchProgress`, `ExtractionResult` schemas
- Codebase: `apps/backend/app/api/api_v1/endpoints/batches.py` — verified start/retry endpoints
- Codebase: `apps/backend/app/services/ocr_engine.py` — verified `process_batch` signature and ThreadPoolExecutor pattern
- Codebase: `apps/frontend/src/store/wizardStore.ts` — verified existing Zustand state shape
- Codebase: `apps/frontend/package.json` — verified React 19.2.0, Zustand 5.0.11, TanStack Query 5.90.21 installed
- Codebase: `apps/frontend/tailwind.config.js` — verified color tokens (`archive-sepia`, `parchment`, `archive-ink`)
- [yet-another-react-lightbox documentation](https://yet-another-react-lightbox.com/documentation) — verified install command, `open/close/slides` props

### Secondary (MEDIUM confidence)
- [TanStack Table v8 Sorting Guide](https://tanstack.com/table/v8/docs/guide/sorting) — `getSortedRowModel`, `SortingState`, `onSortingChange` pattern
- [TanStack Table v8 Editable Data Example](https://tanstack.com/table/v8/docs/framework/react/examples/editable-data) — `meta.updateData` pattern
- [FastAPI Static Files docs](https://fastapi.tiangolo.com/tutorial/static-files/) — `StaticFiles` mount pattern
- [react-use-websocket GitHub issue #256](https://github.com/robtaussig/react-use-websocket/issues/256) — confirmed React 19 incompatibility

### Tertiary (LOW confidence, flag for validation)
- WebSearch: FastAPI `asyncio.create_task` vs `BackgroundTasks` for cancellation — multiple sources agree, but no single authoritative reference verified
- WebSearch: `threading.Event` thread-safety in asyncio.to_thread context — logically correct, needs smoke test

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified against official docs and npm, codebase confirms React 19 and existing deps
- Architecture: HIGH — codebase-grounded; all backend pieces verified by reading source
- Pitfalls: MEDIUM — flushSync/React 19 issue verified; threading.Event question needs smoke test

**Research date:** 2026-02-21
**Valid until:** 2026-03-21 (library APIs stable; React 19 ecosystem still settling)
