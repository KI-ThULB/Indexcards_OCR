---
status: resolved
phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick
source: 06-02-SUMMARY.md, 06-03-SUMMARY.md, 06-04-SUMMARY.md, 06-05-SUMMARY.md, 06-06-SUMMARY.md, 06-07-SUMMARY.md, 06-08-SUMMARY.md
started: 2026-02-23T19:00:00Z
updated: 2026-02-23T19:00:00Z
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

[testing complete]

## Tests

### 1. App Branding & Title
expected: Header shows title "Archival Metadata Extraction & Export Tool" with an "A" icon. ThULB logo appears in the header and links to thulb.uni-jena.de (opens in new tab). Sidebar footer shows "A Hack the Heritage Project" label with the event banner image.
result: pass

### 2. Provider Selection in Configure Step
expected: The Configure step sidebar shows a provider selector with radio buttons for OpenRouter and Ollama. Each provider has a model dropdown with provider-specific defaults. Switching provider changes the available model.
result: pass

### 3. Processing Step (Progress & WebSocket)
expected: After starting a batch, the Processing step shows a progress bar with percentage, an X/Y counter, and a live feed of processed cards. A cancel button is available. If connection drops briefly, it reconnects automatically.
result: pass

### 4. Results Table Layout (4 Columns)
expected: Results table shows exactly 4 columns in this order: Image, Status, Time, Extraction. No separate "Filename" or "Actions" column exists. Extraction is the widest column (rightmost).
result: issue
reported: "image column is not sortable, rest ok"
severity: minor

### 5. Extraction Column Key-Value Pairs
expected: Each row's Extraction cell shows all OCR fields as aligned key-value pairs (field label on the left, value on the right) using a definition-list layout. Internal fields starting with underscore (_entries, _entry_count) are not shown.
result: pass

### 6. Editable Cells (Textarea with Multiline)
expected: Clicking a value in the Extraction column opens a textarea for editing (not a single-line input). Plain Enter inserts a newline. Ctrl+Enter (or Cmd+Enter on Mac) commits the edit. Escape cancels. After committing, the display preserves line breaks.
result: pass

### 7. Lightbox on Filename Click
expected: Clicking the filename text link (with small Image icon) in the Image column opens a full-size lightbox overlay showing the card image. The lightbox can be closed by clicking outside it or pressing Escape.
result: pass

### 8. Status Column (Error Tooltip & Retry)
expected: For a failed row, the status chip shows "failed". Hovering over the chip displays the error message as a native browser tooltip. A retry button appears below the chip in the same column. No separate "Actions" column exists.
result: pass

### 9. Export Formats (CSV, JSON, XML)
expected: The summary banner above the results table has an export dropdown offering CSV, JSON, and 6 XML formats (LIDO, EAD, Darwin Core, Dublin Core, MARC21-XML, METS/MODS). Clicking a format downloads a file to your computer.
result: pass

### 10. Multi-Entry Row Expansion
expected: For cards where the AI returned multiple entries (array), the table shows sub-rows with entry labels like "Eintrag 2 / 7" displayed in the Image column. Each sub-entry has its own editable Extraction fields.
result: pass

## Summary

total: 10
passed: 9
issues: 1
pending: 0
skipped: 0

## Gaps

- truth: "Image column is sortable (clicking header sorts rows by filename)"
  status: resolved
  reason: "User reported: image column is not sortable, rest ok"
  severity: minor
  test: 4
  root_cause: "Thumbnail column used columnHelper.display() which has no data accessor — TanStack Table cannot sort display-only columns"
  artifacts:
    - path: "apps/frontend/src/features/results/ResultsTable.tsx"
      issue: "columnHelper.display() on thumbnail column — no accessor for sorting"
  missing:
    - "Change to columnHelper.accessor('_pageFilename') with enableSorting: true"
  debug_session: ""
