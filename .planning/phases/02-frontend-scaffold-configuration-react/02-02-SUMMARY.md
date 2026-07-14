# Phase 2 Wave 2 Summary: Upload Workflow

**Date:** 2026-02-21
**Objective:** Implement Step 1 (Upload) of the wizard with Dropzone, List View, and Backend API synchronization.

## Accomplishments
- **Dropzone:** Created a "Museum-Ready" drag-and-drop component using `react-dropzone`.
  - Restricted to JPG, PNG, WEBP.
  - 10MB file size limit with Toast notifications for rejections.
  - Integrated `useUploadMutation` to sync files with the backend immediately on drop.
- **FileList:** Implemented a scrollable list view for staged files.
  - Displays filename, formatted size, and file type.
  - Includes a "Delete" action with a confirmation toast.
- **Upload API:** Created `uploadApi.ts` using TanStack Query.
  - Handles multi-file upload via `POST /api/v1/upload/`.
  - Manages `session_id` returned from the backend.
- **State Management:** Updated `wizardStore.ts` to include `sessionId` persistence and `setSessionId` action.
- **Shell Integration:**
  - Integrated `UploadStep` into the main application flow.
  - Configured Vite proxy for seamless API communication during development.
  - Added `QueryClientProvider` and `Toaster` to the application entry point.
- **Live Stats:** Footer now displays live file counts and total batch size in MB.

## Technical Details
- **API Endpoint:** `POST /api/v1/upload/`
- **State Store:** `useWizardStore` (Zustand)
- **Data Fetching:** `@tanstack/react-query`
- **Styling:** Tailwind CSS (Parchment theme)

## Verification Results
- [x] Files appear in list immediately after drop.
- [x] Delete confirmation prevents accidental data loss.
- [x] Backend receives files and returns a session ID.
- [x] Footer updates accurately as the batch changes.
- [x] Navigation to Step 2 is blocked until at least one file is staged.
