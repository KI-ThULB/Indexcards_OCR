# Phase 1: Backend Foundation (FastAPI Integration) - Research

**Researched:** 2025-05-22
**Domain:** FastAPI, WebSockets, OCR Engine Refactoring
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Naming Convention:** Batches are named using a `[Custom Name]_[Human Readable Timestamp]_[Unique ID]` format.
- **File Management:** 
  - Uploaded images are stored in a temporary area.
  - Upon starting processing, they are moved to a permanent batch-specific directory.
- **Cleanup Policy:** Manual cleanup only; the system will not auto-delete data to avoid accidental loss.
- **State:** Batches are "appendable" during the upload phase but become "locked/frozen" once processing starts.
- **Access:** No requirement to serve original images back via the API for now.
- **Validation:** At least one field must be active to start a task. The UI should include a verification step to confirm field names and intent.
- **Persistence:** Field configurations (the "schema") must be storable as reusable templates for future batches.
- **Prompting:** No "predefined" global fields; every batch starts from a blank slate or a selected template.
- **API Flow:** The frontend sends the field list; the backend generates the appropriate VLM prompt internally.
- **Communication:** **WebSockets** will be used for real-time updates.
- **Metrics:** Updates must include: completion percentage, "File X of Y" counter, and estimated time remaining.
- **Data Streaming:** Individual card results (extracted JSON) should be pushed via the WebSocket as they are completed.
- **Resilience:** The backend must support "re-attaching" to an ongoing task.
- **Individual Errors:** If a card fails, log and skip to next. Failed images moved to `_errors/` subfolder.
- **Interruption Recovery:** Support resuming interrupted batches using checkpointing logic.
- **Retry Mechanism:** API endpoint to retry only failed cards.

### Claude's Discretion
- Project structure details.
- Internal service architecture for the OCR Engine.
- WebSocket message protocol specifics.

### Deferred Ideas (OUT OF SCOPE)
- *N/A (All discussed items prioritized for Phase 1 or current scope)*
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FR1 | Image Upload (Drag & Drop) | FastAPI `UploadFile` with `shutil` for efficient disk spooling. |
| FR2 | Metadata Field Configuration | Local JSON persistence for templates; dynamic prompt generation logic. |
| FR3 | OCR Processing & Progress Tracking | Refactored `OcrEngine` with `ThreadPoolExecutor` and WebSocket progress streaming. |
| FR5 | Local Storage / Persistence | Strategy for batch-specific `checkpoint.json` and `_errors/` folders. |
| NFR4 | Modular Architecture | Service-oriented structure separating API, Engine, and File Management. |
</phase_requirements>

## Summary

This research establishes the foundation for a robust, multi-user (though local-first) FastAPI backend that wraps the existing VLM-based OCR logic. The primary challenge is transforming the procedural `indexcard_ocr.py` script into a reactive service that can communicate progress in real-time.

**Primary recommendation:** Use a service-oriented architecture where a `BatchManager` handles the file lifecycle (temp-to-perm), an `OcrEngine` handles the heavy lifting via threads, and a `WebSocketManager` bridges the gap to the frontend.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | ^0.100.0 | Web Framework | High performance, async-first, excellent documentation. |
| Uvicorn | ^0.22.0 | ASGI Server | Standard for running FastAPI apps. |
| WebSockets | ^11.0 | Real-time comms | Required for progress streaming and "re-attaching" to tasks. |
| Pydantic | ^2.0 | Data Validation | Native to FastAPI; handles schema validation and serialization. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|--------------|
| aiofiles | ^23.1.0 | Async File I/O | Use for reading/writing small metadata files without blocking the loop. |
| python-multipart | ^0.0.6 | Form/File uploads | Required for FastAPI's `File` and `UploadFile` support. |
| shutil | (Stdlib) | File operations | Best for "moving" entire directories (temp-to-perm). |

**Installation:**
```bash
pip install fastapi uvicorn websockets pydantic aiofiles python-multipart
```

## Architecture Patterns

### Recommended Project Structure
```
backend/
├── app/
│   ├── api/
│   │   ├── endpoints/    # Upload, Batch, Fields, WebSocket routes
│   │   └── api.py        # Main router assembly
│   ├── core/
│   │   ├── config.py     # Settings (OpenRouter Key, Paths)
│   │   └── events.py     # App startup/shutdown hooks
│   ├── models/
│   │   └── schemas.py    # Pydantic models for API requests/responses
│   ├── services/
│   │   ├── ocr_engine.py # The refactored OcrEngine class
│   │   ├── batch_manager.py # Handles temp-to-perm and file locking
│   │   └── ws_manager.py # WebSocket connection management
│   └── main.py           # App entry point
├── data/
│   ├── temp/             # Transient uploads
│   ├── batches/          # Permanent batch storage (output_batches)
│   └── templates.json    # Reusable field configurations
└── requirements.txt
```

### Pattern 1: Refactored OcrEngine (Thread-Safe)
The `OcrEngine` should remain synchronous/threaded to utilize `ThreadPoolExecutor` (which is efficient for I/O bound API calls), but it should be wrapped such that it doesn't block the FastAPI event loop.

**Example:**
```python
# app/services/ocr_engine.py
import asyncio
from concurrent.futures import ThreadPoolExecutor

class OcrEngine:
    def __init__(self, max_workers=5):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
    async def process_batch(self, batch_id, images, config, on_progress_coro):
        loop = asyncio.get_event_loop()
        # Offload the heavy batch processing to the executor
        await loop.run_in_executor(
            self.executor, 
            self._run_sync_process, 
            batch_id, images, config, on_progress_coro
        )

    def _run_sync_process(self, batch_id, images, config, on_progress_coro):
        # Traditional synchronous loop with thread-safe async calls
        for img in images:
            # ... process card ...
            # Push update back to the event loop
            asyncio.run_coroutine_threadsafe(
                on_progress_coro(update_data), 
                asyncio.get_event_loop()
            )
```

### Pattern 2: WebSocket "Re-attach" logic
To support "re-attaching" to an ongoing task, the `ws_manager` should track task progress in an in-memory dictionary. When a client connects to `/ws/task/{batch_id}`, it immediately receives the current state before entering the stream.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File Upload Buffer | Manual byte-chunking | `fastapi.UploadFile` | Automatically spools to disk; handles memory safely. |
| JSON Validation | Manual `isinstance` checks | Pydantic Models | Type safety, clear error messages, and automatic OpenAPI docs. |
| Connection Tracking | Manual socket lists | `WebSocketManager` class | Centralizes broadcast/disconnect logic; prevents memory leaks. |

## Common Pitfalls

### Pitfall 1: Event Loop Blocking
**What goes wrong:** Running the OCR loop directly in an `async def` function without `run_in_executor` or `asyncio.to_thread`.
**Why it happens:** Misunderstanding how `async` works; thinking `requests` becomes non-blocking just because it's in an `async` function.
**How to avoid:** Always wrap synchronous I/O (like `requests` or `PIL`) in `run_in_executor`.

### Pitfall 2: Race Conditions in Progress Updates
**What goes wrong:** Multiple threads updating the same "percentage" counter simultaneously.
**Why it happens:** `ThreadPoolExecutor` threads sharing a simple integer.
**How to avoid:** Use an `asyncio.Queue` or a thread-safe counter (`threading.Lock`) to manage state updates.

### Pitfall 3: Directory Name Collisions
**What goes wrong:** Two batches with the same name overwriting each other.
**Why it happens:** User inputs "Batch1" twice.
**How to avoid:** Mandatory suffix with `[Human Readable Timestamp]_[Unique ID]` as per Decisions.

## Code Examples

### FastAPI File Upload to Temp
```python
# app/api/endpoints/upload.py
import shutil
from fastapi import UploadFile, File

@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    session_id = generate_id()
    temp_dir = Path(f"data/temp/{session_id}")
    temp_dir.mkdir(parents=True)
    
    for file in files:
        file_path = temp_dir / file.filename
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    return {"session_id": session_id, "count": len(files)}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Procedural CLI | FastAPI Services | Phase 1 Plan | Enables UI-based interaction and concurrent multi-batch support. |
| Print-based logging | WebSocket Streams | Phase 1 Plan | Real-time user feedback; professional "SaaS-like" feel. |
| Global Checkpoint | Per-batch Checkpoint | Phase 1 Plan | Prevents cross-batch state corruption; allows independent resumes. |

## Open Questions

1. **How to handle "Batch Locking" across restarts?**
   - Recommendation: Create a `.lock` file or a `state.json` inside the batch directory. If `status == "processing"`, prevent modifications.
2. **Should we use `BackgroundTasks` or `asyncio.create_task`?**
   - Recommendation: Use `asyncio.create_task` for OCR because `BackgroundTasks` only runs *after* the response is sent, and we want to return a "Task Started" status immediately while the engine initializes.

## Sources

### Primary (HIGH confidence)
- FastAPI Docs (UploadFile, WebSockets) - Verified standard patterns.
- `indexcard_ocr.py` - Source code for existing logic.
- .planning/1-CONTEXT.md - Project-specific requirements.

### Secondary (MEDIUM confidence)
- StackOverflow / GitHub Discussions - Patterns for FastAPI WebSocket progress updates.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - FastAPI is industry standard.
- Architecture: HIGH - Modular service pattern is well-proven.
- Pitfalls: HIGH - Common async/threading issues are well-documented.

**Research date:** 2025-05-22
**Valid until:** 2025-06-22
