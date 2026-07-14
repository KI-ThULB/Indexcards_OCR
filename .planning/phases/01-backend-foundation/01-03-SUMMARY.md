# Wave 3 Summary: Live Updates & Resilience

## Accomplishments
- **WebSocket Progress Tracking**: Implemented `ConnectionManager` in `backend/app/services/ws_manager.py` for real-time status updates.
  - **Endpoint**: `/api/v1/ws/task/{batch_id}` provides a live stream of OCR results and progress.
  - **Re-attach Logic**: Clients can reconnect to ongoing tasks and immediately receive the latest `BatchProgress` state.
  - **Metrics**: Broadcasts percentage, "File X of Y" counter, and estimated time remaining (ETA).
- **Resilient OCR Execution**: Enhanced `OcrEngine` to gracefully handle individual card failures.
  - **Skip-on-Error**: Failed cards are logged and moved to an `_errors/` subfolder, allowing the batch to continue.
  - **Checkpointing**: Uses `checkpoint.json` to track successful extractions and support resuming interrupted batches.
- **Retry & Background Processing**:
  - **Retry API**: `POST /api/v1/batches/{batch_id}/retry` re-processes only the images in the `_errors/` folder.
  - **Background Tasks**: Long-running OCR jobs are executed using FastAPI's `BackgroundTasks` to keep the API responsive.
- **Dynamic Prompting**: The OCR engine now dynamically builds its extraction prompt based on the fields configured for each specific batch.

## Verification Results
- **WebSocket Streaming**: Verified live updates (%, X/Y, card data) using a test client.
- **Error Handling**: Confirmed that a simulated failure results in the image being moved to `_errors/` and processing continuing for other images.
- **Retry Logic**: Verified that the retry endpoint correctly moves files back from `_errors/` for re-processing.

## Technical Notes
- The `OcrEngine` uses `asyncio.run_coroutine_threadsafe` to bridge the gap between worker threads and the WebSocket event loop.
- Batch configuration (fields, status) is persisted in a `config.json` within the batch directory.
