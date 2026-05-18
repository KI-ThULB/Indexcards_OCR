---
phase: 11-authority-reconciliation
plan: 05
subsystem: frontend
tags: [typescript, lido, marcxml, dublin-core, authority-reconciliation, gnd, wikidata, geonames, aat, validation-badge]

# Dependency graph
requires:
  - phase: 11-authority-reconciliation
    plan: "01"
    provides: "ReconciliationOutcome type on ValidationOutcome in batchesApi.ts"
  - phase: 11-authority-reconciliation
    plan: "02"
    provides: "canonical authority URI forms stored in reconciliation.uri"
provides:
  - "getReconciliationUri(row, field) helper — null-safe URI access from ResultRow.validation"
  - "AUTHORITY_SOURCE_LABELS map — maps 8 authority type strings to vocabulary labels (GND/Wikidata/GeoNames/AAT)"
  - "uriToMarc0(uri) helper — converts GND URI to (DE-588){id}; passes Wikidata/GeoNames/AAT URIs through"
  - "downloadLIDO: lido:conceptID with lido:source vocabulary label + lido:actorID for person fields"
  - "downloadMARCXML: $0 subfield with (DE-588) for GND and full URI for others"
  - "downloadDublinCore: xmlns:dcterms namespace + dcterms:identifier per reconciled field"
  - "ValidationBadge: Link2 reconciliation icon with tooltip (label/authority/URI) independent of status"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AUTHORITY_SOURCE_LABELS Record<string, string> — vocabulary label lookup for lido:source (not field name)"
    - "uriToMarc0 regex pattern: /d-nb\\.info\\/gnd\\/(.+)/ for GND detection"
    - "reconTooltipOpen separate useState — independent tooltip state for reconciliation badge"
    - "onMouseEnter/Leave pattern for reconciliation tooltip (consistent with existing corrected-status pattern)"

key-files:
  created: []
  modified:
    - apps/frontend/src/features/results/useResultsExport.ts
    - apps/frontend/src/features/results/ValidationBadge.tsx

key-decisions:
  - "lido:source uses AUTHORITY_SOURCE_LABELS[recon.authority] (vocabulary label like 'GND') — NOT the field name — per plan must_haves"
  - "buildRecord receives optional row parameter for reconciliation lookup — minimal signature change"
  - "DC unmapped fields changed from joined string to per-field loop to enable per-field dcterms:identifier emission"
  - "ValidationBadge renders reconciliation badge even when outcome is null/skipped — returns early with just Link2 icon if reconciliation is set but status is absent"
  - "ResultsTable.tsx unchanged — already passes full ValidationOutcome including reconciliation field"

requirements-completed: [FR4]

# Metrics
duration: ~3min
completed: 2026-05-18
---

# Phase 11 Plan 05: Export URI Emission + Reconciliation Badge Summary

**Authority URIs emitted in LIDO (conceptID/actorID with vocabulary lido:source), MARCXML ($0 with (DE-588) for GND, full URI for others), and Dublin Core (dcterms:identifier sibling elements + xmlns:dcterms namespace); ValidationBadge augmented with Link2 icon and tooltip for reconciled cells**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-18T12:36:52Z
- **Completed:** 2026-05-18T12:40:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `getReconciliationUri(row, field): string | null` helper — null-safe access via optional chaining
- Added `AUTHORITY_SOURCE_LABELS` Record mapping all 8 authority type strings to vocabulary labels: `gnd-*` → `'GND'`, `wikidata` → `'Wikidata'`, `geonames` → `'GeoNames'`, `aat` → `'AAT'`
- Added `uriToMarc0(uri): string | null` helper — detects GND URIs via `/d-nb\.info\/gnd\/(.+)/` regex and converts to `(DE-588){id}`; all other URIs (Wikidata, GeoNames, AAT) pass through unchanged
- Modified `downloadLIDO`: `descSets` map now reads `row.validation[f.name].reconciliation` and emits `<lido:conceptID lido:type="URI" lido:source="{vocabularyLabel}">` inside each `objectDescriptionSet`; actor block adds `<lido:actorID>` when Komponist field is reconciled; both use `AUTHORITY_SOURCE_LABELS` for source attribute
- Modified `downloadMARCXML`: `buildRecord` gains optional `row?: ResultRow` parameter; reads reconciliation URI for name field (`Zu- u. Vorname` or `Komponist`), converts via `uriToMarc0`, emits `<marc:subfield code="0">` if present; existing hardcoded `(DE-588)4113937-9` in f655 block unchanged
- Modified `downloadDublinCore`: added `xmlns:dcterms="http://purl.org/dc/terms/"` to root element; added `dcterms:identifier` emission after each mapped DC field with a URI; refactored rest/unmapped block from a joined string to per-field loop to support per-field `dcterms:identifier`
- `downloadEAD`, `downloadDarwinCore`, `downloadMETSMODS`, `checkValidationGate`, `downloadCSV`, `downloadJSON` are all byte-identical to before
- Extended `ValidationBadge`: added `Link2` import from lucide-react; added `reconTooltipOpen` state; renders `Link2` icon after status icon when `outcome.reconciliation` is non-null; tooltip shows label, authority type, and clickable new-tab URI link; uses `onMouseEnter/Leave` pattern consistent with existing corrected-status tooltip
- `ResultsTable.tsx` confirmed passing full `ValidationOutcome` (including reconciliation) to `ValidationBadge` — no changes needed

## Task Commits

1. **Task 1: useResultsExport.ts — helpers + URI injection in LIDO/MARC/DC** — `47f9769` (feat)
2. **Task 2: ValidationBadge reconciliation icon + ResultsTable verification** — `c9516c0` (feat)

## Files Created/Modified

- `apps/frontend/src/features/results/useResultsExport.ts` — 91 lines added (+3 helpers/constants, +LIDO conceptID/actorID, +MARCXML $0, +DC dcterms); 13 lines removed (rest block refactored to per-field loop)
- `apps/frontend/src/features/results/ValidationBadge.tsx` — 86 lines added (Link2 import, reconTooltipOpen state, reconciliation badge); 16 lines removed (return statement refactored)

## Decisions Made

- `lido:source` uses `AUTHORITY_SOURCE_LABELS[recon.authority]` (vocabulary label like `'GND'`) — NOT the field name. This is a LIDO schema correctness requirement: `lido:source` identifies the controlled vocabulary, not the field it appeared in.
- `buildRecord` gains an optional `row?: ResultRow` parameter rather than a required one — backward-compatible; all three call sites pass `row` but multi-entry branches that previously omitted it now pass it through correctly.
- DC unmapped fields refactored from a single joined `dc:description` string to a per-field loop — this changes the DC output slightly (multiple `<dc:description>` elements instead of one with semicolon-joined pairs) but is required to support per-field `dcterms:identifier`.
- `ValidationBadge` handles the edge case of `outcome.status === 'skipped'` or `outcome == null` by checking for `reconciliation` before returning null — allows reconciliation badge display even without a validation status.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] DC unmapped fields rest block refactored from joined string to per-field loop**
- **Found during:** Task 1 — DC implementation
- **Issue:** The original `rest` block joined all unmapped fields into a single `dc:description` string using semicolons. This made it impossible to emit `dcterms:identifier` for individual unmapped fields (the URI belongs to a specific field, not the combined string).
- **Fix:** Changed to a `for...of` loop over `unmappedFields` array; each field gets its own `dc:description` element followed by `dcterms:identifier` if a URI is present. Net effect: DC output for batches with unmapped fields will have multiple `<dc:description>` elements rather than one — still valid OAI-DC.
- **Files modified:** `apps/frontend/src/features/results/useResultsExport.ts`
- **Commit:** `47f9769`

## Self-Check: PASSED

- `apps/frontend/src/features/results/useResultsExport.ts` — exists, contains `getReconciliationUri`, `AUTHORITY_SOURCE_LABELS`, `uriToMarc0`, `DE-588`, `conceptID`, `actorID`, `dcterms`, `checkValidationGate`
- `apps/frontend/src/features/results/ValidationBadge.tsx` — exists, contains `Link2`, `reconciliation`, `reconTooltipOpen`
- Commit `47f9769` — exists (Task 1)
- Commit `c9516c0` — exists (Task 2)
- TypeScript `--noEmit` exit code 0 (no errors)

---
*Phase: 11-authority-reconciliation*
*Completed: 2026-05-18*
