# Phase 3: Processing & Results (React) - Context

**Gathered:** 2026-02-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the "Process" button to the backend OCR engine via WebSocket, show real-time processing progress with a live feed of extracted data, then display results in an editable data table with summary stats, image thumbnails, retry capability, and CSV/JSON export.

</domain>

<decisions>
## Implementation Decisions

### Progress Experience
- Rich per-image updates: progress bar + current image name + X/Y count + estimated time remaining
- Live feed of extracted data streams in below the progress bar as each image completes
- Cancel button available during processing — partial results are kept and shown in results
- Auto-navigate to Results step after completion (short "Complete!" delay ~2s)
- Early stop on catastrophic failure: after 3 consecutive failures, stop processing and show error screen with troubleshooting hints (e.g. "API connection failed — check your OPENROUTER_API_KEY")

### Results Presentation
- Data table layout (spreadsheet-like): one row per image, columns for each extracted field
- Summary banner at top: total processed, success count, error count, total duration, batch name
- Inline editing: click a cell to correct OCR mistakes before exporting
- Thumbnail column with lightbox: small thumbnail per row, click to open full-size image overlay for verifying OCR accuracy
- Table should be sortable by columns

### Error Handling UX
- Failed images appear inline in the same results table with a red status indicator and error message
- Both per-image "Retry" button on each failed row AND a "Retry All Failed" button at the top
- Retry re-runs OCR on just the failed image(s) and updates the table in-place
- During live feed: Claude's discretion on how failures appear (red inline entry vs toast)

### CSV/Export Behavior
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

</decisions>

<specifics>
## Specific Ideas

- The live feed during processing should feel like watching a log — each completed image's data appears as it finishes, giving a sense of momentum
- The results table is the primary deliverable view — this is what museum staff will spend time in, verifying and correcting OCR before exporting to their collection management system
- The audit trail (original + edited columns in CSV) matters because museums need to know what was machine-extracted vs human-corrected

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-processing-results-react*
*Context gathered: 2026-02-21*
