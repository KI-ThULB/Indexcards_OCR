---
phase: 01-backend-foundation
plan: 05
subsystem: ui
tags: [react, tanstack-query, zustand, tailwindcss, lucide-react]

# Dependency graph
requires:
  - phase: 01-backend-foundation
    provides: "Template CRUD endpoints (POST/GET/PUT/DELETE /api/v1/templates)"
provides:
  - "useCreateTemplateMutation — POST /api/v1/templates/ with toast + query invalidation"
  - "useUpdateTemplateMutation — PUT /api/v1/templates/{id} (future use)"
  - "useDeleteTemplateMutation — DELETE /api/v1/templates/{id} with toast + query invalidation"
  - "SaveTemplateDialog — modal dialog for naming a new template before saving"
  - "ImagePreview — first uploaded image preview with cursor-following magnifier lens"
  - "FieldManager Save as Template button — wired to create mutation"
  - "TemplateSelector refactored to custom dropdown — per-template delete button"
affects:
  - "UAT test 4: Template CRUD from frontend"
  - "Configure step UX: users can now save/delete templates and read index cards while defining fields"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "useMutation with onSuccess invalidateQueries for template CRUD"
    - "Custom div-based dropdown instead of <select> for interactive per-item actions"
    - "Pure CSS/JS magnifier lens using relative cursor position + scaled overlaid <img>"

key-files:
  created:
    - apps/frontend/src/features/configure/SaveTemplateDialog.tsx
    - apps/frontend/src/features/configure/ImagePreview.tsx
  modified:
    - apps/frontend/src/api/templatesApi.ts
    - apps/frontend/src/features/configure/FieldManager.tsx
    - apps/frontend/src/features/configure/TemplateSelector.tsx
    - apps/frontend/src/features/configure/ConfigureStep.tsx

key-decisions:
  - "Custom div dropdown for TemplateSelector: HTML <select> cannot render custom markup inside <option>, so refactored to div-based list with per-row Trash2 delete button"
  - "Magnifier uses pure CSS/JS (no library): overlaid scaled <img> positioned from cursor's relative x/y in container, no external dependency"
  - "ImagePreview reads files[0].preview (blob URL) from Zustand: temp files not served by StaticFiles, blob URLs already created during upload step"
  - "ImagePreview falls back to placeholder text when preview is undefined (blob URL lost on page refresh/hydration)"

patterns-established:
  - "Template mutation hooks follow error-handler pattern: extract error.response?.data?.detail or fallback message"
  - "Dropdown backdrop pattern: fixed inset-0 z-10 div to close on outside click, dropdown z-20 above it"

# Metrics
duration: 2min
completed: 2026-02-22
---

# Phase 01 Plan 05: Template Save/Delete UI & Image Preview with Magnifier Summary

**Save-as-template modal + per-template delete in custom dropdown, plus first-image card preview with 2.5x cursor magnifier in Configure step sidebar**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-22T11:16:17Z
- **Completed:** 2026-02-22T11:19:10Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Users can save current field configuration as a named template via POST /api/v1/templates/
- Users can delete templates via DELETE /api/v1/templates/{id} — list auto-refreshes via query invalidation
- TemplateSelector refactored from native `<select>` to custom div dropdown supporting per-template delete actions
- First uploaded image is visible in the Configure step sidebar, with a 2.5x circular magnifier lens following the cursor

## Task Commits

Each task was committed atomically:

1. **Task 1: Add template mutations and Save/Delete UI** - `a7fa70c` (feat)
2. **Task 2: Add first-image preview with hover magnifier to Configure step** - `d8d2b8a` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `apps/frontend/src/api/templatesApi.ts` - Added useCreateTemplateMutation, useUpdateTemplateMutation, useDeleteTemplateMutation alongside existing useTemplatesQuery
- `apps/frontend/src/features/configure/SaveTemplateDialog.tsx` - New: modal overlay dialog with name input, Save/Cancel buttons, Enter/Escape keyboard support (89 lines)
- `apps/frontend/src/features/configure/FieldManager.tsx` - Added Save as Template button (disabled when no fields), showSaveDialog state, wired to useCreateTemplateMutation
- `apps/frontend/src/features/configure/TemplateSelector.tsx` - Refactored from native `<select>` to custom div-based dropdown; per-template Trash2 delete button using useDeleteTemplateMutation
- `apps/frontend/src/features/configure/ImagePreview.tsx` - New: reads files[0].preview from Zustand, renders image with 150px magnifier circle (2.5x zoom) following cursor on mouseMove (106 lines)
- `apps/frontend/src/features/configure/ConfigureStep.tsx` - Added ImagePreview import and conditional render in sidebar (files.length > 0 guard)

## Decisions Made
- **Custom div dropdown for TemplateSelector:** HTML `<select>` does not support custom markup inside `<option>`, so refactored to div-based list with per-row Trash2 delete button
- **Magnifier uses pure CSS/JS:** Overlaid scaled `<img>` positioned from cursor's relative x/y in container; no external library needed
- **ImagePreview reads blob URL (not backend URL):** Temp session files are not served by StaticFiles; blob URLs are already created during upload step via URL.createObjectURL
- **Graceful fallback:** When preview is undefined (blob URL lost on page refresh/hydration), shows "Image preview unavailable" placeholder text

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- UAT test 4 (Template CRUD from frontend) should now pass: users can create templates via Save as Template dialog and delete them from the TemplateSelector dropdown
- Image preview with magnifier closes the gap for reading index card content while defining extraction fields
- All six modified files pass `npx tsc --noEmit` with zero errors

## Self-Check: PASSED

All files found on disk. Both task commits (`a7fa70c`, `d8d2b8a`) verified in git log.

---
*Phase: 01-backend-foundation*
*Completed: 2026-02-22*
