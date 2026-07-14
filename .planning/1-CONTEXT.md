# Phase 1 Context: Backend Foundation

## Overview
This phase establishes the FastAPI backend to wrap the existing OCR logic, providing a robust API for the React frontend to manage batches, configure fields, and track progress.

## Decisions

### 1. Upload & Batch Lifecycle
- **Naming Convention:** Batches are named using a `[Custom Name]_[Human Readable Timestamp]_[Unique ID]` format.
- **File Management:** 
  - Uploaded images are stored in a temporary area.
  - Upon starting processing, they are moved to a permanent batch-specific directory.
- **Cleanup Policy:** Manual cleanup only; the system will not auto-delete data to avoid accidental loss.
- **State:** Batches are "appendable" during the upload phase but become "locked/frozen" once processing starts.
- **Access:** No requirement to serve original images back via the API for now.

### 2. Dynamic Field API
- **Validation:** At least one field must be active to start a task. The UI should include a verification step to confirm field names and intent.
- **Persistence:** Field configurations (the "schema") must be storable as reusable templates for future batches.
- **Prompting:** No "predefined" global fields; every batch starts from a blank slate or a selected template.
- **API Flow:** The frontend sends the field list; the backend generates the appropriate VLM prompt internally.

### 3. Progress Reporting
- **Communication:** **WebSockets** will be used for real-time updates.
- **Metrics:** Updates must include:
  - Completion percentage.
  - "File X of Y" counter.
  - Estimated time remaining.
- **Data Streaming:** Individual card results (extracted JSON) should be pushed via the WebSocket as they are completed to provide a live preview.
- **Resilience:** The backend must support "re-attaching" to an ongoing task if the frontend client refreshes or reconnects.

### 4. Failure & Recovery
- **Individual Errors:** If a card fails, the system logs the error and **skips to the next card** without stopping the batch.
- **Error Storage:** Failed images should be moved to an `_errors/` subfolder within the batch directory for manual review.
- **Interruption Recovery:** The system must support resuming interrupted batches (e.g., after a server restart) using the existing checkpointing logic.
- **Retry Mechanism:** Provide a dedicated API endpoint to retry only the failed cards within a specific batch.

## Deferred Ideas
- *N/A (All discussed items prioritized for Phase 1 or current scope)*
