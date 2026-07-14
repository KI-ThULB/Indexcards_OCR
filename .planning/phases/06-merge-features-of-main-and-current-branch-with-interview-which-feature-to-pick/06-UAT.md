---
status: resolved
phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick
source: 06-07-SUMMARY.md
started: 2026-02-23T18:00:00Z
updated: 2026-02-23T18:20:00Z
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

[testing complete]

## Tests

### 1. Extraction Column Layout (Key-Value Pairs)
expected: Results table shows a single "Extraction" column (not N individual field columns). Inside each cell, fields appear as aligned key-value pairs: field label on the left, editable value on the right. All fields for one card are stacked vertically within that single cell.
result: issue
reported: "valuefield should be shown multiline when the result is multiline, edit field should be always a textarea and not an input"
severity: major

### 2. Editable Cells in Extraction Column
expected: Clicking on a value in the Extraction column makes it editable (inline edit). After editing and confirming, the cell shows the updated value with a visual indicator that it was edited.
result: pass

### 3. Error as Tooltip on Status Chip
expected: For a failed row, hovering over the status chip (showing "failed") displays the error message as a native browser tooltip. No separate error column or error display area exists.
result: pass

### 4. Retry Button in Status Column
expected: For a failed row, a "Retry" button appears directly below the status chip within the same status column cell. No separate "Actions" column exists in the table.
result: pass

### 5. Thumbnail as Text Link (No Inline Images)
expected: The image/thumbnail column shows only a text link (filename with a small image icon) — no inline `<img>` thumbnails. No hover preview overlay appears.
result: issue
reported: "good, but now we have a duplication, the file name is shown in the image and the file column, remove the file column at all"
severity: minor

### 6. Lightbox Opens on Thumbnail Click
expected: Clicking the filename text link in the thumbnail column opens a full-size lightbox overlay showing the card image. The lightbox can be closed by clicking outside or pressing Escape.
result: pass

### 7. Table Column Order
expected: Table columns appear in this order: Image (thumbnail link), Filename, Status (with retry/error), Extraction (key-value pairs), Time/Duration.
result: issue
reported: "move time/duration before extraction"
severity: cosmetic

## Summary

total: 7
passed: 4
issues: 3
pending: 0
skipped: 0

## Gaps

- truth: "Value fields in Extraction column show multiline content and use textarea for editing"
  status: resolved
  reason: "User reported: valuefield should be shown multiline when the result is multiline, edit field should be always a textarea and not an input"
  severity: major
  test: 1
  root_cause: "EditableCell component (ResultsTable.tsx lines 48-93) renders <input> element for editing. Input is single-line only — Enter commits instead of creating new lines. Ref typed as HTMLInputElement. Display mode uses whitespace-pre-line but edit mode is single-line input."
  artifacts:
    - path: "apps/frontend/src/features/results/ResultsTable.tsx"
      issue: "EditableCell renders <input> (line 69) instead of <textarea>; ref typed as HTMLInputElement (line 51)"
  missing:
    - "Change <input> to <textarea> with auto-resize"
    - "Change ref type from HTMLInputElement to HTMLTextAreaElement"
    - "Update Enter key handler to allow newlines (Shift+Enter or remove Enter-to-commit)"
    - "Ensure display mode preserves whitespace/newlines (whitespace-pre-wrap)"
  debug_session: ""

- truth: "Table column order: Image, Status, Time/Duration, Extraction (extraction last as widest column)"
  status: resolved
  reason: "User reported: move time/duration before extraction"
  severity: cosmetic
  test: 7
  root_cause: "Column definitions array in ResultsTable.tsx orders extraction (line 231) before duration (line 262). Duration should precede extraction so the widest column is last."
  artifacts:
    - path: "apps/frontend/src/features/results/ResultsTable.tsx"
      issue: "Duration column defined after extraction column in columns array (lines 262-271 vs 231-260)"
  missing:
    - "Move duration column definition before extraction column definition in the columns array"
  debug_session: ""

- truth: "No duplicate filename display — Image column text link is sufficient, no separate Filename column"
  status: resolved
  reason: "User reported: good, but now we have a duplication, the file name is shown in the image and the file column, remove the file column at all"
  severity: minor
  test: 5
  root_cause: "Two columns display filename: thumbnail column (lines 154-167) renders ThumbnailCell which shows Image icon + filename as clickable link, AND filename column (lines 169-195) explicitly shows filename/entry label. Both display the same filename text."
  artifacts:
    - path: "apps/frontend/src/features/results/ResultsTable.tsx"
      issue: "Separate filename column (id: 'filename', lines 169-195) redundant with ThumbnailCell filename display"
  missing:
    - "Remove the entire filename column definition (lines 169-195)"
    - "Move any sub-row entry label logic into the thumbnail column if needed"
  debug_session: ""
