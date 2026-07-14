---
status: complete
phase: 02-frontend-scaffold-configuration-react
source: 02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md
started: 2026-02-22T17:30:00Z
updated: 2026-02-22T19:00:00Z
---

## Tests

### 1. Parchment Theme & Layout Shell
expected: The app renders with a museum/archive aesthetic: parchment-toned background, serif font (Crimson Text) for headings and body text, monospace font (IBM Plex Mono) for technical labels. The layout has a sticky header at top, a vertical sidebar on the left with step indicators, a scrollable main content area, and a footer bar at the bottom.
result: pass

### 2. Drag-and-Drop Upload
expected: In the Upload step, there is a dropzone area. Dragging image files (JPG, PNG, WEBP) onto it uploads them to the backend. Dropped files immediately appear in a scrollable file list below with filename, formatted size, and file type.
result: pass

### 3. Upload Rejection Toasts
expected: Dropping an invalid file type (e.g., .txt, .pdf) or a file exceeding 10MB shows a toast notification explaining the rejection. The invalid file is not added to the list.
result: pass

### 4. File Delete with Confirmation
expected: Each file in the list has a Delete button. Clicking it shows a confirmation toast. After confirming, the file is removed from the list.
result: pass

### 5. Footer Live Stats
expected: The footer bar shows live statistics: file count, total batch size in MB, and number of active fields. These update in real-time as files are added/removed and fields are changed.
result: issue
reported: "footer as well as header are transparent in bg, that leads to buggy visual. as well check if on every page is enough margin bottom that no content is behind the footer in any case"
severity: minor

### 6. Upload-to-Configure Gate
expected: The "Next" or "Continue" button to proceed from Upload to Configure is disabled or blocked when no files have been uploaded. After uploading at least one file, the button becomes active and clicking it advances to the Configure step.
result: pass
note: "User feedback for later: (1) Need ability to navigate back to previous steps to fix mistakes (upload more files, fix typos in field config). (2) Proceed/back buttons should be more prominent — duplicated top+bottom or sticky floating, so user doesn't have to scroll to find them."

### 7. Field Manager CRUD
expected: In the Configure step, there is a field manager where you can add new extraction fields by typing a name and clicking Add. Each field has a delete action with confirmation toast. Fields persist in the wizard store.
result: pass

### 8. Template Selector
expected: A template dropdown in Configure fetches available templates from the backend. Selecting a template auto-populates the field list with that template's fields. A "Blank Slate" option clears all fields.
result: pass

### 9. Commence Processing Flow
expected: After entering a batch name and configuring fields, clicking "Commence Processing" (or equivalent) creates the batch via API, starts OCR processing, and transitions the wizard to the Processing step.
result: pass

### 10. Start Fresh Reset
expected: Clicking "Start Fresh" in the header resets the wizard back to the Upload step, clearing files, fields, and batch data.
result: issue
reported: "button has not the full click area at all times. Also the nav left is not always full scrollable — scrolls with main content, gets cut off. Nav and main should not share scroller."
severity: minor

### 11. Sidebar Step Tracking
expected: The sidebar shows all wizard steps (Upload, Configure, Processing, Results). The current step is highlighted as active. Completed steps show a different visual state (e.g., checkmark or muted style). Pending steps appear dimmed.
result: pass
note: "User reiterated: back-navigation to previous steps is not possible yet."

### 12. Zustand State Persistence
expected: After uploading files and configuring fields, refreshing the browser page preserves the wizard state — you return to the same step with the same data (files listed, fields configured).
result: pass

## Summary

total: 12
passed: 10
issues: 2
pending: 0
skipped: 0
gaps_from_feedback: 2

## Gaps

- truth: "Header and footer have opaque backgrounds so content doesn't show through when scrolling, and all pages have sufficient bottom margin to avoid content hiding behind the footer"
  status: fixed
  reason: "User reported: footer as well as header are transparent in bg, that leads to buggy visual. as well check if on every page is enough margin bottom that no content is behind the footer in any case"
  severity: minor
  test: 5
  root_cause: "Header used bg-parchment/80 (80% opacity) and Footer used bg-parchment-dark/50 (50% opacity). Content wrapper had z-10 competing with header/footer z-10. No bottom padding for footer clearance."
  artifacts: ["Header.tsx", "Footer.tsx", "MainLayout.tsx"]
  missing: []
  fix: "Header: bg-parchment (opaque) + z-30. Footer: bg-parchment (opaque) + z-20. MainLayout: removed z-10 from content wrapper, added pb-16 for footer clearance."

- truth: "Start Fresh button is fully clickable at all times. Sidebar scrolls independently from main content and is never cut off."
  status: fixed
  reason: "User reported: button has not the full click area at all times. Nav left is not always full scrollable — scrolls with main content, gets cut off."
  severity: minor
  test: 10
  root_cause: "Header z-10 conflicted with content wrapper z-10, causing content to paint over header buttons in some states. Sidebar used h-[calc(100vh-4rem)] hardcoded height that didn't account for footer and lacked independent overflow scrolling."
  artifacts: ["Header.tsx", "Sidebar.tsx", "MainLayout.tsx"]
  missing: []
  fix: "Header: z-30 (above content). Sidebar: h-full + overflow-y-auto + shrink-0 for independent scrolling within flex container."

- truth: "Users can navigate back to completed wizard steps to fix mistakes (upload more files, fix field config)"
  status: failed
  reason: "User reported: can't go back to a former step if I missed something like uploading additional info or have a typo in field config"
  severity: minor
  test: 6, 11
  root_cause: "Sidebar steps are display-only. No onClick handlers on completed steps — by design decision 'step transitions only via store actions to enforce wizard order'. Back-navigation was not implemented."
  artifacts: ["Sidebar.tsx"]
  missing: ["onClick handlers for completed steps", "cursor-pointer hover styles"]
  plan: "02-04-PLAN.md"

- truth: "Proceed/back buttons are always visible without scrolling on all wizard steps"
  status: failed
  reason: "User reported: proceed/back buttons should be more prominent or duplicated top+bottom or floating sticky so user doesn't need endless scrolling"
  severity: minor
  test: 6
  root_cause: "Navigation buttons are inline at the bottom of each step's content. On long pages (many files, many fields), users must scroll past all content to reach the buttons."
  artifacts: ["UploadStep.tsx", "ConfigureStep.tsx", "ResultsStep.tsx"]
  missing: ["Sticky/floating navigation bar component"]
  plan: "02-05-PLAN.md"
