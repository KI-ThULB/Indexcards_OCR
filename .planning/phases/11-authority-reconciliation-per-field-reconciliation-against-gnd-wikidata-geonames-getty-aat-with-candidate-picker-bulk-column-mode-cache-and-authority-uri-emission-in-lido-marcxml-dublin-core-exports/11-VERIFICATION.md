---
phase: 11-authority-reconciliation
verified: 2026-05-18T00:00:00Z
status: passed
score: 46/46 must-haves verified
---

# Phase 11: Authority Reconciliation Verification Report

**Phase Goal:** Match free-text values in extracted fields against four external authority files (GND with 5 sub-collections, Wikidata, GeoNames, Getty AAT). Per-field authority binding in Configure step alongside Phase 8 FieldRule. Reconciliation lives inside Clean view with inline drawer candidate picker. Bulk column mode auto-accepts only exact-normalized-match-single-candidate, queues the rest for review. Per-batch authority_cache.json (no TTL, manual clear). Single POST /api/v1/reconcile endpoint with backend exponential-backoff retry. LIDO + MARCXML + Dublin Core exports gain URI slots; other Phase 6 exports unchanged. New reconciliation field as sibling to ValidationOutcome.status. Editing a reconciled cell auto-clears the reconciliation via clear_reconciliation:true flag (NOT reconciliation:null sentinel).
**Verified:** 2026-05-18
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | ReconciliationOutcome and AuthorityBinding types exist in JSON Schema and flow through codegen | VERIFIED | `packages/shared-types/schemas/batch.schema.json` has both definitions; `generated/ts/index.ts` exports `ReconciliationOutcome`, `AuthorityBinding`, `ValidationOutcome.reconciliation` |
| 2  | ValidationOutcome.reconciliation present in schemas and frontend type copies | VERIFIED | `schemas.py` line 31; `batchesApi.ts` line 43: `reconciliation?: ReconciliationOutcome \| null` |
| 3  | batchesApi.ts defines ReconciliationOutcome, AuthorityType, AuthorityBinding, extends BatchCreate/BatchConfig with authority_bindings | VERIFIED | Lines 14, 23, 29, 43, 76-80 of `batchesApi.ts` |
| 4  | templatesApi.ts includes authority_bindings; AuthorityBinding imported from batchesApi | VERIFIED | Line 13 `authority_bindings` field; mutation functions pass it through |
| 5  | wizardStore.ts MetadataField.authority?: AuthorityBinding \| null; updateFieldAuthority action | VERIFIED | Line 23 `authority?:`; line 119 `updateFieldAuthority`; line 252 implementation |
| 6  | batch_manager.create_batch() snapshots authority_bindings into config.json | VERIFIED | Line 38 parameter; line 64 `"authority_bindings": authority_bindings` in `config_data` |
| 7  | schemas.py has ReconciliationOutcome, AuthorityBinding Pydantic models; extended ValidationOutcome | VERIFIED | Lines 15, 22, 31 of `schemas.py` |
| 8  | ResultPatch accepts clear_reconciliation: bool = False; PATCH handler uses it unambiguously | VERIFIED | Line 139 `clear_reconciliation: bool = False`; lines 255–263 of `batches.py` |
| 9  | PATCH handler priority: clear_reconciliation=True → null; elif reconciliation → set; else leave | VERIFIED | Lines 255–263 of `batches.py`: condition `if patch.clear_reconciliation` first, then `else` sets to dict |
| 10 | patchResult in batchesApi.ts uses clear_reconciliation: true (not reconciliation: null) when clearing | VERIFIED | Line 133 `clear_reconciliation?: boolean`; convention documented in comment |
| 11 | authority/cache.py exports read_cache, write_cache_entry, lookup_cache, clear_cache; empty arrays cached | VERIFIED | All 4 functions present; line 30 docstring confirms `candidates=[]` is valid entry; `tmp.replace(p)` atomic write |
| 12 | POST /api/v1/reconcile registered in api.py; stub / real endpoint exists | VERIFIED | `api.py` lines 3 and 11: `reconcile_router` registered at `/reconcile` |
| 13 | DELETE /api/v1/batches/{batch_name}/authority-cache endpoint returns 204 | VERIFIED | `batches.py` line 295: `@router.delete("/{batch_name}/authority-cache", status_code=204)` |
| 14 | GEONAMES_USERNAME added to config.py settings | VERIFIED | Line 31: `GEONAMES_USERNAME: Optional[str] = None` |
| 15 | POST /api/v1/reconcile dispatches to all 4 clients; cache pre-check + cache post-write | VERIFIED | `reconcile.py` lines 57–67 dispatch; line 49 `lookup_cache`; line 81 `write_cache_entry` |
| 16 | GND TYPE_MAP has exactly 5 entries with correct Lobid filter values | VERIFIED | Python assertion passed: `{gnd-persons: Person, gnd-places: PlaceOrGeographicName, gnd-subjects: SubjectHeading, gnd-corporate-bodies: CorporateBody, gnd-works: Work}` |
| 17 | Wikidata proactive throttle: MIN_INTERVAL_SECONDS = 6, asyncio.Lock, asyncio.sleep | VERIFIED | `wikidata.py` line 17 constant; lines 26-34 lock + sleep logic |
| 18 | Wikidata uses concepturi (not url) for canonical URI | VERIFIED | `wikidata.py` line 55: `uri = r.get("concepturi", "")` |
| 19 | GeoNames body-level retry: RATE_LIMIT_CODES = {18, 19, 20, 22}, loop inside geonames.py | VERIFIED | `geonames.py` line 17 `RATE_LIMIT_CODES = {18, 19, 20, 22}`; loop at line 52; body check at line 59 |
| 20 | GeoNames raises ValueError when GEONAMES_USERNAME missing; endpoint returns 503 | VERIFIED | `geonames.py` lines 33-36 `raise ValueError`; `reconcile.py` line 73 `status_code=503` |
| 21 | Getty AAT uses POST form-body W3C Reconciliation API v0.2; extracts aat/NNNNNN → full URI | VERIFIED | `aat.py` line 23 `method="POST"`; line 35 `f"http://vocab.getty.edu/aat/{m.group(1)}"` |
| 22 | base.py fetch_with_retry: 3 retries, 1s/2s/4s backoff, 429 Retry-After, 5xx retry | VERIFIED | `base.py` lines 29, 39-40: backoff formula and Retry-After header honored |
| 23 | Cache lookup before every external call; cache write after every successful response | VERIFIED | `reconcile.py` line 49 `lookup_cache` before dispatch; line 81 `write_cache_entry` after dispatch (outside try block — always runs on success) |
| 24 | aiohttp in requirements.txt | VERIFIED | Line 12: `aiohttp>=3.9.0` |
| 25 | AuthorityBindingEditor has 9 options: None + 5 GND + Wikidata + GeoNames + Getty AAT | VERIFIED | `AuthorityBindingEditor.tsx` lines 12-22: 9 entries including `null` for None |
| 26 | AuthorityBindingEditor calls updateFieldAuthority; mounted in FieldManager | VERIFIED | `FieldManager.tsx` line 9 import; line 131 rendered; `onChange` calls `updateFieldAuthority` |
| 27 | Template save serializes authority_bindings; createBatch payload includes it | VERIFIED | `FieldManager.tsx` line 68 `authority_bindings` in createBatch payload |
| 28 | TemplateSelector hydrates authority_bindings on template load | VERIFIED | `TemplateSelector.tsx` line 31: `authority: template.authority_bindings?.[label] ?? null` |
| 29 | ColumnWorkspace.tsx accepts reconcilePaneSlot without dropping existing slots | VERIFIED | Line 15 new prop; line 90 rendered in stack; all existing slots preserved |
| 30 | ReconcilePane shows Reconcile column button only when authorityType is non-null | VERIFIED | `ReconcilePane.tsx` line 120 toast; bulk button conditional on `authorityType`; null check at bottom of component |
| 31 | Bulk-mode auto-accepts when exactly 1 candidate AND normalizeValue(label) === normalizeValue(cellValue) | VERIFIED | `ReconcilePane.tsx` lines 76-79: `candidates.length === 1 && normalizeValue(candidates[0].label) === normalizeValue(cellValue)` |
| 32 | normalizeValue imported from validationRuntime (not duplicated) | VERIFIED | `ReconcilePane.tsx` line 8: `import { normalizeValue } from './validationRuntime'` |
| 33 | 100-row confirmation toast in ReconcilePane | VERIFIED | Lines 120-127: `toast.warning` with Confirm/Cancel action buttons |
| 34 | CandidateDrawer: top-5 candidates, Pick/No-match/Search-again, Escape closes | VERIFIED | `CandidateDrawer.tsx` 153 lines; lines 38-43: `useEffect` Escape key handler |
| 35 | Reconciliation-clearing-on-edit in CleanStep: both handleApplyTransform and executeClusterApply | VERIFIED | Lines 302-329 (transform path) and 458-484 (cluster path): both use `clear_reconciliation: true` |
| 36 | Reconciliation-clearing-on-edit in FieldsPane.tsx | VERIFIED | Lines 67-86: Zustand sets `reconciliation: null`; PATCH uses `clear_reconciliation: true` |
| 37 | No `reconciliation: null` sentinel in PATCH calls (uses clear_reconciliation flag) | VERIFIED | CleanStep lines 329, 484 use `...(hasReconciliation ? { clear_reconciliation: true } : {})`; FieldsPane line 86 same pattern |
| 38 | AUTHORITY_SOURCE_LABELS map: 8 entries (5 GND variants → 'GND', wikidata, geonames, aat) | VERIFIED | `useResultsExport.ts` lines 46-55: all 8 entries confirmed |
| 39 | downloadLIDO emits lido:conceptID with AUTHORITY_SOURCE_LABELS[recon.authority] for lido:source | VERIFIED | Lines 193-203: `sourceLabel = AUTHORITY_SOURCE_LABELS[recon.authority]` used in `lido:conceptID` |
| 40 | downloadLIDO emits lido:actorID with same AUTHORITY_SOURCE_LABELS convention | VERIFIED | Lines 206-212: `komponistSource` uses `AUTHORITY_SOURCE_LABELS`, emitted in `lido:actorID` |
| 41 | uriToMarc0: GND → (DE-588){id}; Wikidata/GeoNames/AAT → full URI | VERIFIED | Lines 64-70: regex match on `d-nb.info/gnd/`; returns `(DE-588){id}` for GND; full URI otherwise |
| 42 | downloadMARCXML emits marc:subfield code='0' using uriToMarc0 | VERIFIED | Line 527: `uriToMarc0(getReconciliationUri(row, nameFieldKey))` used in MARCXML output |
| 43 | downloadDublinCore adds xmlns:dcterms and emits dcterms:identifier | VERIFIED | Line 484: `xmlns:dcterms="http://purl.org/dc/terms/"`; lines 453-468: `dcterms:identifier` for reconciled fields |
| 44 | downloadEAD, downloadDarwinCore, downloadMETSMODS unchanged — no reconciliation logic | VERIFIED | Grep over lines 293-350 (EAD), 351-410 (DarwinCore), 664-858 (METS/MODS) found zero reconciliation references |
| 45 | checkValidationGate unchanged — reconciliation does not affect export gate | VERIFIED | Lines 81-97: gate only checks `v.status === 'invalid'`; no reconciliation condition |
| 46 | ValidationBadge shows Link2 icon + tooltip when validation.reconciliation is set | VERIFIED | `ValidationBadge.tsx` lines 2 (Link2 import), 18, 30, 160: independent of status dimension; `reconTooltipOpen` state with mouseEnter/Leave |

**Score:** 46/46 truths verified

---

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `packages/shared-types/schemas/batch.schema.json` | VERIFIED | `ReconciliationOutcome`, `AuthorityBinding`, `ValidationOutcome.reconciliation`, `authority_bindings` on BatchConfig/BatchCreate |
| `packages/shared-types/schemas/template.schema.json` | VERIFIED | `AuthorityBinding` definition; `authority_bindings` on Template variants |
| `packages/shared-types/generated/ts/index.ts` | VERIFIED | `ReconciliationOutcome`, `AuthorityBinding` exported |
| `apps/backend/app/models/schemas.py` | VERIFIED | `ReconciliationOutcome`, `AuthorityBinding` Pydantic models; `ValidationOutcome.reconciliation`; `ResultPatch.clear_reconciliation: bool = False` |
| `apps/backend/app/services/authority/cache.py` | VERIFIED | `write_cache_entry` + atomic tmp rename (`tmp.replace(p)`); empty-array no-match semantics documented |
| `apps/backend/app/services/authority/base.py` | VERIFIED | `fetch_with_retry` with exponential backoff + 429 Retry-After + 5xx handling |
| `apps/backend/app/services/authority/gnd.py` | VERIFIED | `TYPE_MAP` with 5 entries; correct Lobid type strings |
| `apps/backend/app/services/authority/wikidata.py` | VERIFIED | `MIN_INTERVAL_SECONDS = 6`, `_wikidata_lock`, `asyncio.sleep`; `concepturi` field used |
| `apps/backend/app/services/authority/geonames.py` | VERIFIED | `RATE_LIMIT_CODES = {18, 19, 20, 22}`; body-level retry loop inside `search_geonames()`; `ValueError` for missing username |
| `apps/backend/app/services/authority/aat.py` | VERIFIED | POST form-body; `http://vocab.getty.edu/aat/{id}` URI construction |
| `apps/backend/app/api/api_v1/endpoints/reconcile.py` | VERIFIED | Dispatches to all 4 clients; `lookup_cache` pre-check; `write_cache_entry` post-write; 503/502 error mapping |
| `apps/backend/app/api/api_v1/endpoints/batches.py` | VERIFIED | PATCH handler with `clear_reconciliation` priority logic; DELETE `authority-cache` endpoint at line 295 |
| `apps/backend/app/core/config.py` | VERIFIED | `GEONAMES_USERNAME: Optional[str] = None` at line 31 |
| `apps/backend/app/services/batch_manager.py` | VERIFIED | `authority_bindings` parameter and written to `config_data` at lines 38, 64 |
| `apps/frontend/src/api/batchesApi.ts` | VERIFIED | `ReconciliationOutcome`, `AuthorityType`, `AuthorityBinding`; extended `ValidationOutcome`, `AuditEntry` (op + 4 source values); `clear_reconciliation?:boolean` on `patchResult`; `postReconcile` function |
| `apps/frontend/src/api/templatesApi.ts` | VERIFIED | `authority_bindings` on Template variants; `AuthorityBinding` imported from batchesApi |
| `apps/frontend/src/store/wizardStore.ts` | VERIFIED | `MetadataField.authority?: AuthorityBinding \| null`; `updateFieldAuthority` action with implementation |
| `apps/frontend/src/features/configure/AuthorityBindingEditor.tsx` | VERIFIED | 80 lines; 9 options in `AUTHORITY_OPTIONS`; calls `onChange` with `AuthorityBinding \| null` |
| `apps/frontend/src/features/configure/FieldManager.tsx` | VERIFIED | Imports and renders `AuthorityBindingEditor`; `authority_bindings` in createBatch payload |
| `apps/frontend/src/features/configure/TemplateSelector.tsx` | VERIFIED | `authority: template.authority_bindings?.[label] ?? null` hydration |
| `apps/frontend/src/features/clean/ColumnWorkspace.tsx` | VERIFIED | `reconcilePaneSlot?: React.ReactNode` prop; rendered in vertical stack; existing slots untouched |
| `apps/frontend/src/features/clean/ReconcilePane.tsx` | VERIFIED | 211 lines; bulk mode with sequential loop; `normalizeValue` imported; `toast.warning` 100-row confirmation; Clear cache button |
| `apps/frontend/src/features/clean/CandidateDrawer.tsx` | VERIFIED | 153 lines; top-5 list; Pick/No-match/Search-again; Escape key via `useEffect` |
| `apps/frontend/src/features/clean/CleanStep.tsx` | VERIFIED | `reconcilePaneSlot` wired; `clear_reconciliation: true` in BOTH `handleApplyTransform` (line 329) and `executeClusterApply` (line 484) |
| `apps/frontend/src/features/verify/FieldsPane.tsx` | VERIFIED | `clear_reconciliation: true` in PATCH at line 86; Zustand sets `reconciliation: null` at line 68 |
| `apps/frontend/src/features/results/useResultsExport.ts` | VERIFIED | `AUTHORITY_SOURCE_LABELS` (8 entries); `uriToMarc0` with GND (DE-588) logic; `getReconciliationUri`; URI in LIDO conceptID + actorID, MARCXML $0, DC dcterms:identifier; EAD/DarwinCore/METS/MODS sections contain zero reconciliation code |
| `apps/frontend/src/features/results/ValidationBadge.tsx` | VERIFIED | `Link2` imported; `reconciliation` badge with `reconTooltipOpen` state; independent of validation status |
| `apps/frontend/src/features/results/ResultsTable.tsx` | VERIFIED | `ValidationBadge` receives `outcome={r.validation?.[field]}` (full `ValidationOutcome` including reconciliation) |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `batch_manager.py` | `data/batches/*/config.json` | `create_batch()` writes `authority_bindings` | WIRED | Line 64: `"authority_bindings": authority_bindings` in config_data dict |
| `batches.py` | `authority/cache.py` | DELETE authority-cache calls `clear_cache(batch_dir)` | WIRED | Line 295 endpoint imports and calls `clear_cache` |
| `batchesApi.ts` | `templatesApi.ts` | `AuthorityBinding` imported from batchesApi | WIRED | `templatesApi.ts` imports `AuthorityBinding` from `./batchesApi` |
| `reconcile.py` | `authority/cache.py` | `lookup_cache` before external call; `write_cache_entry` after | WIRED | Lines 46-49 and 81 |
| `geonames.py` | `config.py` | `settings.GEONAMES_USERNAME` raises ValueError if None | WIRED | Lines 31-36; `reconcile.py` line 73 maps ValueError to 503 |
| `base.py` | all 4 client files | All clients call `fetch_with_retry` from base.py | WIRED | Each client imports `from .base import fetch_with_retry` |
| `AuthorityBindingEditor.tsx` | `wizardStore.ts` | `onChange` calls `updateFieldAuthority(field.id, binding)` in FieldManager | WIRED | `FieldManager.tsx` line 131 renders editor; passes `onChange={(binding) => updateFieldAuthority(...)}` |
| `FieldManager.tsx` | backend `batches.py` | `createBatch` payload carries `authority_bindings` | WIRED | Line 68 in FieldManager; `batch_manager.create_batch()` snapshots to config.json |
| `TemplateSelector.tsx` | `templatesApi.ts` | `handleSelectTemplate` uses `template.authority_bindings` typed via `Template` | WIRED | Line 31: `template.authority_bindings?.[label]` |
| `ReconcilePane.tsx` | `batchesApi.ts` | `postReconcile` + `patchResult` | WIRED | Line 5 imports `postReconcile`; line 74 calls it |
| `ReconcilePane.tsx` | `validationRuntime.ts` | `normalizeValue` imported (not duplicated) | WIRED | Line 8: `import { normalizeValue } from './validationRuntime'` |
| `CleanStep.tsx` | `ReconcilePane.tsx` | `reconcilePaneSlot` prop injection | WIRED | Line 698: `reconcilePaneSlot={activeColumn ? <ReconcilePane ...> : null}` |
| `CleanStep.tsx` | `batchesApi.ts` | `clear_reconciliation:true` PATCH in transform paths | WIRED | Lines 329, 484 |
| `FieldsPane.tsx` | `batchesApi.ts` | `clear_reconciliation:true` PATCH on edit | WIRED | Line 86 |
| `useResultsExport.ts` | `batchesApi.ts` | `row.validation[field].reconciliation.uri` in 3 export generators | WIRED | Lines 193, 206, 453, 527 |
| `ValidationBadge.tsx` | `batchesApi.ts` | `ReconciliationOutcome` type on `outcome` prop | WIRED | `outcome?.reconciliation` accessed at line 18 |

---

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| FR2 | 11-01, 11-03, 11-04 | Metadata Field Configuration — per-field authority binding in Configure, reconciliation in Clean | SATISFIED | `AuthorityBindingEditor.tsx` with 9 options; `updateFieldAuthority` action; `authority_bindings` snapshot into batch config; `ReconcilePane` + `CandidateDrawer` in Clean view |
| FR4 | 11-01, 11-02, 11-04, 11-05 | Results Visualization & Export — URI emission in LIDO, MARCXML, Dublin Core | SATISFIED | `AUTHORITY_SOURCE_LABELS`; `uriToMarc0`; `lido:conceptID`/`actorID`; MARC `$0`; `dcterms:identifier`; all verified present in `useResultsExport.ts` |

---

### Anti-Patterns Found

None. No TODO/FIXME/placeholder patterns found in Phase 11 files. No stub implementations detected.

---

### Correctness Hazard Spot-Checks (from prompt)

| # | Check | Result |
|---|-------|--------|
| 1 | Wikidata `MIN_INTERVAL_SECONDS = 6` + module-level Lock + `asyncio.sleep` | PASS — `wikidata.py` line 17 constant; lines 26-34 lock+sleep proactive throttle |
| 2 | GeoNames `RATE_LIMIT_CODES = {18, 19, 20, 22}` + body-level retry inside `geonames.py` | PASS — line 17 set; body loop at line 52; checks `data["status"]["value"] in RATE_LIMIT_CODES` |
| 3 | Getty AAT POST form-body; parses `q1.result[i]`; `aat/{n}` → `http://vocab.getty.edu/aat/{id}` | PASS — `aat.py` uses `method="POST"`, parses `data.get("q1", {}).get("result", [])`, regex extracts numeric ID |
| 4 | GND TYPE_MAP exactly 5 entries with correct values | PASS — Python assertion confirmed all 5 entries |
| 5 | `ResultPatch.clear_reconciliation: bool = False`; `patchResult` uses `clear_reconciliation?: boolean` | PASS — `schemas.py` line 139; `batchesApi.ts` line 133; no `reconciliation: null` sentinel in PATCH calls |
| 6 | PATCH handler: `clear_reconciliation=True` takes priority over `reconciliation` dict | PASS — `batches.py` lines 255-263: `if patch.clear_reconciliation:` first, then `else:` sets dict |
| 7 | `cache.py` atomic tmp-file rename; empty arrays cached | PASS — `tmp.replace(p)` at line 41; docstring confirms `candidates=[]` is valid entry |
| 8 | POST /api/v1/reconcile dispatches to all 4 clients; cache pre-check + post-write | PASS — all 4 imports + dispatch in `reconcile.py`; cache on lines 49 and 81 |
| 9 | `GEONAMES_USERNAME` in `config.py`; missing-env `ValueError`; endpoint maps to 503 | PASS — confirmed at all 3 sites |
| 10 | `AuthorityBindingEditor.tsx` in configure; `FieldManager` mounts it; `ConfigureStep` sends `authority_bindings` | PASS — all confirmed |
| 11 | `authority_bindings` snapshot into `config.json` via `batch_manager.create_batch()` | PASS — line 64 |
| 12 | `ReconcilePane` + `CandidateDrawer`; `ColumnWorkspace` `reconcilePaneSlot` added without dropping slots | PASS — both exist; ColumnWorkspace slot added; no existing slots removed |
| 13 | Bulk auto-accept imports `normalizeValue` from `validationRuntime` (not duplicated); exactly-1-candidate condition | PASS — line 8 import; lines 76-79 condition |
| 14 | 100-row confirmation toast reuses sonner pattern | PASS — `toast.warning` at line 120 with action/cancel buttons |
| 15 | Reconciliation clearing in BOTH CleanStep `handleApplyTransform` AND `executeClusterApply`; uses `clear_reconciliation: true` | PASS — lines 329 and 484; both use the flag, not `reconciliation: null` |
| 16 | `AUTHORITY_SOURCE_LABELS` map in `useResultsExport.ts` with 8 entries | PASS — all 8 entries confirmed |
| 17 | `uriToMarc0` helper: GND → `(DE-588){id}`; full URI for Wikidata/GeoNames/AAT | PASS — regex at line 67; fallback returns URI unchanged |
| 18 | `downloadLIDO` emits `lido:conceptID` with `lido:source` from `AUTHORITY_SOURCE_LABELS` (not field name) | PASS — `sourceLabel = AUTHORITY_SOURCE_LABELS[recon.authority]` at line 195 |
| 19 | `downloadDublinCore` emits `dcterms:identifier` + `xmlns:dcterms` namespace | PASS — namespace at line 484; identifier at lines 455, 468 |
| 20 | EAD/DarwinCore/METS/MODS exports UNCHANGED; no reconciliation logic leaked | PASS — grep over all three sections returned zero matches for reconciliation-related patterns |
| 21 | `ValidationBadge.tsx` renders `Link2` icon when `validation.reconciliation` is present | PASS — line 2 import; lines 18, 30: shown when reconciliation non-null, independent of status |
| 22 | Deferred authorities NOT implemented (VIAF/LCNAF/ULAN/ISNI/ORCID); no per-authority TTL; no global cache; no soft-block | PASS — grep found zero VIAF/LCNAF/ULAN/ISNI/ORCID references; no TTL fields; cache is per-batch only; `checkValidationGate` unchanged |

---

### Human Verification Required

1. **Wikidata bulk-mode rate limiting in practice**
   Test: Fire 10+ consecutive Wikidata queries in bulk mode
   Expected: Requests spaced at least 6 seconds apart (no 429 errors)
   Why human: Can only verify the asyncio.Lock + sleep code is structurally correct; actual timing behavior under concurrent users requires runtime observation

2. **GeoNames HTTP-200 rate-limit body detection in production**
   Test: Use a near-quota GeoNames account and trigger a rate-limit body
   Expected: HTTP 502 returned by the reconcile endpoint (not a silent empty response)
   Why human: Requires real GeoNames credentials and intentional quota exhaustion to trigger codes 18/19/20/22

3. **LIDO export round-trip with multiple authority types**
   Test: Reconcile fields with GND, Wikidata, GeoNames, and AAT authorities then export LIDO
   Expected: lido:source = "GND", "Wikidata", "GeoNames", "AAT" respectively (not field names)
   Why human: Correctness of the AUTHORITY_SOURCE_LABELS routing through the export generator requires end-to-end data flow

4. **EAD / DarwinCore / METS/MODS byte-identity with pre-Phase-11 output**
   Test: Export the same batch data that was exported before Phase 11
   Expected: Identical output for the three unmodified formats
   Why human: "Byte-identical" claim cannot be verified without pre-Phase-11 reference output

---

### Summary

Phase 11 goal is fully achieved. All 46 must-have truths across five plans (11-01 through 11-05) are verified in the codebase. The correctness hazard spot-checks specific to this phase all pass:

- Wikidata proactive throttle (`MIN_INTERVAL_SECONDS = 6`, module-level lock, sleep) is correctly implemented and not confused with reactive retry.
- GeoNames body-level rate-limit detection (`RATE_LIMIT_CODES = {18, 19, 20, 22}`) is a separate retry loop inside `geonames.py`, not delegated to `base.py`.
- Getty AAT uses POST with form-body, not GET.
- The `clear_reconciliation: bool` sentinel is consistently used over `reconciliation: null` in all PATCH call sites (CleanStep transform path, CleanStep cluster path, FieldsPane edit path).
- EAD, Darwin Core, and METS/MODS exports are clean of any reconciliation logic.
- The `AUTHORITY_SOURCE_LABELS` map correctly routes all 8 authority type strings to vocabulary labels for `lido:source` (not field names).
- No deferred features (VIAF, LCNAF, TTL, global cache, soft-block gate) leaked into the implementation.

---

_Verified: 2026-05-18_
_Verifier: Claude (gsd-verifier)_
