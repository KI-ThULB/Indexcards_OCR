# Phase 8: Validation Rules Engine - Research

**Researched:** 2026-05-13
**Domain:** Per-field rule engine, schema codegen, LLM corrector, backend OCR pipeline, React table badges
**Confidence:** HIGH (all findings drawn directly from live codebase reads)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Rule storage & lifecycle**
- Rules attached directly to the field definition in templates and batches — no separate "validation profile" abstraction. One rule (regex + vocabulary + corrector config) per field, optional.
- Rules execute inline during VLM extraction (in `OcrEngine.process_image` / `process_batch`) AND must be re-runnable on demand without re-extracting. New endpoint(s) needed to re-run validation against an existing batch's results.
- Rules are snapshotted at batch creation time, same pattern as the existing `prompt_template`. Old batches retain their original rule set; current template edits do not retroactively re-validate them.
- Validation outcome is stored inline alongside the value in the existing result row, e.g. `result.validation[field] = { status, rule_failed?, original_value?, rationale?, corrector_proposal? }`. Single source of truth — no separate validation report file. Frontend derives badges/filter state from this.

**LLM corrector — when, what, how**
- Corrector fires only when regex or vocabulary rule fails (not always, not manual-only). Cheap fallback for the hard cases.
- Default model is a cheap text-only model (e.g. Claude Haiku via OpenRouter, or a comparable small model). An opt-in image fallback sends the image to the configured extraction VLM when a rule's correction needs visual context.
- Corrections are always proposed, never silently auto-applied. The cell shows original value + proposed value + rationale; one-click accept/reject by the curator.
- Cost control: opt-in per batch + hard cap. Configure step has an "Enable LLM correction for this batch" toggle (off by default); when on, a per-batch correction-call cap (default ~100, configurable) prevents runaway spend.

**Rule library: regex presets + vocab matching**
- Configure-step rule editor offers a curated preset library + custom-regex escape hatch.
- v1 preset list: Year (YYYY), year range (YYYY–YYYY), ISO date (YYYY-MM-DD), German date (DD.MM.YYYY), GND/RKD/AAT/VIAF authority ID patterns, configurable prefix pattern, Required/non-empty.
- Closed-vocabulary matching: case-insensitive exact by default; fuzzy (Levenshtein) is opt-in per rule with configurable distance (default 1).
- Vocabulary normalization: trim whitespace + NFC + case-fold + diacritic-fold.

**Status surfacing in Results**
- Per-cell inline badge next to each value in the existing dl/dd extraction column. No separate validation column for v1.
- Filter chips above the Results table: All / Only invalid / Only auto-corrected (proposed) / Only verified-OK.
- Export gate: soft-block with confirmation dialog. CSV/JSON/XML export still works; a dialog appears if any row has open invalid status.
- Badge style: color + lucide-react icon + tooltip. Tooltip shows which rule failed, original VLM output, and proposed value for corrections.
- SummaryBanner.tsx should surface aggregate validation counts.

### Claude's Discretion
- Configure-step rule editor UX (where exactly the disclosure sits in `FieldManager`, animation, save-with-template ergonomics) — defer to existing FieldManager pattern.
- Exact corrector prompt construction (system prompt, JSON output schema, retry/fallback if corrector errors).
- Backend module boundaries within `apps/backend/app/services/validation/` (regex/vocab/corrector adapters, runner orchestration).
- Whether the per-batch cap is a soft warning at threshold + hard stop at cap, or a single hard stop.
- Fuzzy matching algorithm choice (Levenshtein vs damerau-levenshtein vs metaphone) — pick whatever standard library covers it.
- Choice of cheap default corrector model — pick best price/quality available via the existing provider abstraction (`_resolve_provider`).

### Deferred Ideas (OUT OF SCOPE)
- Configurable per-export-format gate (LIDO/MARCXML hard-block, CSV soft-block)
- Save user's custom regex as a personal preset
- Bulk-apply rule across fields of the same type
- Row-summary validation chip on each Results row
- Mixed apply mode (auto-apply for vocab snaps, propose for free-form regex)
- Always-on corrector
- Internationalization of error text
- Multi-pattern OR rules
- Configure-step rule editor: separate Validation tab vs inline disclosure
</user_constraints>

---

## Summary

Phase 8 adds a per-field validation rules engine to the existing Indexcards OCR system. The entire data path — from field definition through OCR extraction to results export — must be extended to carry rule definitions and validation outcomes. The project already has a working pattern for this: `prompt_template` was added in Phase 03.1 through exactly five files (JSON Schema → TypeScript codegen → Pydantic schemas → batch_manager → ocr_engine), and validation rules follow the exact same path.

The backend integration point is clean: validation logic slots in immediately after `_call_vlm_api_resilient` returns in `_process_card_sync`, before the result dict is assembled. A new `apps/backend/app/services/validation/` module handles regex/vocabulary/corrector logic without touching OcrEngine internals. A new `/revalidate` endpoint mirrors the existing `/retry` pattern and re-runs validation on a completed batch's `checkpoint.json` in place.

The frontend changes are surgical: `FieldManager.tsx` gains a per-field disclosure panel, `ResultsTable.tsx` wraps each `<dd>` value with a badge, `SummaryBanner.tsx` adds validation count stats, and `useResultsExport.ts` adds a pre-download check with a `sonner` confirmation dialog. The Zustand store needs a `fieldRules` map and a `correctorEnabled`/`correctorCap` toggle — both following the `partialize`-excluded results pattern to avoid localStorage bloat.

**Primary recommendation:** Follow the `prompt_template` reference pattern faithfully. Schema-first: add `FieldRule`, `ValidationOutcome`, and `BatchValidationConfig` to `packages/shared-types/schemas/`, regenerate, then wire top-down through models → services → endpoints → frontend.

---

## Standard Stack

### Core (already in project, no new installs)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `re` | stdlib | Regex matching in validation engine | Already imported in ocr_engine.py |
| Python `unicodedata` | stdlib | NFC normalize + casefold + diacritic-fold for vocab normalization | Zero-dep, canonical |
| `requests` | existing | LLM corrector HTTP call via OpenRouter API | Same client already used by OcrEngine |
| `lucide-react` | ^0.575.0 | Badge icons (CheckCircle, XCircle, AlertCircle, Wand) | Already used throughout ResultsTable |
| `sonner` | ^2.0.7 | Confirmation dialog/toast for export gate | Already used in FieldManager, batchesApi |
| `@tanstack/react-table` | ^8.21.3 | Filter state for filter chips above table | Already used in ResultsTable |

### Supporting (new installs needed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `rapidfuzz` | latest (^3.x) | Levenshtein fuzzy matching for opt-in vocabulary rule | Pure-Python Levenshtein is slower; rapidfuzz has C ext and Python fallback; no GPL license issue. No existing Levenshtein dep found in requirements.txt. |

**PLAN MUST DO:** Add `rapidfuzz` to `apps/backend/requirements.txt`. Use `rapidfuzz.distance.Levenshtein.distance(a, b)` for the opt-in fuzzy vocab match. No JS fuzzy library needed — normalization and matching are entirely server-side.

**Installation:**
```bash
# Backend
echo "rapidfuzz" >> apps/backend/requirements.txt
uv pip install rapidfuzz  # or pip install rapidfuzz
```

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| rapidfuzz | python-Levenshtein | python-Levenshtein is a thin C wrapper with less convenient API; rapidfuzz is the current community standard, actively maintained |
| rapidfuzz | jellyfish | jellyfish adds metaphone/soundex but overkill; no advantage for simple edit-distance matching of authority IDs and dates |

---

## Architecture Patterns

### 1. Schema-First Extension Pattern (from prompt_template, Phase 03.1)

**What:** All data model changes start in `packages/shared-types/schemas/*.schema.json`, then `turbo generate` regenerates `generated/ts/index.ts` (TypeScript) and `generated/py/*.py` (Pydantic). Hand-written `apps/backend/app/models/schemas.py` is the authoritative Pydantic source for the backend API layer — it is NOT auto-generated.

**Confirmed from codebase:**
- `packages/shared-types/schemas/batch.schema.json` — contains `BatchConfig`, `BatchCreate`, `ExtractionResult`
- `packages/shared-types/schemas/template.schema.json` — contains `Template`, `TemplateCreate`, `TemplateUpdate`
- `apps/backend/app/models/schemas.py` — manually maintained Pydantic models (NOT the generated ones in `generated/py/`)
- `apps/frontend/src/api/batchesApi.ts` — has its own local TypeScript interface copies (e.g., `BatchCreate`) rather than importing from shared-types directly

**PLAN MUST DO:** Add the following new schema definitions to the appropriate `.schema.json` files:

**`packages/shared-types/schemas/template.schema.json`** — add `FieldRule` definition:
```json
"FieldRule": {
  "type": "object",
  "properties": {
    "preset_id":    { "anyOf": [{"type": "string"}, {"type": "null"}], "default": null },
    "pattern":      { "anyOf": [{"type": "string"}, {"type": "null"}], "default": null,
                      "description": "Regex pattern string. Null means no regex rule." },
    "vocabulary":   { "anyOf": [{"items":{"type":"string"},"type":"array"}, {"type":"null"}], "default": null,
                      "description": "Closed vocabulary list. Null means no vocab rule." },
    "fuzzy_distance":{ "anyOf": [{"type":"integer"}, {"type":"null"}], "default": null,
                      "description": "Levenshtein distance threshold for opt-in fuzzy vocab match. Null = exact." },
    "corrector_enabled": { "type": "boolean", "default": false,
                      "description": "Whether to invoke LLM corrector on rule failure for this field." }
  },
  "title": "FieldRule"
}
```

**`packages/shared-types/schemas/template.schema.json`** — extend `Template`, `TemplateCreate`, `TemplateUpdate` with:
```json
"field_rules": {
  "anyOf": [
    { "additionalProperties": { "$ref": "#/definitions/FieldRule" }, "type": "object" },
    { "type": "null" }
  ],
  "default": null,
  "title": "Field Rules",
  "description": "Map of field_label -> FieldRule. Null means no validation rules."
}
```

**`packages/shared-types/schemas/batch.schema.json`** — extend `BatchConfig` and `BatchCreate` with the same `field_rules` property, plus:
```json
"corrector_enabled": { "type": "boolean", "default": false },
"corrector_cap":     { "anyOf": [{"type":"integer"}, {"type":"null"}], "default": 100 }
```

**`packages/shared-types/schemas/batch.schema.json`** — add `ValidationOutcome` definition:
```json
"ValidationOutcome": {
  "type": "object",
  "properties": {
    "status":           { "type": "string", "enum": ["valid","invalid","corrected","skipped"],
                          "description": "valid=passed, invalid=failed no corrector, corrected=proposal pending, skipped=no rule" },
    "rule_failed":      { "anyOf": [{"type":"string"}, {"type":"null"}], "default": null,
                          "description": "Which rule type failed: 'regex', 'vocabulary', null" },
    "original_value":   { "anyOf": [{"type":"string"}, {"type":"null"}], "default": null },
    "rationale":        { "anyOf": [{"type":"string"}, {"type":"null"}], "default": null },
    "corrector_proposal":{ "anyOf": [{"type":"string"}, {"type":"null"}], "default": null }
  },
  "required": ["status"],
  "title": "ValidationOutcome"
}
```

**`packages/shared-types/schemas/batch.schema.json`** — extend `ExtractionResult` with:
```json
"validation": {
  "anyOf": [
    { "additionalProperties": { "$ref": "#/definitions/ValidationOutcome" }, "type": "object" },
    { "type": "null" }
  ],
  "default": null,
  "title": "Validation",
  "description": "Per-field validation outcomes. Null means validation not run."
}
```

After schema edits: run `turbo generate` from repo root. The generated `ts/index.ts` will update automatically. Then mirror changes in `apps/backend/app/models/schemas.py` manually (same pattern as existing Pydantic models).

**PLAN MUST AVOID:** Editing `generated/ts/index.ts` or `generated/py/*.py` directly. These are auto-generated.

**PLAN MUST AVOID:** Assuming `batchesApi.ts` imports from shared-types — it has its own local type copies. Update `batchesApi.ts` manually to add `field_rules`, `corrector_enabled`, `corrector_cap` to `BatchCreate` interface.

---

### 2. Batch Config Snapshot Pattern (prompt_template reference)

**Confirmed from codebase — exact code path to replicate:**

`apps/backend/app/services/batch_manager.py`, line 29-55:
```python
def create_batch(self, custom_name, session_id, fields=None, prompt_template=None):
    config_data = {
        "custom_name": custom_name,
        "fields": fields or settings.FIELD_KEYS,
        "prompt_template": prompt_template,   # ← snapshotted here
        "created_at": datetime.now().isoformat()
    }
    with open(batch_path / "config.json", "w") as f:
        json.dump(config_data, f, indent=2)
```

`apps/backend/app/api/api_v1/endpoints/batches.py`, line 25-47 (`run_ocr_task`):
```python
if config_path.exists():
    with open(config_path, "r") as f:
        config = json.load(f)
        fields = config.get("fields")
        prompt_template = config.get("prompt_template")   # ← read via config.get()
        provider = config.get("provider", "openrouter")
        model = config.get("model")
```

**PLAN MUST DO for rules:** Mirror exactly — add `field_rules`, `corrector_enabled`, `corrector_cap` to `create_batch()` signature and `config_data` dict, then read them in `run_ocr_task` via `config.get("field_rules")`, `config.get("corrector_enabled", False)`, `config.get("corrector_cap", 100)`.

**PLAN MUST DO:** Pass `field_rules`, `corrector_enabled`, `corrector_cap` through `process_batch` → `_process_card_sync` as parameters (same as existing `prompt_template`, `api_endpoint`, `model_name`, `api_key` pattern at lines 253-330 of ocr_engine.py). Do NOT use global state or mutate `settings`.

---

### 3. OCR Engine Integration Point

**Confirmed location in `apps/backend/app/services/ocr_engine.py`:**

The exact insertion point is in `_process_card_sync` (lines 252-330) after `data, error = self._call_vlm_api_resilient(...)` returns and `data` is confirmed non-error, before the result dict is assembled (line 311 return block).

Current flow (line 267-322):
```python
data, error = self._call_vlm_api_resilient(...)  # ← VLM call
# ... handle error ...
# ... handle multi-entry (list) case ...
# Enrich metadata
data["Datei"] = filename
data["Batch"] = batch_name
ok, v_errors = self._validate_extraction(data)   # ← existing basic validation
return { "filename": ..., "data": data, "validation_errors": ... }
```

**New validation engine hooks in after line 309 (`data["Batch"] = batch_name`) and before the final `return` on line 311:**
```python
# NEW: run per-field validation rules if configured
validation_outcomes = {}
if field_rules:
    from app.services.validation.runner import run_validation
    validation_outcomes = run_validation(
        data=data,
        field_rules=field_rules,
        corrector_enabled=corrector_enabled,
        corrector_cap_state=corrector_cap_state,  # mutable dict {"used": N, "cap": M}
        image_path=image_path,                     # for opt-in image fallback
        api_endpoint=api_endpoint,
        api_key=api_key,
    )
return {
    ...
    "validation": validation_outcomes,   # NEW field
}
```

**PLAN MUST DO:** Create `apps/backend/app/services/validation/` package with:
- `__init__.py`
- `runner.py` — orchestrates regex/vocab/corrector per field
- `regex_rules.py` — compiled regex matching, preset patterns
- `vocab_rules.py` — vocabulary normalization + exact/fuzzy matching (using rapidfuzz)
- `corrector.py` — LLM corrector via `requests` (same client as OcrEngine)

**PLAN MUST DO:** The `_process_card_sync` method signature must gain `field_rules`, `corrector_enabled`, `corrector_cap_state` parameters. `process_batch` must accept and thread them through the `ThreadPoolExecutor` `executor.submit(...)` call (line 401-407).

**Note on threading:** `_process_card_sync` runs inside `ThreadPoolExecutor` workers. The `corrector_cap_state` dict (`{"used": N, "cap": M}`) must use a `threading.Lock` for thread-safe increment. The existing cancellation pattern uses `threading.Event` (not asyncio.Event) — same pattern is safe here.

---

### 4. `_resolve_provider` Pattern for LLM Corrector

**Confirmed from `apps/backend/app/api/api_v1/endpoints/batches.py`, lines 18-22:**
```python
def _resolve_provider(provider: str, model: Optional[str] = None):
    if provider == "ollama":
        return settings.OLLAMA_API_ENDPOINT, model or settings.OLLAMA_MODEL_NAME, settings.OLLAMA_API_KEY
    return settings.API_ENDPOINT, model or settings.MODEL_NAME, settings.OPENROUTER_API_KEY
```

The corrector is a text-only chat completion (no image). It should use the OpenRouter endpoint with a cheap text model. The corrector call is simpler than the VLM call — no base64 image, just text messages.

**PLAN MUST DO:** In `corrector.py`, call the corrector directly via the existing `requests.Session` pattern (same as `_call_vlm_api_resilient`). The corrector endpoint is always `settings.API_ENDPOINT` (OpenRouter) regardless of the batch's extraction provider. This avoids mutating any state and does not touch the existing `_resolve_provider()` function.

Corrector call shape:
```python
payload = {
    "model": corrector_model,   # e.g. "anthropic/claude-haiku-4" or similar cheap model
    "messages": [
        {"role": "system", "content": CORRECTOR_SYSTEM_PROMPT},
        {"role": "user", "content": f"Field: {field_name}\nValue: {raw_value}\nRule: {rule_description}\nPropose a correction as JSON: {{\"proposal\": \"...\", \"rationale\": \"...\"}}"}
    ],
    "max_tokens": 256,
    "temperature": 0.0,
}
```

No image in the corrector call unless `image_fallback=True` is set per rule — in that case, include the base64-encoded image in the user message, using the batch's configured VLM endpoint/model instead.

**PLAN MUST DO:** Choose corrector model from a new config constant (not from `PROVIDER_DEFAULT_MODELS` which is frontend-only). Recommended: `anthropic/claude-haiku-4` (text-only, cheap) via OpenRouter. Add `CORRECTOR_MODEL_NAME: str = "anthropic/claude-haiku-4"` to `apps/backend/app/core/config.py`.

---

### 5. Re-runnable Validation Endpoint

**Existing endpoint pattern to replicate (from `batches.py`):**

The `/retry` endpoint pattern (line 273-290) moves files from `_errors/` back and re-runs OCR. The `/revalidate` endpoint is simpler — it reads the existing `checkpoint.json`, runs validation rules from `config.json`, and updates results in place.

**Proposed new endpoint:**
```
POST /api/v1/batches/{batch_name}/revalidate
```

Implementation:
1. Read `batch_path / "config.json"` → extract `field_rules`, `corrector_enabled`, `corrector_cap`
2. Read `batch_path / "checkpoint.json"` → list of result dicts
3. For each result with `success=True`, run `run_validation(data=result["data"], ...)`
4. Update `result["validation"]` in place
5. Write updated list back to `checkpoint.json`
6. Return `{"message": "Revalidation complete", "validated_count": N}`

**PLAN MUST DO:** Place this endpoint before `/{batch_name}` in `batches.py` (same pattern as `/history` before `/{batch_name}` — see STATE.md key decision on FastAPI route ordering). Register as `@router.post("/{batch_name}/revalidate")`.

This endpoint runs synchronously (not as a BackgroundTask) because validation is fast (regex/vocab) and corrector calls are bounded by cap. For large batches with LLM corrector enabled, consider making it a background task — planner's discretion.

---

### 6. Frontend Configure Step — FieldManager Extension

**Current `FieldManager.tsx` structure (lines 1-143 confirmed):**

Each field row (line 95-111) currently renders:
```tsx
<div className="flex items-center justify-between px-6 py-4 ...">
  <div className="flex items-center gap-3">
    <Tag icon />
    <span>{field.label}</span>
  </div>
  <Trash2 button />
</div>
```

**PLAN MUST DO:** Extend `MetadataField` interface in `wizardStore.ts` to add an optional `rule` property:
```typescript
export interface FieldRule {
  preset_id?: string | null;
  pattern?: string | null;
  vocabulary?: string[] | null;
  fuzzy_distance?: number | null;
  corrector_enabled?: boolean;
}

export interface MetadataField {
  id: string;
  label: string;
  type: 'text' | 'date' | 'number' | 'enum';
  options?: string[];
  rule?: FieldRule | null;   // NEW
}
```

**PLAN MUST DO:** Add `correctorEnabled: boolean` and `correctorCap: number` to `WizardState` and `initialState`. Wire through `BatchCreate` payload in `ConfigureStep.handleStartExtraction`.

**PLAN MUST DO:** Add a collapsible `<ValidationRuleEditor>` disclosure inside each field row in `FieldManager.tsx`. Pattern follows `PromptTemplateEditor.tsx`'s `collapsed` state. The disclosure contains:
- A preset picker (dropdown or radio buttons from a `VALIDATION_PRESETS` constant)
- A custom regex text input (shown when "Custom Regex" preset selected)
- A vocabulary textarea (shown when "Vocabulary" mode)
- A fuzzy distance numeric input (shown when vocabulary mode + fuzzy enabled)
- A corrector toggle (per-field override)

**PLAN MUST DO:** Add an "Enable LLM Correction" toggle + cap input in the ConfigureStep "How to extract" card (Card 2), next to PromptTemplateEditor. This is the batch-level corrector control.

**PLAN MUST AVOID:** Adding `fieldRules` or `correctorEnabled` to the Zustand `partialize` keys. STATE.md explicitly notes "Zustand partialize excludes processingState/results" to prevent localStorage regression. Field rules are small but still should be scoped consistently — they ARE safe to persist since they're configuration, not results. Include them in `partialize` alongside `fields`.

---

### 7. Frontend Results Step — Badges and Filter Chips

**Current `ResultsTable.tsx` extraction column (lines 255-283):**
```tsx
columnHelper.display({
  id: 'extraction',
  cell: ({ row }) => (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
      {visibleFields.map((field) => (
        <React.Fragment key={field}>
          <dt className="font-mono text-xs ...">{field}</dt>
          <dd className="py-0.5">
            <EditableCell value={displayValue} ... />
          </dd>
        </React.Fragment>
      ))}
    </dl>
  ),
})
```

**PLAN MUST DO:** Wrap the `<dd>` content to add a badge inline:
```tsx
<dd className="py-0.5 flex items-start gap-1.5">
  <ValidationBadge outcome={r.validation?.[field]} />
  <EditableCell value={displayValue} ... />
</dd>
```

`ValidationBadge` is a new small component:
- `status='valid'` → green CheckCircle, tooltip "Passed rule"
- `status='invalid'` → red XCircle, tooltip shows `rule_failed` + `original_value`
- `status='corrected'` → amber Wand icon, tooltip shows proposal + rationale + Accept/Reject buttons
- `status='skipped'` or no outcome → renders null (no badge)

**PLAN MUST DO:** Pass `validation` map from `ResultRow` through `ResultsTable` props. This requires:
1. Extending `ResultRow` interface in `wizardStore.ts` with `validation?: Record<string, ValidationOutcome> | null`
2. Extending `ExtractionResult` interface in `batchesApi.ts` with `validation?: ...`
3. Updating `ResultsStep.tsx` hydration (lines 38-45) to include `validation: r.validation ?? null`

**PLAN MUST DO:** Add filter chips above the ResultsTable in `ResultsStep.tsx`:
```tsx
type ValidationFilter = 'all' | 'invalid' | 'corrected' | 'valid';
const [validationFilter, setValidationFilter] = useState<ValidationFilter>('all');
```

Filter chips render as `<button>` elements with Parchment-theme styling (rounded, sepia border) — same as existing category chips in other parts of the UI. Pass `validationFilter` into `ResultsTable` or filter the `results` array before passing.

**PLAN MUST DO:** Update `SummaryBanner.tsx` props and rendering to add validation aggregate stats:
- Add `invalidCount`, `correctedCount` props to `SummaryBannerProps`
- Add two new stat columns after "Errors": "Invalid" (amber) and "Proposals" (blue/sepia)
- Compute these in `ResultsStep.tsx` from `results` array

---

### 8. Export Gate (Soft-Block)

**Current `useResultsExport.ts` structure (lines 30-759):** Each download function (`downloadCSV`, `downloadJSON`, etc.) calls `triggerDownload(...)` directly with no pre-check.

**PLAN MUST DO:** Add a guard function at the top of `useResultsExport`:
```typescript
function checkValidationGate(
  results: ResultRow[],
  onProceed: () => void,
  onCancel?: () => void
): void {
  const invalidCount = results.filter(r =>
    r.validation && Object.values(r.validation).some(v => v.status === 'invalid')
  ).length;
  
  if (invalidCount === 0) { onProceed(); return; }

  // Use sonner's `toast` with action buttons (soft-block pattern)
  toast.warning(`${invalidCount} row(s) have validation issues.`, {
    action: { label: 'Export anyway', onClick: onProceed },
    cancel: { label: 'Cancel', onClick: () => onCancel?.() },
    duration: 10000,
  });
}
```

Then wrap each download function:
```typescript
const downloadCSV = () => checkValidationGate(results, () => { /* existing CSV logic */ });
```

**Confirmed `sonner` version:** `^2.0.7` — the `toast()` with `action` + `cancel` pattern is used in `FieldManager.tsx` (lines 32-44). Same pattern applies here.

**PLAN MUST AVOID:** A modal dialog. The existing codebase uses sonner toasts exclusively for confirmations. No dialog component exists; introducing one would require a new dependency or inline implementation.

---

### 9. Vocabulary Normalization in Python

**PLAN MUST DO:** Implement in `apps/backend/app/services/validation/vocab_rules.py`:
```python
import unicodedata

def normalize_value(value: str) -> str:
    """Trim, NFC, casefold, diacritic-fold."""
    value = value.strip()
    # NFC normalize first (canonical decomposition → recomposition)
    value = unicodedata.normalize('NFC', value)
    # casefold (German-aware lowercasing: ß → ss, Ü → ü → u, etc.)
    value = value.casefold()
    # diacritic-fold: decompose to NFD then strip combining marks
    value = unicodedata.normalize('NFD', value)
    value = ''.join(c for c in value if unicodedata.category(c) != 'Mn')
    # Final NFC
    return unicodedata.normalize('NFC', value)

def matches_vocabulary(value: str, vocabulary: list[str], fuzzy_distance: int | None = None) -> bool:
    normalized_value = normalize_value(value)
    normalized_vocab = [normalize_value(v) for v in vocabulary]
    
    if normalized_value in normalized_vocab:
        return True
    
    if fuzzy_distance is not None and fuzzy_distance > 0:
        from rapidfuzz.distance import Levenshtein
        return any(
            Levenshtein.distance(normalized_value, v) <= fuzzy_distance
            for v in normalized_vocab
        )
    
    return False
```

This matches the user decision: `"Goethe"`, `" goethe "`, `"GÖTHE"`, `"GOETHE"` all normalize to `"goethe"` and match.

---

### 10. Regex Preset Library Shape

**PLAN MUST DO:** Create `apps/backend/app/services/validation/presets.py` (Python) with VALIDATION_PRESETS constant, and `apps/frontend/src/features/configure/validationPresets.ts` (TypeScript mirror):

```python
# presets.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class ValidationPreset:
    id: str
    label: str
    pattern: str
    description: str
    has_prefix_input: bool = False  # True → user supplies prefix, pattern = f"^{prefix}\\d+"

VALIDATION_PRESETS: list[ValidationPreset] = [
    ValidationPreset("required",     "Required / Non-empty",   r"^.+$",            "Field must not be empty"),
    ValidationPreset("year",         "Year (YYYY)",            r"^\d{4}$",          "Four-digit year"),
    ValidationPreset("year_range",   "Year Range (YYYY–YYYY)", r"^\d{4}[–\-]\d{4}$","Year range with dash or en-dash"),
    ValidationPreset("iso_date",     "ISO Date (YYYY-MM-DD)",  r"^\d{4}-\d{2}-\d{2}$", "ISO 8601 date"),
    ValidationPreset("german_date",  "German Date (DD.MM.YYYY)",r"^\d{2}\.\d{2}\.\d{4}$","German date format"),
    ValidationPreset("gnd_id",       "GND Authority ID",       r"^(DE-588)?[0-9X]+$","GND identifier"),
    ValidationPreset("rkd_id",       "RKD Authority ID",       r"^\d+$",            "RKD numeric identifier"),
    ValidationPreset("aat_id",       "Getty AAT ID",           r"^aat:\d+$",        "AAT concept identifier"),
    ValidationPreset("viaf_id",      "VIAF ID",                r"^\d+$",            "VIAF numeric identifier"),
    ValidationPreset("prefix",       "Prefix Pattern",         r"",                 "Custom prefix + digits",   True),
    ValidationPreset("custom",       "Custom Regex",           r"",                 "User-supplied regex pattern"),
    ValidationPreset("vocabulary",   "Closed Vocabulary",      r"",                 "Match against a list of allowed values"),
]
```

**Note on loading pattern:** This is a Python constant (not a JSON file) since it's backend-only for validation. The frontend TypeScript mirror in `validationPresets.ts` has the same list as a `const` array — same approach as `PROVIDER_DEFAULT_MODELS` in `wizardStore.ts` (line 69-72).

**PLAN MUST AVOID:** Making presets a JSON file loaded at runtime from disk. The list is small, static for v1, and belongs as a compile-time constant in each layer. Adding a runtime JSON load creates a new code path that can fail.

---

### 11. Cost Cap Implementation

**PLAN MUST DO:** Implement corrector call counting via a thread-safe mutable dict passed through the call chain:

```python
# In run_ocr_task (batches.py), after reading config:
corrector_cap_state = {"used": 0, "cap": corrector_cap, "lock": threading.Lock()}

# Pass to process_batch, which passes to _process_card_sync, which passes to run_validation
# In corrector.py:
def invoke_corrector(..., cap_state: dict) -> dict:
    with cap_state["lock"]:
        if cap_state["used"] >= cap_state["cap"]:
            return {"status": "skipped", "rationale": "Correction cap reached"}
        cap_state["used"] += 1
    # ... make LLM call ...
```

The cap counter does not need to persist across server restarts (per-batch run is ephemeral). No need to store it in config.json or results.

**WebSocket broadcasting for cap-hit:** The existing `ws_manager.broadcast_progress` sends `BatchProgress` on each image completion. PLAN MUST DECIDE whether to add a `corrector_calls_used` field to `BatchProgress` for real-time cap monitoring — this is a planner discretion item. The minimal v1 approach: surface the cap-hit count only in the final results (ValidationOutcome.rationale = "Cap reached"), not via WebSocket.

---

### 12. Common Pitfalls

### Pitfall 1: Async/Sync Threading Boundary
**What goes wrong:** `_process_card_sync` runs inside `ThreadPoolExecutor` workers (synchronous). Adding `async` calls inside it (e.g., `await something`) will deadlock or fail silently.
**Root cause:** `asyncio.run()` inside a thread that already has an event loop raises `RuntimeError: This event loop is already running.`
**How to avoid:** All validation logic (including corrector HTTP calls) MUST be synchronous. The corrector uses `requests.Session.post()` — same synchronous pattern as `_call_vlm_api_resilient`. The existing `asyncio.run_coroutine_threadsafe` pattern is only for broadcasting progress back to the event loop — do NOT use it for corrector calls.
**Warning signs:** `asyncio` imports inside validation modules.

### Pitfall 2: JSON Schema Codegen Drift
**What goes wrong:** Schema `.json` files edited but `turbo generate` not run — TypeScript types out of sync with backend.
**Root cause:** `generated/ts/index.ts` is committed to git (STATE.md decision) so it appears up-to-date even when stale.
**How to avoid:** PLAN MUST include a task to run `turbo generate` immediately after schema edits, before any frontend code is written. Frontend code should import types from the generated file.
**Warning signs:** TypeScript type errors in batchesApi.ts or wizardStore.ts after schema changes.

### Pitfall 3: Double Source of Truth for Types
**What goes wrong:** `apps/backend/app/models/schemas.py` is maintained separately from the generated Pydantic in `generated/py/`. Adding a field to the schema but not to `schemas.py` means the backend API silently ignores the new field.
**Root cause:** The Pydantic generated files are not imported by the backend — `schemas.py` is the authoritative backend model file (confirmed by `batches.py` line 10: `from app.models.schemas import ...`).
**How to avoid:** PLAN MUST include a task to update `schemas.py` after schema JSON changes. Order: schema JSON → `turbo generate` → `schemas.py` update.

### Pitfall 4: Zustand localStorage Bloat from Validation State
**What goes wrong:** Adding `validation` map to `ResultRow` and including it in `partialize` causes localStorage overflow or performance regression for 500+ row batches.
**Root cause:** STATE.md explicitly notes "Zustand partialize excludes processingState/results" to prevent localStorage performance regression. Per-row validation data can be large.
**How to avoid:** `results` is already excluded from partialize (line 232-243 of wizardStore.ts). The `validation` field on `ResultRow` rides on the excluded `results` array — no additional action needed. Do NOT add a separate `validationState` key to partialize.

### Pitfall 5: FastAPI Route Ordering with New Endpoints
**What goes wrong:** `POST /{batch_name}/revalidate` registered after `POST /{batch_name}/start` does not cause issues because both have the same path structure. But if `/revalidate` is mistakenly added as a static route after a wildcard.
**Root cause:** FastAPI matches routes greedily for path parameters.
**How to avoid:** In `batches.py`, follow the existing convention: register `/{batch_name}/revalidate` in the same section as `/{batch_name}/start`, `/{batch_name}/cancel`, `/{batch_name}/retry`. The only ordering constraint is that static segments like `/history` must come before `/{batch_name}` — confirmed in STATE.md.

### Pitfall 6: `batchesApi.ts` Local Type Copies
**What goes wrong:** `batchesApi.ts` defines its own local `BatchCreate` interface (line 6-11) instead of importing from `@indexcards/shared-types`. Adding fields to the shared types but not to the local copy means the frontend never sends `field_rules`.
**Root cause:** This was a deliberate architectural decision (confirmed by reading `batchesApi.ts` lines 1-11). The local copies are not auto-synced with codegen.
**How to avoid:** PLAN MUST explicitly update `batchesApi.ts` `BatchCreate` interface and the `createBatch` function body to include `field_rules`, `corrector_enabled`, `corrector_cap`.

### Pitfall 7: EditableCell Accept/Reject and Validation Badge Interaction
**What goes wrong:** When a curator accepts a corrector_proposal, the cell value changes via `updateResultCell` — but if the badge still shows "corrected" status, the UI is confusing.
**Root cause:** `validation` field in ResultRow is set during hydration from backend; accepting a correction only updates `editedData`, not `validation`.
**How to avoid:** When accept is clicked on a ValidationBadge, call `updateResultCell` AND update `validation[field].status` to `'valid'` (accepted correction) in the store. PLAN MUST add a `acceptCorrectorProposal(filename, field)` action to `wizardStore.ts` that sets both `editedData[field]` and `validation[field].status = 'valid'`.

---

## Code Examples

### Pattern 1: prompt_template snapshot in create_batch (reference pattern)
```python
# apps/backend/app/services/batch_manager.py line 29-55 (confirmed)
def create_batch(self, custom_name, session_id, fields=None, prompt_template=None):
    config_data = {
        "custom_name": custom_name,
        "fields": fields or settings.FIELD_KEYS,
        "prompt_template": prompt_template,    # snapshotted
        "created_at": datetime.now().isoformat()
    }
    with open(batch_path / "config.json", "w") as f:
        json.dump(config_data, f, indent=2)
```

### Pattern 2: prompt_template read in run_ocr_task (reference pattern)
```python
# apps/backend/app/api/api_v1/endpoints/batches.py line 38-47 (confirmed)
if config_path.exists():
    with open(config_path, "r") as f:
        config = json.load(f)
        fields = config.get("fields")
        prompt_template = config.get("prompt_template")   # backward-compatible .get()
        provider = config.get("provider", "openrouter")
        model = config.get("model")
```

### Pattern 3: Thread-pool parameter threading (reference pattern)
```python
# apps/backend/app/services/ocr_engine.py lines 401-407 (confirmed)
futures = {
    executor.submit(
        self._process_card_sync, img, batch_name, fields, max_size,
        prompt_template, api_endpoint, model_name, api_key   # ← all passed positionally
    ): img
    for img in files_to_process
}
```

### Pattern 4: sonner toast with action+cancel (confirmed from FieldManager.tsx)
```typescript
// apps/frontend/src/features/configure/FieldManager.tsx lines 32-44
toast(`Remove field "${label}"?`, {
  action: { label: 'Confirm', onClick: () => { /* ... */ } },
  cancel: { label: 'Cancel', onClick: () => {} },
});
```

### Pattern 5: FieldManager field row (extension point)
```tsx
// apps/frontend/src/features/configure/FieldManager.tsx lines 95-111
{fields.map((field) => (
  <div key={field.id} className="flex items-center justify-between px-6 py-4 ...">
    <div className="flex items-center gap-3">
      <Tag icon /> <span>{field.label}</span>
    </div>
    <Trash2 button />
  </div>  // ← extend: add <ValidationRuleEditor field={field} /> below this div
))}
```

### Pattern 6: Zustand partialize (confirmed from wizardStore.ts)
```typescript
// apps/frontend/src/store/wizardStore.ts lines 232-243
partialize: (state) => ({
  step: state.step,
  view: state.view,
  files: state.files.map(({ preview: _, ...rest }) => rest),
  fields: state.fields,      // ← field rules ride here (MetadataField.rule)
  sessionId: state.sessionId,
  batchId: state.batchId,
  promptTemplate: state.promptTemplate,
  selectedTemplateName: state.selectedTemplateName,
  provider: state.provider,
  model: state.model,
  // results: excluded intentionally (performance)
  // processingState: excluded intentionally
  // NEW: correctorEnabled, correctorCap — add here (small scalars, safe to persist)
}),
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Separate validation profile JSON | Rules inline on field definition | No extra file, snapshot-at-creation follows prompt_template pattern |
| Auto-apply corrections silently | Always proposed, curator approves | Curatorial transparency — matches museum workflow norms |
| python-Levenshtein (thin C wrapper) | rapidfuzz (full-featured, maintained) | Better API, C ext with Python fallback, widely used in 2025+ |

---

## Open Questions

1. **Corrector model choice**
   - What we know: `_resolve_provider` returns OpenRouter endpoint. OpenRouter offers many cheap text models.
   - What's unclear: Which is the current best price/quality ratio for a text-only correction task (mid-2026)?
   - Recommendation: Use `anthropic/claude-haiku-4` as default (smallest Anthropic model on OpenRouter); make it configurable via `CORRECTOR_MODEL_NAME` in `config.py`. Planner should note this as a configurable constant, not hardcoded.

2. **Revalidate as background task or synchronous**
   - What we know: For small batches (≤100 rows, no corrector), synchronous is fine (<1s). With corrector enabled and cap=100, each corrector call can take 2-5s, so 100 calls = 200-500s.
   - Recommendation: PLAN should implement `/revalidate` as a BackgroundTask (same as `/retry`) with WebSocket progress broadcast. This avoids request timeouts on large batches with corrector.

3. **`validation` field in checkpoint.json backward compatibility**
   - What we know: `checkpoint.json` is a plain JSON array of result dicts. Adding `"validation": null` to new results is backward-compatible.
   - What's unclear: Old batches lacking `"validation"` key — frontend must treat missing as `null`/no-badge.
   - Recommendation: In `ResultsStep.tsx` hydration, use `validation: r.validation ?? null`. No migration needed.

---

## Sources

### Primary (HIGH confidence — direct codebase reads)
- `apps/backend/app/services/ocr_engine.py` — full OcrEngine implementation, `_process_card_sync` insertion point at line ~309
- `apps/backend/app/services/batch_manager.py` — `create_batch` snapshot pattern, lines 29-55
- `apps/backend/app/api/api_v1/endpoints/batches.py` — `run_ocr_task`, `_resolve_provider`, all endpoint patterns
- `apps/backend/app/models/schemas.py` — Pydantic model shapes (hand-maintained, NOT generated)
- `apps/backend/app/core/config.py` — Settings, API endpoint constants
- `packages/shared-types/schemas/batch.schema.json` — Current BatchConfig/BatchCreate/ExtractionResult schema
- `packages/shared-types/schemas/template.schema.json` — Current Template/TemplateCreate/TemplateUpdate schema
- `packages/shared-types/generated/ts/index.ts` — Current generated TypeScript interfaces
- `packages/shared-types/scripts/generate.mjs` — Codegen script mechanics
- `apps/frontend/src/store/wizardStore.ts` — Zustand store, partialize keys, MetadataField interface
- `apps/frontend/src/features/configure/FieldManager.tsx` — Field row structure, sonner toast pattern
- `apps/frontend/src/features/configure/ConfigureStep.tsx` — Card 1/2 layout, handleStartExtraction
- `apps/frontend/src/features/results/ResultsTable.tsx` — dl/dd extraction column, EditableCell
- `apps/frontend/src/features/results/ResultsStep.tsx` — Hydration, fieldLabels derivation
- `apps/frontend/src/features/results/SummaryBanner.tsx` — Stats section structure
- `apps/frontend/src/features/results/useResultsExport.ts` — All download functions, triggerDownload
- `apps/frontend/src/api/batchesApi.ts` — Local BatchCreate type, mutation hooks, sonner usage
- `.planning/STATE.md` — Key decisions: partialize exclusion, prompt_template pattern, route ordering, threading model

### Secondary (MEDIUM confidence)
- rapidfuzz library: widely used Python fuzzy matching library with C extension; recommended over python-Levenshtein for API ergonomics and maintenance status (as of 2025-2026 ecosystem surveys)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed present in package.json / requirements.txt; only rapidfuzz is new
- Architecture: HIGH — all patterns confirmed from live codebase reads with exact line numbers
- Pitfalls: HIGH — based on confirmed code paths and STATE.md decisions

**Research date:** 2026-05-13
**Valid until:** 2026-06-13 (stable codebase; only invalidated if Phase 7 files are modified)
