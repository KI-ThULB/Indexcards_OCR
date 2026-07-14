---
phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick
plan: 03
subsystem: ui
tags: [react, zustand, tanstack-table, yet-another-react-lightbox, websocket, typescript, provider-selection, xml-export]

# Dependency graph
requires:
  - phase: 06-02
    provides: "BatchStartRequest schema with provider/model fields; _resolve_provider() backend helper"
  - phase: 03-processing-results-react
    provides: "Source branch implementations of processing/results features to port"
provides:
  - "OcrProvider type + PROVIDER_DEFAULT_MODELS exported from wizardStore"
  - "provider/model Zustand state + setProvider/setModel actions (Feature 8)"
  - "ProviderSelector.tsx component: radio provider + model dropdown (Feature 4)"
  - "startBatch API call passes provider/model to backend (Feature 9)"
  - "ConfigureStep wires ProviderSelector; sends provider/model on batch start (Feature 4)"
  - "useProcessingWebSocket uses recursive connect() for robust reconnects (Feature 1)"
  - "useResultsExport: CSV/JSON + LIDO/EAD/Darwin Core/Dublin Core/MARC21/METS export (Feature 2)"
  - "SummaryBanner with XML dropdown (MARC21, METS/MODS, LIDO, EAD, Darwin Core, Dublin Core) (Feature 2)"
  - "ThumbnailCell with fixed-position hover preview overlay (Feature 2)"
  - "ResultsTable with multi-entry Findmittel expansion, thumbnail column, retryingFilename (Feature 2)"
  - "ResultsStep with retryingFilename state, hydratedRef guard, all XML exports wired (Feature 2)"
affects:
  - "06-04 (Processing step enhancements)"
  - "06-05 (Final results/App.tsx integration)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "OcrProvider type: 'openrouter' | 'ollama' — extensible via PROVIDER_DEFAULT_MODELS map"
    - "recursive connect() pattern in WebSocket hook: wsRef.current === ws guard prevents stale reconnects"
    - "_entries JSON array in result.data: multi-entry detection expands into DisplayRow sub-rows"
    - "fixed-position hover overlay: escapes table overflow:hidden for thumbnail preview"
    - "hydratedRef guard: prevents double setResults on React Strict Mode double-invoke"
    - "retryingFilename state: tracks per-row retry spinner without global isProcessing flag"

key-files:
  created:
    - "apps/frontend/src/features/configure/ProviderSelector.tsx"
  modified:
    - "apps/frontend/src/store/wizardStore.ts"
    - "apps/frontend/src/api/batchesApi.ts"
    - "apps/frontend/src/features/configure/ConfigureStep.tsx"
    - "apps/frontend/src/features/processing/useProcessingWebSocket.ts"
    - "apps/frontend/src/features/results/useResultsExport.ts"
    - "apps/frontend/src/features/results/SummaryBanner.tsx"
    - "apps/frontend/src/features/results/ThumbnailCell.tsx"
    - "apps/frontend/src/features/results/ResultsTable.tsx"
    - "apps/frontend/src/features/results/ResultsStep.tsx"

key-decisions:
  - "No customPrompt anywhere — Feature 5 rejected; prompt_template naming from main preserved throughout"
  - "OcrProvider defaults to 'openrouter' in store initialState; PROVIDER_DEFAULT_MODELS maps to model strings"
  - "startBatch sends { provider, model } in POST body; backend _resolve_provider() handles resolution"
  - "recursive connect() pattern replaces direct ws assignment in onclose: single responsibility, avoids stale closure sharing"
  - "SummaryBanner XML dropdown is client-side only: all formats generated in-browser from results array"
  - "ResultsTable multi-entry expansion: __entry_N suffix creates unique virtual filename for per-entry editedData keying"
  - "hydratedRef guard in ResultsStep: prevents double setResults on React Strict Mode double-invoke"

patterns-established:
  - "Provider selection: OcrProvider type + PROVIDER_DEFAULT_MODELS + ProviderSelector component + store state"
  - "Multi-entry display: _entries JSON field in result.data → useMemo DisplayRow expansion → sub-row rendering"
  - "XML export suite: escapeXml helper + fieldValue(row, field) helper + per-format generator function"

# Metrics
duration: 35min
completed: 2026-02-23
---

# Phase 06 Plan 03: Frontend Feature Reimplementation Summary

**Provider-selectable OCR frontend (OpenRouter/Ollama) with multi-entry results table, 8-format XML export, hover thumbnails, and robust WebSocket reconnect**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-02-23T01:00:00Z
- **Completed:** 2026-02-23T01:35:00Z
- **Tasks:** 6 (11 files across features 8, 9, 4, 1, 2)
- **Files modified:** 9 existing + 1 new

## Accomplishments

- Added `OcrProvider` type, `PROVIDER_DEFAULT_MODELS`, `provider`/`model` state + `setProvider`/`setModel` to Zustand store (Feature 8)
- Updated `startBatch` API call to send `{ provider, model }` in POST body to match new `BatchStartRequest` backend schema (Feature 9)
- Created `ProviderSelector.tsx` with radio group for OpenRouter/Ollama + per-provider model dropdown (Feature 4)
- Wired `ProviderSelector` into `ConfigureStep` sidebar — provider/model flows into batch start call (Feature 4)
- Improved `useProcessingWebSocket` to use recursive `connect()` closure — single guard prevents stale reconnect (Feature 1)
- Ported full Results step from source branch: multi-entry `_entries` array expansion, thumbnail hover preview, 8 XML export formats (LIDO, EAD, Darwin Core, Dublin Core, MARC21, METS/MODS + CSV + JSON), per-row `retryingFilename` spinner (Feature 2)

## Task Commits

Each task was committed atomically:

1. **Task 1: Store expansion** — `57ab516` (feat)
2. **Task 2: batchesApi startBatch** — `c307d6a` (feat)
3. **Task 3: ProviderSelector component** — `a3a9e9e` (feat)
4. **Task 4: ConfigureStep wiring** — `a43221d` (feat)
5. **Task 5: WebSocket reconnect** — `fe77f9e` (feat)
6. **Task 6: Results step bundle** — `edc81ac` (feat)

## Files Created/Modified

- `apps/frontend/src/store/wizardStore.ts` — Added OcrProvider, PROVIDER_DEFAULT_MODELS, provider/model state+actions, partialize
- `apps/frontend/src/api/batchesApi.ts` — startBatch accepts { batchName, provider?, model? }
- `apps/frontend/src/features/configure/ProviderSelector.tsx` — New component: provider radio + model select
- `apps/frontend/src/features/configure/ConfigureStep.tsx` — Import+render ProviderSelector, pass provider/model to startBatch
- `apps/frontend/src/features/processing/useProcessingWebSocket.ts` — Recursive connect() pattern
- `apps/frontend/src/features/results/useResultsExport.ts` — Full XML export suite (6 formats + CSV + JSON)
- `apps/frontend/src/features/results/SummaryBanner.tsx` — XML dropdown, restructured stats
- `apps/frontend/src/features/results/ThumbnailCell.tsx` — Hover preview overlay (fixed-position, 340x256)
- `apps/frontend/src/features/results/ResultsTable.tsx` — Multi-entry expansion, ThumbnailCell, retryingFilename
- `apps/frontend/src/features/results/ResultsStep.tsx` — retryingFilename state, hydratedRef, all exports wired

## Decisions Made

- **Feature 5 rejected throughout**: `prompt_template` naming from main preserved in ConfigureStep; no `customPrompt` state or `PromptEditor` import anywhere
- **OcrProvider defaults to openrouter**: `initialState.provider = 'openrouter'` with matching model — backward compatible with existing sessions
- **startBatch body always includes provider**: even when using default, the body is explicit `{ provider: 'openrouter', ... }` — no ambiguity in backend resolution
- **Recursive connect() replaces direct ws assignment**: previous impl assigned `newWs.onmessage = ws.onmessage` which shared the same function reference; new impl is cleaner and avoids React Strict Mode pitfalls
- **Multi-entry virtual filenames**: `${pageFilename}__entry_${idx}` used as Zustand `updateResultCell` key — allows per-entry edit tracking without schema changes
- **hydratedRef guard retained from main**: prevents double-hydration in React Strict Mode (double-invoke of useEffect)
- **XML exports are fully client-side**: no new backend endpoints needed; all 6 XML formats generated in-browser from `results` array

## Deviations from Plan

None — plan executed exactly as specified in the critical context. All 5 accepted features (8, 4, 9, 1, 2) ported. Feature 5 (PromptEditor/customPrompt) correctly excluded throughout.

## Issues Encountered

None — TypeScript compilation passed cleanly on first check (`tsc --noEmit` 0 errors).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All accepted frontend features now on `feat/phase-06-ported-features`
- Provider selection fully wired end-to-end: UI → Zustand → API → backend `_resolve_provider()`
- Results step ready for UAT: multi-entry, thumbnails, XML exports, per-row retry
- Ready for Plan 04: ProcessingStep enhancements (fields display, error details from source branch)
- Ready for Plan 05: App.tsx integration / final merge

---
*Phase: 06-merge-features-of-main-and-current-branch-with-interview-which-feature-to-pick*
*Completed: 2026-02-23*
