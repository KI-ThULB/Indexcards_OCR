---
phase: 12-cross-phase-integration-fixes
researcher: claude-sonnet-4-6
researched: 2026-05-18
status: complete
fixes_confirmed: 4
wave_recommendation: two_waves
---

# Phase 12 Research: Cross-Phase Integration Fixes

**Objective:** Confirm exact file paths, line numbers, and code patterns for all four fixes specified in the milestone audit. No new design decisions — locked behavior was specified by Phases 08, 09, and 11.

---

## Fix 1 — template_service.py forwards authority_bindings (FR2)

### Confirmed bug location

**File:** `apps/backend/app/services/template_service.py`

**create_template()** — lines 41–52:
```python
def create_template(self, template_in: TemplateCreate) -> Template:
    templates = self._read_templates()
    new_template = Template(
        id=str(uuid.uuid4()),
        name=template_in.name,
        fields=template_in.fields,
        prompt_template=template_in.prompt_template,
        field_rules=template_in.field_rules,
        # BUG: authority_bindings from TemplateCreate is NOT passed here
    )
```

**update_template()** — lines 54–68 have branches for `name`, `fields`, `prompt_template`, `field_rules` but NO branch for `authority_bindings`.

### Confirmed schema support

Both `TemplateCreate` and `TemplateUpdate` in `apps/backend/app/models/schemas.py` already declare `authority_bindings: Optional[Dict[str, AuthorityBinding]] = None` (lines 100 and 107 respectively). The `Template` model also has the field (line 93). The problem is purely in the service layer — the constructor call and update branches are missing the field.

### Precedent fix (Phase 03.1 Plan 03 — identical pattern)

From `03.1-03-SUMMARY.md`:
- `create_template()` was missing `prompt_template=template_in.prompt_template` in the constructor call → **add it as a kwarg**
- `update_template()` was missing a branch → **add `if template_in.prompt_template is not None: templates[i]["prompt_template"] = template_in.prompt_template`**

### Exact fix

```python
# create_template() — add authority_bindings kwarg to Template(...)
new_template = Template(
    id=str(uuid.uuid4()),
    name=template_in.name,
    fields=template_in.fields,
    prompt_template=template_in.prompt_template,
    field_rules=template_in.field_rules,
    authority_bindings=template_in.authority_bindings,  # ADD THIS LINE
)

# update_template() — add is-not-None guard after field_rules branch (line ~65)
if template_in.field_rules is not None:
    templates[i]["field_rules"] = template_in.field_rules
if template_in.authority_bindings is not None:          # ADD THIS BLOCK
    templates[i]["authority_bindings"] = [
        (v.dict() if hasattr(v, 'dict') else v)
        for v in template_in.authority_bindings.values()  # wrong — see note below
    ]
```

**Important serialization note:** Unlike `create_template()` where the Template Pydantic model handles its own serialization via `.dict()`, `update_template()` works on the raw JSON dict. The `authority_bindings` values are `AuthorityBinding` Pydantic instances when parsed by FastAPI. They must be serialized to plain dicts before writing to the JSON store. The `create_batch()` endpoint in `batches.py` (lines 169–175) shows the correct pattern:
```python
ab = None
if batch_data.authority_bindings:
    ab = {
        k: (v.dict() if hasattr(v, "dict") else v)
        for k, v in batch_data.authority_bindings.items()
    }
```
Apply the same pattern in `update_template()`:
```python
if template_in.authority_bindings is not None:
    templates[i]["authority_bindings"] = {
        k: (v.dict() if hasattr(v, "dict") else v)
        for k, v in template_in.authority_bindings.items()
    }
```

For `create_template()`, passing `authority_bindings=template_in.authority_bindings` to the `Template()` constructor is safe because the `Template` Pydantic model serializes it properly when `.dict()` is called on line 50 (`templates.append(new_template.dict())`).

### Verification grep

```
grep authority_bindings apps/backend/app/services/template_service.py
```
Must show at least 2 occurrences (one in create_template, one in update_template).

---

## Fix 2 — CleanStep.handleCellReconciled(null) PATCH includes clear_reconciliation (FR4 + FR5)

### Confirmed bug location

**File:** `apps/frontend/src/features/clean/CleanStep.tsx`

**handleCellReconciled** — line 574–617:

The PATCH call at lines 611–616 is:
```ts
patchResult(batchId, pageFilename, {
  field,
  reconciliation: outcome ?? undefined,   // BUG: when outcome===null, this becomes undefined
  audit_entry: auditEntry,                // JSON.stringify drops undefined keys
}).catch(err => console.warn('[CleanStep] reconcile PATCH failed', err));
```

When `outcome === null` (No-match click → `CandidateDrawer` calls `handleCellReconciled(filename, field, null, 'reconciliation-no-match')`), `outcome ?? undefined` evaluates to `undefined`. `JSON.stringify` drops `undefined` values. The PATCH body becomes `{ field, audit_entry: ... }` with no reconciliation signal at all. The backend's reconciliation branch (`if patch.clear_reconciliation or patch.reconciliation is not None`) is never entered, so `checkpoint.json` retains any previously-set reconciliation.

**Key design decision note (from 11-04-SUMMARY.md key-decisions):**
> "handleCellReconciled omits reconciliation key on no-match (null outcome) — PATCH for no-match only sends audit_entry without reconciliation field to avoid overwriting with null vs absent"

This was the original intent, but it fails because the backend never clears the reconciliation. The fix is to use `clear_reconciliation: true` on null outcome per the Phase 11 backend convention — which is what the reconciliation-clearing-on-edit paths in `handleApplyTransform` and `executeClusterApply` correctly do.

### Confirmed clear_reconciliation support in batchesApi.ts

**File:** `apps/frontend/src/api/batchesApi.ts`, lines 125–141:
```ts
export async function patchResult(
  batchName: string,
  filename: string,
  patch: {
    field: string;
    value?: string | null;
    validation_status?: string | null;
    reconciliation?: ReconciliationOutcome;    // Phase 11: set a new outcome
    clear_reconciliation?: boolean;             // Phase 11: true → clear existing reconciliation
    audit_entry?: AuditEntry | null;
  }
): Promise<void>
```
`clear_reconciliation?: boolean` is already in the signature. No changes needed to `batchesApi.ts` for this fix.

### Confirmed backend handles clear_reconciliation

**File:** `apps/backend/app/api/api_v1/endpoints/batches.py`, line 255:
```python
if patch.clear_reconciliation or patch.reconciliation is not None:
    ...
    if patch.clear_reconciliation:
        row["validation"][patch.field]["reconciliation"] = None
    else:
        row["validation"][patch.field]["reconciliation"] = patch.reconciliation
```
Backend is already correct. Only the frontend PATCH payload construction needs fixing.

### Exact fix

Replace lines 611–616 in `CleanStep.tsx`:
```ts
// BEFORE (buggy):
patchResult(batchId, pageFilename, {
  field,
  reconciliation: outcome ?? undefined,
  audit_entry: auditEntry,
}).catch(...)

// AFTER (correct):
patchResult(batchId, pageFilename, {
  field,
  ...(outcome === null
    ? { clear_reconciliation: true }
    : { reconciliation: outcome }),
  audit_entry: auditEntry,
}).catch(...)
```

### Verification grep

```
grep clear_reconciliation apps/frontend/src/features/clean/CleanStep.tsx
```
Must show an occurrence inside `handleCellReconciled`.

---

## Fix 3 — CockpitBadge renders reconciliation Link2 icon (FR4 UX)

### Confirmed gap

**File:** `apps/frontend/src/features/verify/CockpitBadge.tsx`

CockpitBadge (141 lines) has:
- Import: `import { CheckCircle, CheckCircle2, XCircle, Wand2 } from 'lucide-react'` — **no `Link2`**
- State: `const [tooltipOpen, setTooltipOpen] = useState(false)` — **only one tooltip state; no `reconTooltipOpen`**
- No reconciliation rendering anywhere in the component

**File:** `apps/frontend/src/features/results/ValidationBadge.tsx`

ValidationBadge (182 lines) has the complete pattern to port:
- Line 2: `import { ..., Link2 } from 'lucide-react'`
- Line 15: `const [reconTooltipOpen, setReconTooltipOpen] = useState(false)`
- Lines 17–18: `const reconciliation = outcome?.reconciliation ?? null`
- Lines 20–52: early-return branch for skipped/null outcome that still renders Link2 if reconciliation is set
- Lines 150–179: reconciliation badge block after the status icon block, with `onMouseEnter/Leave` pattern and tooltip showing label / authority / clickable URI

### CockpitBadge tooltip pattern is compatible

Both `CockpitBadge` and `ValidationBadge` use `onMouseEnter/onMouseLeave` (not CSS group-hover) per the Phase 9 STATE.md key decision: corrected-status tooltip must stay open when cursor moves to Accept/Reject buttons. The pattern is identical. `CockpitBadge` uses `status !== 'corrected' && setTooltipOpen(false)` on mouse-leave for the primary icon — this should be preserved unchanged. The reconciliation badge adds a *second independent tooltip* with its own state (`reconTooltipOpen`), so there is no interference.

### Import difference to note

`ValidationBadge` imports `ValidationOutcome` from `'../../store/wizardStore'` (line 4). `CockpitBadge` imports from `'../../api/batchesApi'` (line 4). Both types are identical (wizardStore re-exports from batchesApi). No change needed to the import source — just add `Link2` to the existing lucide-react import line.

### Exact fix structure

1. Add `Link2` to lucide-react import in `CockpitBadge.tsx`
2. Add `const [reconTooltipOpen, setReconTooltipOpen] = useState(false);`
3. Add `const reconciliation = outcome?.reconciliation ?? null;` near the top (before the `if (!outcome || ...)` guard)
4. In the early-return guard (`if (!outcome || outcome.status === 'skipped') return null`):
   - Before returning null, check if reconciliation is set and render Link2-only span (same pattern as ValidationBadge lines 22–51)
5. In the main return, change from a bare `<span>` wrapping just status icon+tooltip to the two-sibling pattern: status icon span + reconciliation badge span (same as ValidationBadge lines 127–180)

The entire Link2 tooltip block from ValidationBadge (lines 151–179) ports directly with no modifications needed.

### Verification grep

```
grep -E "Link2|reconciliation" apps/frontend/src/features/verify/CockpitBadge.tsx
```
Must show both strings.

---

## Fix 4 — edited_data round-trip from PATCH back into ExtractionResult hydration (FR5)

### Confirmed data shape

The PATCH handler in `batches.py` (lines 241–243) writes `edited_data` as a **field on the result row**, not at the batch level:
```python
if "edited_data" not in row or row["edited_data"] is None:
    row["edited_data"] = {}
row["edited_data"][patch.field] = patch.value
```
Shape in checkpoint.json: `{ "filename": "...", "data": {...}, "edited_data": {"FieldName": "edited value"}, ... }`

This means `edited_data` is a **per-row field** with shape `Dict[str, str]` (field_name → edited_value). It is NOT a batch-level dict; it is a property ON each ExtractionResult row.

The GET `/results` endpoint returns checkpoint.json verbatim (via `read_checkpoint()`), so the raw API response DOES include `edited_data` on each row when present. The backend passes it through; the frontend simply has no type declaration for it and ignores it during hydration.

### Confirmed bug: ExtractionResult type lacks edited_data

**`apps/frontend/src/store/wizardStore.ts` (lines 26–34):**
```ts
export interface ExtractionResult {
  filename: string;
  batch: string;
  success: boolean;
  data: Record<string, string> | null;
  error?: string | null;
  duration: number;
  validation?: Record<string, ValidationOutcome> | null;
  // NO edited_data field — typed away
}
```

**`apps/backend/app/models/schemas.py` (lines 43–51):**
```python
class ExtractionResult(BaseModel):
    filename: str
    batch: str
    success: bool
    data: Optional[Dict[str, str]] = None
    error: Optional[str] = None
    duration: float
    validation: Optional[Dict[str, ValidationOutcome]] = None
    # NO edited_data field — Pydantic drops it on validation
```

**`packages/shared-types/schemas/batch.schema.json` `ExtractionResult` definition (lines 226–289):** Also lacks `edited_data`.

### Confirmed hydration bug in ResultsStep and VerifyStep

**`apps/frontend/src/features/results/ResultsStep.tsx` (lines 36–51):**
```ts
const existingEditsMap = new Map<string, Record<string, string>>(
  results.map((r) => [r.filename, r.editedData])
);

const rows: ResultRow[] = rawResults.map((r) => ({
  ...
  editedData: existingEditsMap.get(r.filename) ?? {},  // BUG: only reads from Zustand; ignores r.edited_data
  ...
}));
```

**`apps/frontend/src/features/verify/VerifyStep.tsx` (lines 30–44):** Identical pattern; same bug.

Since `ExtractionResult` doesn't declare `edited_data`, even if the API returns it, `r.edited_data` would be `undefined` in TypeScript's type system, and the hydration ignores it.

### Confirmed: batchesApi.ts is the only ExtractionResult copy for this fix

`apps/frontend/src/api/templatesApi.ts` imports `FieldRule` and `AuthorityBinding` from `batchesApi` but does NOT define or use `ExtractionResult`. `ExtractionResult` is owned by `wizardStore.ts` (the canonical TS type for frontend use) and exists in a slightly different form in `batchesApi.ts` — but looking at the code, `wizardStore.ts` actually defines its own `ExtractionResult` interface independently (not imported from `batchesApi.ts`). `batchesApi.ts` uses `import type { ExtractionResult } from '../store/wizardStore'` (line 4 of batchesApi.ts — confirmed above). So the TS type source of truth is `wizardStore.ts`.

### Confirmed: useResultsQuery select shim compatibility

`useResultsQuery` (batchesApi.ts lines 240–247) has `select: (data) => data.results` which extracts `ExtractionResult[]` from the API response. Adding `edited_data` to `ExtractionResult` simply makes the field visible to callers; the select shim passes through whatever the API returns. No change to the shim.

**Both ResultsStep and VerifyStep use `useResultsQuery`** (shimmed, returns `ExtractionResult[]` directly). Neither uses `useBatchResultsRawQuery`. The fix applies symmetrically to both.

### Exact fix — four locations

**A. `packages/shared-types/schemas/batch.schema.json` — add `edited_data` to ExtractionResult definition:**
```json
"edited_data": {
  "anyOf": [
    { "additionalProperties": { "type": "string" }, "type": "object" },
    { "type": "null" }
  ],
  "default": null,
  "title": "Edited Data",
  "description": "Curator field edits persisted by PATCH endpoint. Dict[field_name, edited_value]."
}
```
Insert this inside the `ExtractionResult.properties` block, after the `validation` block (around line 278, before the closing `}` of `properties`).

**B. `apps/backend/app/models/schemas.py` — add to ExtractionResult Pydantic model (after line 51):**
```python
edited_data: Optional[Dict[str, str]] = None   # Phase 9 PATCH writes curator edits here
```

**C. `apps/frontend/src/store/wizardStore.ts` — add to ExtractionResult interface (after line 33):**
```ts
edited_data?: Record<string, string> | null;   // Phase 9 PATCH writes; now round-tripped on reload
```

**D. ResultsStep.tsx and VerifyStep.tsx — update hydration to merge backend edited_data:**

Current hydration (both files, same pattern):
```ts
const existingEditsMap = new Map<string, Record<string, string>>(
  results.map((r) => [r.filename, r.editedData])
);
const rows: ResultRow[] = rawResults.map((r) => ({
  ...
  editedData: existingEditsMap.get(r.filename) ?? {},
  ...
}));
```

Fixed hydration (prefer backend if present, fall back to Zustand localStorage, then empty):
```ts
const existingEditsMap = new Map<string, Record<string, string>>(
  results.map((r) => [r.filename, r.editedData])
);
const rows: ResultRow[] = rawResults.map((r) => ({
  ...
  editedData: r.edited_data
    ? { ...existingEditsMap.get(r.filename), ...r.edited_data }
    : existingEditsMap.get(r.filename) ?? {},
  ...
}));
```

**Merge strategy:** backend `edited_data` takes precedence over Zustand localStorage for keys present in the backend. Keys only in Zustand (e.g., edits made during this session before the component re-mounts) are preserved. This means: backend wins on reload-from-scratch; Zustand fills in any in-session edits not yet persisted (e.g., if the PATCH debounce hasn't fired yet). The spread order `...existingEditsMap.get(r.filename), ...r.edited_data` achieves this.

The planner may also choose "backend always wins" (`editedData: r.edited_data ?? existingEditsMap.get(r.filename) ?? {}`) — simpler, but loses any in-flight edits. Either strategy closes the FR5 gap; the merge strategy is safer for the user.

### Note: batchesApi.ts does NOT need changes for Fix 4

`batchesApi.ts` imports `ExtractionResult` from `wizardStore.ts` (line 4: `import type { ExtractionResult } from '../store/wizardStore'`). Adding `edited_data` to `wizardStore.ts`'s interface propagates automatically. No separate change to `batchesApi.ts`.

### Verification greps

```
grep edited_data packages/shared-types/schemas/batch.schema.json
grep edited_data apps/backend/app/models/schemas.py
grep edited_data apps/frontend/src/store/wizardStore.ts
grep edited_data apps/frontend/src/features/results/ResultsStep.tsx
grep edited_data apps/frontend/src/features/verify/VerifyStep.tsx
```
All must return at least one match.

---

## Cross-Cutting Findings

### clear_reconciliation already in batchesApi.ts patchResult signature

Confirmed at `batchesApi.ts` lines 133–134:
```ts
reconciliation?: ReconciliationOutcome;    // Phase 11: set a new outcome (omit to leave alone)
clear_reconciliation?: boolean;             // Phase 11: true → clear existing reconciliation
```
Phase 11 Plan 01 added this. Fix 2 does not need to touch `batchesApi.ts`.

### useResultsQuery select shim — Phase 10 compatibility confirmed

`useResultsQuery` uses `select: (data) => data.results` to expose `ExtractionResult[]`. Adding `edited_data` to `ExtractionResult` is additive; existing callers get a new optional field with no breaking change. The Phase 10 shim introduced at the same time does not interfere.

### VerifyStep uses useResultsQuery (shimmed), confirmed

`apps/frontend/src/features/verify/VerifyStep.tsx` line 6: `import { useResultsQuery } from '../../api/batchesApi'`. Fix 4 hydration change applies to both ResultsStep (line 27) and VerifyStep (line 21) identically.

### templatesApi.ts — no changes needed for Fix 4

`templatesApi.ts` only declares `Template` (which has its own fields list) and re-exports `FieldRule`/`AuthorityBinding` from `batchesApi`. `ExtractionResult` is not referenced in `templatesApi.ts`. Fix 4 does not touch this file.

### edited_data shape is per-row, not batch-level

The PATCH handler writes `row["edited_data"][patch.field] = patch.value` — one dict per result row. `ExtractionResult` should declare `edited_data: Optional[Dict[str, str]] = None` (not a nested dict). This is the same shape as `data: Optional[Dict[str, str]]` already on `ExtractionResult`. Confirmed by reading the PATCH handler at lines 241–243 of `batches.py`.

---

## Wave Structure Recommendation

**Option B (Two Waves) is recommended** because Fix 4 requires a JSON Schema addition that should land before the frontend hydration fix reads the new field.

**Wave 1 (serial, 1 plan — 12-01):**
- Fix 1: `template_service.py` authority_bindings forwarding (backend-only, no schema change)
- Fix 4 schema foundation: add `edited_data` to `batch.schema.json` + `schemas.py` ExtractionResult

These two items share no file and can be in one plan. Wave 1 is "backend + schema" work. No frontend changes.

**Wave 2 (parallel, 3 plans — 12-02, 12-03, 12-04):**
- 12-02: Fix 2 — `CleanStep.handleCellReconciled` PATCH payload fix (1 line change in CleanStep.tsx)
- 12-03: Fix 3 — `CockpitBadge` reconciliation Link2 icon (port from ValidationBadge)
- 12-04: Fix 4 frontend — Add `edited_data` to `wizardStore.ts` ExtractionResult + hydration merge in ResultsStep and VerifyStep

All three Wave 2 plans touch disjoint files. 12-04 depends on Wave 1 schema landing first (so `edited_data` is in the Pydantic model before the frontend reads it), but 12-02 and 12-03 have no schema dependency and could technically run in Wave 1 as well. The two-wave structure is cleaner.

**Alternative: 4-plan single wave** if planner determines that schema changes don't create codegen dependencies (they don't in Phase 12's scope — no codegen pipeline is being re-adopted here; Phase 13 handles that). In that case, all 4 plans can run in parallel. Fix 4 frontend merge code would read `r.edited_data` which TypeScript would infer as `any` until the `wizardStore.ts` type is updated — but since all 4 plans run simultaneously, the type update is in the same wave. Acceptable if each plan handles its own scope without depending on peer plan outputs.

**Recommended wave structure for the plan:**

```
Wave 1: 12-01 (Fix 1 + Fix 4 schema foundation — backend only)
Wave 2: 12-02 (Fix 2 — CleanStep), 12-03 (Fix 3 — CockpitBadge), 12-04 (Fix 4 frontend)
```

This gives 2 waves, 4 plans total.

---

## File Map Summary

| Fix | File | Change Type |
|-----|------|-------------|
| Fix 1 | `apps/backend/app/services/template_service.py` | Add `authority_bindings` kwarg to `create_template()` constructor; add is-not-None guard in `update_template()` |
| Fix 2 | `apps/frontend/src/features/clean/CleanStep.tsx` | Replace 3-line PATCH payload object with conditional spread on `outcome === null` |
| Fix 3 | `apps/frontend/src/features/verify/CockpitBadge.tsx` | Add `Link2` import, `reconTooltipOpen` state, `reconciliation` extraction, and Link2 badge rendering (ported from ValidationBadge) |
| Fix 4a | `packages/shared-types/schemas/batch.schema.json` | Add `edited_data` property to `ExtractionResult` definition |
| Fix 4b | `apps/backend/app/models/schemas.py` | Add `edited_data: Optional[Dict[str, str]] = None` to `ExtractionResult` Pydantic model |
| Fix 4c | `apps/frontend/src/store/wizardStore.ts` | Add `edited_data?: Record<string, string> \| null` to `ExtractionResult` interface |
| Fix 4d | `apps/frontend/src/features/results/ResultsStep.tsx` | Hydration: merge `r.edited_data` into `editedData` (backend wins; Zustand fills in-session-only keys) |
| Fix 4e | `apps/frontend/src/features/verify/VerifyStep.tsx` | Same hydration merge as ResultsStep |

Total files changed: 7 (across 4 distinct fixes).

---

*Phase: 12-cross-phase-integration-fixes*
*Research completed: 2026-05-18*
