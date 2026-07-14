# Phase 2 Context: Frontend Scaffold & Configuration

## Overview
This phase establishes the React frontend (TypeScript + Tailwind) to provide a "Museum-Ready" user interface for managing OCR batches and configurations.

## Decisions

### 1. Upload UX
- **Display Mode:** A **List View** will be used to efficiently manage large numbers of files.
- **File Management:** 
  - **Confirmation:** Users must confirm file deletions.
  - **Error Handling:** Unsupported formats are added to the list but visually marked with an error state; files that are too large trigger a **Toast** notification.
- **Metadata:** The file counter will display both the **total count** and the **cumulative file size** (e.g., "150 Files | 450 MB").

### 2. Configuration UI
- **Starting State:** The configuration step begins with a **blank slate**, but users can select a "Collection Type" (template) from the UI to pre-populate fields.
- **Field Management:** 
  - **Deletion:** Users must confirm the removal of any field.
  - **Clarification Step:** The UI will include a specific step to clarify/verify custom fields to ensure correct AI prompting.
- **Dynamic Prompting:** The backend generates the prompt internally, so a live prompt preview is not required in the frontend.

### 3. Step Flow
- **Transitions:** Moving between steps (Upload -> Configure -> Processing) is triggered by an **explicit button click**.
- **Validation:** A **Hard Block** will prevent users from proceeding to the processing step if no fields are active.
- **State Persistence:** Data (uploaded files, configured fields) must **persist** if the user navigates "Back" to a previous step.
- **Global Reset:** A "Start Fresh" button will be visible at all times to clear the current session.

### 4. Visual Style & Feedback
- **Aesthetic:** The design should move beyond a simple dark mode toward a **themed aesthetic** (e.g., "Museum," "Archive," "Perchment," or "Old Paper" textures/colors).
- **Interactions:** The developer has the creative freedom to implement confirmation effects (e.g., pulses, shadows) and toast positioning (e.g., Bottom Right vs. Top Center).
- **Stats:** The footer will feature **Live Stats** that update in real-time as files are uploaded or fields are modified.

## Deferred Ideas
- *N/A (All discussed items prioritized for Phase 2 or current scope)*
