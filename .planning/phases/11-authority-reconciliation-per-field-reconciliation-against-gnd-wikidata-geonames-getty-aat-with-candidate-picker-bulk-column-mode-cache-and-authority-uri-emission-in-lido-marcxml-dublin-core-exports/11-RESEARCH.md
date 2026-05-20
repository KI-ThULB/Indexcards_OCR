# Phase 11: Authority Reconciliation — Research Findings

**Status:** Research complete — ready for planning
**Date:** 2026-05-18

---

## 1. The Four Authority APIs — Concrete Endpoint Research

### 1.1 GND via Lobid

**Recommended endpoint:**
```
GET https://lobid.org/gnd/search?q={query}&filter=type:{TypeName}&format=json&size=5
```

**Parameters:**
- `q` — free-text search query (required). Also supports field-specific syntax like `preferredName:Goethe`
- `filter` — entity-type filter using Elasticsearch query syntax (e.g., `filter=type:Person`)
- `format` — must be `json` for JSON-LD output (default is HTML)
- `size` — result count (default 10; use 5 for candidate-picker top-5)
- `from` — pagination offset (default 0)

**GND entity-type filter values** (exact strings for `filter=type:X`):

| AuthorityType in CONTEXT | Lobid filter value |
|---|---|
| `gnd-persons` | `Person` |
| `gnd-places` | `PlaceOrGeographicName` |
| `gnd-subjects` | `SubjectHeading` |
| `gnd-corporate-bodies` | `CorporateBody` |
| `gnd-works` | `Work` |

Note: `DifferentiatedPerson` is a subtype of `Person` and will be included when filtering by `Person`. The Lobid API uses Elasticsearch under the hood; the `filter=type:Person` syntax catches all GND entities of type Person including DifferentiatedPerson.

**Response shape (JSON-LD):**
```json
{
  "@context": "...",
  "id": "https://lobid.org/gnd/search?q=...&filter=type:Person&format=json",
  "totalItems": 158,
  "member": [
    {
      "id": "https://d-nb.info/gnd/118540238",
      "gndIdentifier": "118540238",
      "preferredName": "Goethe, Johann Wolfgang von",
      "type": ["DifferentiatedPerson", "Person", "AuthorityResource"],
      "biographicalOrHistoricalInformation": ["Dt. Dichter und Naturforscher"],
      "dateOfBirth": ["1749"],
      "dateOfDeath": ["1832"],
      "professionOrOccupation": [{ "id": "...", "label": "Dichter" }],
      "sameAs": [{ "id": "https://viaf.org/viaf/24602065", "collection": {...} }]
    }
  ],
  "aggregation": { ... }
}
```

**Candidate extraction** (for the reconcile endpoint's `candidates` response):
- `label` = `member[i].preferredName`
- `uri` = `member[i].id` (the `https://d-nb.info/gnd/<ID>` URI)
- `description` = `member[i].biographicalOrHistoricalInformation[0]` or a join of `type` labels

**Auth:** None required. The Lobid API is open.

**Rate limits (from lobid.org/usage-policy):**
- Simple lookups: 6,000 req/min
- Complex queries (wildcard, faceted): 30 req/min
- Bulk harvesting should use `format=jsonl` and happen off-peak
- Caching recommended (minimum 12h — our per-batch no-TTL cache satisfies this)
- MUCH more lenient than Wikidata or GeoNames — bulk mode can serialize at modest pace

**Canonical URI form:**
`https://d-nb.info/gnd/<ID>` (HTTPS since 2019; Lobid response returns this in `member[i].id`)

**MARC $0 subfield convention:**
`(DE-588)<ID>` — where DE-588 is the ISIL of Deutsche Nationalbibliothek. The numeric/alphanumeric GND ID follows without the base URI. Examples:
- `(DE-588)118540238` for Goethe
- `(DE-588)4062129-7` for a place (Berlin)

The parenthetical-prefix form is used because this is a text identifier (not a dereferenceable URI directly in $0). The full URI may optionally appear in $1 per modern MARC best practice, but $0 with `(DE-588)` is the K10plus / ZDB convention.

---

### 1.2 Wikidata via wbsearchentities

**Recommended endpoint:**
```
GET https://www.wikidata.org/w/api.php?action=wbsearchentities&search={query}&language=de&uselang=de&type=item&limit=5&format=json
```

**Parameters:**
- `action=wbsearchentities` — required
- `search` — free-text query (required)
- `language` — language for candidate matching (set to `de` for German archival data; affects which label is matched against)
- `uselang` — language for returned labels/descriptions (set to `de`); falls back to English when German label absent
- `type` — entity type (`item` is correct for archival entities; `property` not needed)
- `limit` — max results (0–50, default 7); use 5 for top-5 candidate picker
- `strictlanguage` — boolean; omit or set false to enable fallback to English when German label absent (recommended)
- `format=json` — required for JSON response

**Language preference recommendation (per CONTEXT discretion):** Use `language=de&uselang=de` without `strictlanguage`. This returns German labels when available, with transparent fallback to English. German archives expect German labels for well-known entities (German states, persons with German-language authority records) and English fallback for international entities.

**Response shape:**
```json
{
  "searchinfo": { "search": "Berlin" },
  "search": [
    {
      "id": "Q64",
      "title": "Q64",
      "pageid": 66,
      "concepturi": "http://www.wikidata.org/entity/Q64",
      "repository": "wikidata",
      "url": "//www.wikidata.org/wiki/Q64",
      "display": {
        "label": { "value": "Berlin", "language": "de" },
        "description": { "value": "Bundesland und Hauptstadt Deutschlands", "language": "de" }
      },
      "label": "Berlin",
      "description": "Bundesland und Hauptstadt Deutschlands",
      "match": { "type": "label", "language": "de", "text": "Berlin" }
    }
  ],
  "search-continue": 5,
  "success": 1
}
```

**Candidate extraction:**
- `label` = `search[i].label`
- `uri` = `search[i].concepturi` (the canonical `http://www.wikidata.org/entity/Q<n>` URI)
- `description` = `search[i].description`

Note: The canonical URI uses `http://` (not `https://`). This is intentional per Wikidata convention. The URI redirects to entity data but the identifier itself is `http://www.wikidata.org/entity/Q<n>`.

**Auth:** None required. Wikidata Action API is open.

**Rate limits:**
- Anonymous users as of 2026: approximately 10 req/min per Wikimedia's new 2026 rate-limit policy (newly deployed; previously informal ~50 req/s)
- Rate limiting is enforced with HTTP 429 + `Retry-After` header
- Important: Set a descriptive `User-Agent` header (e.g., `IndexcardsOCR/1.0 (contact@thulb.uni-jena.de)`) to avoid being placed in the "unidentified" tier with the most restrictive limits
- The 2026 policy is still being rolled out; conservative behavior: treat as 10 req/s (600/min) for a properly identified client

**429 handling:** Wikidata returns HTTP 429 with a `Retry-After` header (seconds). Backend must honor this. The exponential-backoff retry (3 attempts at 1s/2s/4s) from CONTEXT covers this. After 3 failures, surface as "API error — retry?" in the drawer per CONTEXT.

**Canonical URI form:** `http://www.wikidata.org/entity/Q<n>`

**MARC $0 subfield convention:**
Full URI (no parenthetical prefix): `http://www.wikidata.org/entity/Q64`. MARC21 policy since 2016 dropped the `(uri)` prefix requirement for dereferenceable HTTP URIs — include the URI directly in $0.

---

### 1.3 GeoNames via searchJSON

**Recommended endpoint:**
```
GET http://api.geonames.org/searchJSON?q={query}&maxRows=5&username={GEONAMES_USERNAME}&style=SHORT
```

Note: GeoNames uses `http://` (not `https://`) for their API domain. Many clients transparently follow the redirect but some Python/aiohttp clients may not; use `http://` as the base.

**Parameters:**
- `q` — free-text search query (queries all attributes: place name, country name, admin codes, etc.)
- `maxRows` — max results (default 100, max 1000); use 5 for candidate picker
- `username` — required auth parameter (GeoNames account username)
- `style` — response verbosity: `SHORT` (minimal), `MEDIUM` (default), `LONG`, `FULL`; `SHORT` or `MEDIUM` is sufficient for candidate picker

**Response shape (JSON):**
```json
{
  "totalResultsCount": 1614,
  "geonames": [
    {
      "geonameId": 2950159,
      "toponymName": "Berlin",
      "name": "Berlin",
      "lat": "52.52437",
      "lng": "13.41053",
      "countryCode": "DE",
      "countryName": "Germany",
      "fcl": "A",
      "fclName": "country, state, region,...",
      "fcode": "PPLC",
      "fcodeName": "capital of a political entity",
      "adminName1": "Land Berlin",
      "population": 3426354
    }
  ]
}
```

**Candidate extraction:**
- `label` = `geonames[i].toponymName` (or `name`)
- `uri` = `https://www.geonames.org/{geonameId}` (the canonical GeoNames URI for the place)
- `description` = `geonames[i].fclName + ", " + geonames[i].countryName` (human-readable)

**Auth:** `username` query parameter — a registered GeoNames account. Must be exposed via env var `GEONAMES_USERNAME` per CONTEXT discretion. No API key; just the account username.

**Error UX if `GEONAMES_USERNAME` missing:** The reconcile endpoint should return HTTP 503 with `{ "error": "GEONAMES_USERNAME not configured" }`. This signals to the frontend that the authority is unavailable — the drawer should show "GeoNames not available (configuration required)". The bulk-mode flow treats this as a persistent failure → "needs review".

**Rate limits:**
- Free tier: 10,000 credits/day, 1,000 credits/hour per username
- Each search request = 1 credit
- 1,000/hour = ~16–17 req/min; bulk mode must serialize slower than that

**Rate-limit error detection — CRITICAL:**
GeoNames does NOT return HTTP 429 for rate limiting. It returns HTTP 200 with a JSON error body:
```json
{ "status": { "message": "the hourly limit of 1000 credits for demo has been exceeded.", "value": 19 } }
```
Error codes to detect:
- `value: 18` — daily limit exceeded
- `value: 19` — hourly limit exceeded
- `value: 20` — weekly limit exceeded
- `value: 22` — server overloaded

The backend GeoNames client MUST parse the response body and check for `status.value` codes, not just HTTP status. A 200 response with a `status.value` of 18/19/20 must be treated as a rate-limit error and trigger the exponential-backoff retry. After 3 failures, surface as "API error — retry?" — do NOT silently drop as an empty result.

**Canonical URI form:** `https://www.geonames.org/{geonameId}` (human-readable page URI, standard for linked data)

Alternative linked-data URI: `http://sws.geonames.org/{geonameId}/` — this is the RDF/LOD canonical form used in semantic web contexts. For MARC $0 and LIDO, either form is acceptable; the `https://www.geonames.org/{id}` form is more recognizable to non-semantic-web consumers.

**MARC $0 subfield convention:**
Full URI: `https://www.geonames.org/2950159`. No parenthetical prefix (dereferenceable HTTP URI).

---

### 1.4 Getty AAT via Reconciliation-API Endpoint

**Recommended endpoint:**
```
POST https://services.getty.edu/vocab/reconcile/aat
Content-Type: application/x-www-form-urlencoded

queries={"q1":{"query":"{query}","limit":5}}
```

Or as GET:
```
GET https://services.getty.edu/vocab/reconcile/aat?queries={"q1":{"query":"{query}","limit":5}}
```

The endpoint implements the W3C Reconciliation Service API v0.2 protocol. The `/aat` path restricts results to the Art & Architecture Thesaurus only (vs `/ulan` for persons/orgs, `/tgn` for geographic, `/all` for combined). Phase 11 uses `/aat` exclusively.

**Service manifest:** `GET https://services.getty.edu/vocab/reconcile/` returns the service manifest with `defaultTypes` including:
- `{ id: "/aat", name: "AAT search" }`
- `{ id: "/ulan", name: "ULAN search" }`
- `{ id: "/tgn", name: "TGN search" }`
- `{ id: "/all", name: "Search all Vocabs" }`

**Query format (W3C Reconciliation Service API v0.2):**
The `queries` parameter is a JSON object with string keys, each value being a query object:
```json
{
  "q1": {
    "query": "oil painting",
    "limit": 5
  }
}
```
Multiple queries per request are supported but for Phase 11 use one query per POST (simpler implementation, matches cache key granularity).

**Response shape:**
```json
{
  "q1": {
    "result": [
      {
        "id": "aat/300178684",
        "name": "oil painting (technique)",
        "score": 100.0,
        "match": true,
        "type": [{ "id": "/aat", "name": "AAT" }],
        "description": "..."
      }
    ]
  }
}
```

**Candidate extraction:**
- `label` = `q1.result[i].name`
- `uri` = `http://vocab.getty.edu/aat/{numeric_id}` — extract the numeric ID from `id` ("aat/300178684" → 300178684 → `http://vocab.getty.edu/aat/300178684`)
- `description` = `q1.result[i].description` (may be absent; fall back to empty string)
- `score` / `match` can inform auto-accept logic

**Auth:** None. Getty AAT Reconciliation API is open.

**Rate limits:** Not formally documented. Getty's SPARQL endpoint has a 10-second timeout per query but no documented request-per-minute cap for the reconciliation endpoint. Treat conservatively as 60 req/min. The reconciliation endpoint is designed for batch use in OpenRefine.

**429 handling:** Returns standard HTTP 429 if throttled. Honor Retry-After if present; if absent, wait 5s minimum (Wikimedia convention). Exponential-backoff (1s/2s/4s) handles this.

**Canonical URI form:** `http://vocab.getty.edu/aat/<numericID>` (e.g., `http://vocab.getty.edu/aat/300178684`)

Both `http://vocab.getty.edu/aat/<id>` and the page URI `http://vocab.getty.edu/page/aat/<id>` exist. The **concept URI** (`vocab.getty.edu/aat/<id>` — no `/page/`) is the canonical linked data URI that dereferences to RDF. LIDO and MARC consumers expect the concept URI form.

**MARC $0 subfield convention:**
Full URI: `http://vocab.getty.edu/aat/300178684`. No parenthetical prefix.

**AAT vs SPARQL note:** The Reconciliation API is the right choice over SPARQL for candidate search. SPARQL full-text search on AAT requires `luc:term` Lucene queries which are less stable and require knowledge of the GVP ontology. The Reconciliation API abstracts this cleanly.

---

## 2. Summary Table: API Parameters and URI Conventions

| Authority | Search Endpoint | Auth | Rate Limit | Canonical URI | MARC $0 form |
|---|---|---|---|---|---|
| GND (Lobid) | `https://lobid.org/gnd/search?q={q}&filter=type:{T}&format=json&size=5` | None | 6000/min simple, 30/min complex | `https://d-nb.info/gnd/{id}` | `(DE-588){id}` |
| Wikidata | `https://www.wikidata.org/w/api.php?action=wbsearchentities&search={q}&language=de&uselang=de&type=item&limit=5&format=json` | None | ~10 req/min (anonymous, 2026 policy); higher with User-Agent | `http://www.wikidata.org/entity/Q{n}` | `http://www.wikidata.org/entity/Q{n}` (full URI) |
| GeoNames | `http://api.geonames.org/searchJSON?q={q}&maxRows=5&username={U}` | `username` param from env | 1000/hr per account | `https://www.geonames.org/{id}` | `https://www.geonames.org/{id}` (full URI) |
| Getty AAT | `https://services.getty.edu/vocab/reconcile/aat` (POST, queries param) | None | ~60 req/min (conservative) | `http://vocab.getty.edu/aat/{id}` | `http://vocab.getty.edu/aat/{id}` (full URI) |

---

## 3. Existing Infrastructure Mapping

### 3.1 Phase 8 `field_rules` snapshot pattern (insertion point for `authority_bindings`)

File: `apps/backend/app/services/batch_manager.py` — `create_batch()` method (lines 29–81).

The exact same pattern used for `field_rules` applies to `authority_bindings`. The `create_batch()` call receives `authority_bindings` from the batch creation API, and the method writes it to `config_data` in `config.json`:

```python
config_data = {
    "custom_name": custom_name,
    "fields": fields or settings.FIELD_KEYS,
    "prompt_template": prompt_template,
    "field_rules": field_rules,
    "authority_bindings": authority_bindings,   # NEW: same pattern as field_rules
    "corrector_enabled": corrector_enabled,
    "corrector_cap": corrector_cap,
    "created_at": datetime.now().isoformat()
}
```

Both `BatchCreate` and `BatchConfig` Pydantic models need `authority_bindings: Optional[Dict[str, AuthorityBinding]] = None` added alongside `field_rules`.

The run_ocr_task function in `apps/backend/app/api/api_v1/endpoints/batches.py` reads `config.json` on batch start — the reconcile endpoint reads it separately and does not participate in the OCR pipeline.

### 3.2 `normalizeValue` in `validationRuntime.ts` — already exported

File: `apps/frontend/src/features/clean/validationRuntime.ts` — line 15.

`normalizeValue` is already exported as a named export: `export function normalizeValue(value: string): string`. Phase 11 bulk-mode auto-accept can import it directly:
```ts
import { normalizeValue } from '../clean/validationRuntime';
```
The Python equivalent `normalize_value()` is in `apps/backend/app/services/validation/vocab_rules.py`. The backend reconcile endpoint does NOT need to run normalizeValue for matching (that comparison happens on the frontend). The backend uses normalizeValue for building cache keys (the normalized query is the cache key). The Python function needs to be importable from the authority clients.

### 3.3 Phase 8 `ValidationOutcome` extension

**JSON Schema** (`packages/shared-types/schemas/batch.schema.json`):
`ValidationOutcome` definition currently has: `status`, `rule_failed`, `original_value`, `rationale`, `corrector_proposal`. Phase 11 adds:
```json
"reconciliation": {
  "anyOf": [
    { "$ref": "#/definitions/ReconciliationOutcome" },
    { "type": "null" }
  ],
  "default": null
}
```
New definition to add:
```json
"ReconciliationOutcome": {
  "type": "object",
  "title": "ReconciliationOutcome",
  "properties": {
    "authority": { "type": "string" },
    "uri":       { "type": "string" },
    "label":     { "type": "string" },
    "picked_by": { "type": "string", "enum": ["auto", "manual"] },
    "picked_at": { "type": "string", "description": "ISO 8601 date string" }
  },
  "required": ["authority", "uri", "label", "picked_by", "picked_at"]
}
```

Also needs `AuthorityBinding` and associated types in `template.schema.json` (for field binding on MetadataField). Pattern mirrors FieldRule:
- `template.schema.json` gets `AuthorityBinding` definition + `authority_bindings` property on Template/TemplateCreate/TemplateUpdate
- `batch.schema.json` gets `authority_bindings` on `BatchConfig` and `BatchCreate`

**Pydantic** (`apps/backend/app/models/schemas.py`):
```python
class ReconciliationOutcome(BaseModel):
    authority: str
    uri: str
    label: str
    picked_by: str   # "auto" | "manual"
    picked_at: str   # ISO date

class AuthorityBinding(BaseModel):
    type: Optional[str] = None   # AuthorityType string or null

class ValidationOutcome(BaseModel):
    status: str
    rule_failed: Optional[str] = None
    original_value: Optional[str] = None
    rationale: Optional[str] = None
    corrector_proposal: Optional[str] = None
    reconciliation: Optional[ReconciliationOutcome] = None  # NEW
```

Also add `authority_bindings` to `BatchConfig`, `BatchCreate`, `Template`, `TemplateCreate`, `TemplateUpdate`.

**Frontend `batchesApi.ts` (type-copy drift — CRITICAL PITFALL):**
`ValidationOutcome` interface at line 14 needs `reconciliation?: ReconciliationOutcome | null`. Also add:
```ts
export interface ReconciliationOutcome {
  authority: string;
  uri: string;
  label: string;
  picked_by: 'auto' | 'manual';
  picked_at: string;
}

export type AuthorityType =
  | 'gnd-persons' | 'gnd-places' | 'gnd-subjects' | 'gnd-corporate-bodies' | 'gnd-works'
  | 'wikidata' | 'geonames' | 'aat' | null;

export interface AuthorityBinding {
  type: AuthorityType;
}
```

`BatchCreate` and `BatchConfig` both need `authority_bindings?: Record<string, AuthorityBinding> | null`.

**`wizardStore.ts` `MetadataField`** (line 17):
```ts
export interface MetadataField {
  id: string;
  label: string;
  type: 'text' | 'date' | 'number' | 'enum';
  options?: string[];
  rule?: FieldRule | null;
  authority?: AuthorityBinding | null;  // NEW
}
```

**Zustand store** needs `updateFieldAuthority(fieldId: string, authority: AuthorityBinding | null)` action parallel to `updateFieldRule`. FieldManager's template save needs to serialize `authority_bindings` (same pattern as `fieldRules` serialization in `handleSaveTemplate`).

### 3.4 Phase 10 AuditEntry — new `source` values, no shape change

File: `apps/backend/app/models/schemas.py` — `AuditEntry` class (line 107).

Current `source` type is `str`. The AuditEntry model does NOT restrict `source` values by enum — it accepts any string. Phase 11 reconciliation actions use:
- `source: 'reconciliation-auto'`
- `source: 'reconciliation-manual'`
- `source: 'reconciliation-cleared-by-edit'`
- `source: 'reconciliation-no-match'`

These slot into the existing AuditEntry shape without any schema change. The `op` field for reconciliation entries should be a new value: `'reconciliation'`. Current op values: `'bulk-transform' | 'cluster-merge'`.

In `batchesApi.ts` (line 42), the `AuditEntry.op` type is `'bulk-transform' | 'cluster-merge'`. Phase 11 adds `| 'reconciliation'`. The `AuditEntry.source` type is `'bulk-transform' | 'cluster-merge'` — Phase 11 adds `| 'reconciliation-auto' | 'reconciliation-manual' | 'reconciliation-cleared-by-edit' | 'reconciliation-no-match'`.

**AuditPanel rendering** for reconciliation entries: The AuditPanel in `apps/frontend/src/features/clean/AuditPanel.tsx` renders audit entries by label. Reconciliation entries get labels like "Reconciled 3 cells in column Komponist (auto)" or "Reconciliation cleared on edit". The link icon in the label (a small external-link icon pointing to the URI) is reasonable for picked entries.

### 3.5 Phase 9 `PATCH /api/v1/batches/{batch_name}/results/{filename}` — extension for reconciliation

File: `apps/backend/app/api/api_v1/endpoints/batches.py` — `patch_result()` function (line 209).

Current `ResultPatch` has: `field`, `value`, `validation_status`, `audit_entry`. Phase 11 needs to persist the `reconciliation` field on a specific field's ValidationOutcome. Options:

**Option A (recommended): Add `reconciliation` to `ResultPatch`.**
```python
class ResultPatch(BaseModel):
    field: str
    value: Optional[str] = None
    validation_status: Optional[str] = None
    reconciliation: Optional[dict] = None   # ReconciliationOutcome dict or null to clear
    audit_entry: Optional[dict] = None
```
The `patch_result` handler adds a branch:
```python
if patch.reconciliation is not None and patch.field:
    if row.get("validation") and patch.field in row["validation"]:
        row["validation"][patch.field]["reconciliation"] = patch.reconciliation
    # If reconciliation is explicitly null dict: {}, clear it (no-match case)
```

**Option B: Dedicated `POST /api/v1/batches/{batch_name}/reconcile-cell` endpoint.**
Heavier; not needed since PATCH is general enough.

**Recommendation:** Option A. Same endpoint, same pattern, minimal change. The `reconciliation` field in the PATCH body is either a `ReconciliationOutcome` dict (to persist a pick) or `null` (to clear on edit/no-match).

**Reconciliation clearing on edit:** When a PATCH carries a new `value` that differs from the stored value and the cell was reconciled, the reconciliation must be cleared. Per CONTEXT: "editing the cell value auto-clears reconciliation". Two approaches:

- **Client-side**: The React PATCH builder (in FieldsPane or future ReconcilePane) explicitly passes `reconciliation: null` when the new value differs from the previous value.
- **Server-side**: The PATCH handler checks if `value` is being changed and automatically nulls `validation[field].reconciliation`.

**Recommendation: client-side.** The client already knows the old value (from `editedData` or `data`), so it can include `reconciliation: null` in the PATCH body when value changes. Server-side detection requires reading the current value, which adds a read-before-write complexity. The existing client-side "verified survives no-op" pattern (Phase 9/10) is already client-side — reconciliation clearing should follow the same approach.

The `batchesApi.ts` `patchResult` function at line 99 needs its type updated:
```ts
patch: {
  field: string;
  value?: string | null;
  validation_status?: string | null;
  reconciliation?: ReconciliationOutcome | null;   // NEW
  audit_entry?: AuditEntry | null;
}
```

### 3.6 Configure step — `AuthorityBindingEditor` alongside `ValidationRuleEditor`

File: `apps/frontend/src/features/configure/FieldManager.tsx` — the per-field section (line 105).

Current pattern: each field row renders `<ValidationRuleEditor>` below the label row. Phase 11 adds `<AuthorityBindingEditor>` after (or before) `ValidationRuleEditor`. Because ValidationRuleEditor is a disclosure with its own collapse header, AuthorityBindingEditor should also be a collapsible disclosure using the same pattern (`isExpanded` state + ChevronDown icon + border-t divider).

```tsx
<div key={field.id} className="flex flex-col border-b border-parchment-dark/20 last:border-0">
  <div className="flex items-center justify-between px-6 py-4 ...">
    {/* field label + delete button */}
  </div>
  <ValidationRuleEditor
    field={field}
    correctorAvailable={correctorEnabled}
    onChange={(rule) => updateFieldRule(field.id, rule)}
  />
  <AuthorityBindingEditor          {/* NEW */}
    field={field}
    onChange={(binding) => updateFieldAuthority(field.id, binding)}
  />
</div>
```

`AuthorityBindingEditor` is a new file: `apps/frontend/src/features/configure/AuthorityBindingEditor.tsx`. It renders:
- Collapse header: "Authority" label + link-icon + current authority type badge (if set)
- When expanded: a dropdown `<select>` with options: None, GND: Persons, GND: Places, GND: Subjects, GND: Corporate Bodies, GND: Works, Wikidata, GeoNames, Getty AAT

`FieldManager.handleSaveTemplate` (line 53) must be updated to serialize `authority_bindings`:
```ts
const authorityBindings: Record<string, AuthorityBinding> = {};
fields.forEach((f) => {
  if (f.authority?.type) authorityBindings[f.label] = f.authority;
});
createTemplateMutation.mutate({
  name,
  fields: fields.map((f) => f.label),
  prompt_template: promptTemplate,
  field_rules: ...,
  authority_bindings: Object.keys(authorityBindings).length > 0 ? authorityBindings : null,
});
```

Template hydration (`TemplateSelector.handleSelectTemplate`) must map `template.authority_bindings` back to fields (same pattern as `template.field_rules` mapping).

The `templatesApi.ts` also has local type copies (Template, TemplateCreate) — check and update with `authority_bindings` field.

### 3.7 Export generators — LIDO, MARCXML, Dublin Core insertion points

File: `apps/frontend/src/features/results/useResultsExport.ts`

All three export functions live in this single file. Phase 11 is client-side (exports already are), so URI injection happens here too.

**How to access reconciliation URIs in the export functions:**
Each `ResultRow.validation[field].reconciliation.uri` holds the URI for that field. The export functions already have access to `row.validation` via the `ResultRow` type.

Helper to extract URI for a field:
```ts
function getReconciliationUri(row: ResultRow, field: string): string | null {
  return row.validation?.[field]?.reconciliation?.uri ?? null;
}
```

---

**LIDO insertion point (line 145 approx in the existing LIDO block):**

Current LIDO exports `<lido:objectDescriptionSet>` for each field. Phase 11 adds `<lido:conceptID>` for subject/topic fields and `<lido:actorID>` for person fields inside the existing event block.

Exact element paths per CONTEXT:
- **Subject/topic terms** (e.g., AAT-bound fields): Inside `<lido:objectDescriptionSet lido:type="...">`, add `<lido:conceptID lido:type="URI" lido:source="{authorityLabel}">{uri}</lido:conceptID>` before or alongside the `<lido:descriptiveNoteValue>`.
- **Actor/person** (e.g., GND/Wikidata-bound Komponist): Inside `<lido:actor>`, add `<lido:actorID lido:type="URI" lido:source="{authorityLabel}">{uri}</lido:actorID>`.

Concrete change in `descSets` map (around line 148):
```ts
.map((f) => {
  const uri = getReconciliationUri(row, f.name);
  const uriBlock = uri ? `\n          <lido:conceptID lido:type="URI" lido:source="${e(f.name)}">${e(uri)}</lido:conceptID>` : '';
  return `
    <lido:objectDescriptionSet lido:type="${e(f.name)}">
      ${uriBlock}
      <lido:descriptiveNoteValue>${e(f.value)}</lido:descriptiveNoteValue>
    </lido:objectDescriptionSet>`;
})
```

For the Komponist `<lido:actor>` block (around line 154–164):
```ts
const komponistUri = getReconciliationUri(row, 'Komponist');
const actorIdBlock = komponistUri ? `<lido:actorID lido:type="URI">${e(komponistUri)}</lido:actorID>` : '';
// Insert actorIdBlock inside <lido:actor> alongside <lido:nameActorSet>
```

---

**MARCXML insertion point (field 100/700 blocks, around line 452 approx):**

The existing `f100` block (MARC 100: personal name) needs `$0` added:
```ts
const authorName = entry['Zu- u. Vorname'] || entry['Komponist'] || '';
const nameField = entry['Zu- u. Vorname'] ? 'Zu- u. Vorname' : 'Komponist';
const nameUri = row ? getReconciliationUri(row, nameField) : null;
// ...
`<marc:subfield code="a">${e(name)}</marc:subfield>
${nameUri ? `<marc:subfield code="0">${e(nameUri)}</marc:subfield>` : ''}
<marc:subfield code="e">VerfasserIn</marc:subfield>`
```

Note: For GND, the URI in $0 should use the `(DE-588){id}` convention, NOT the full `https://d-nb.info/gnd/...` URI. The `uri` field in `ReconciliationOutcome` stores the canonical URI form (`https://d-nb.info/gnd/...`). The MARCXML exporter needs to detect GND URIs and convert:
```ts
function uriToMarc0(uri: string | null): string | null {
  if (!uri) return null;
  const gndMatch = uri.match(/d-nb\.info\/gnd\/(.+)/);
  if (gndMatch) return `(DE-588)${gndMatch[1]}`;
  return uri;  // Wikidata, GeoNames, AAT — use full URI
}
```

The existing `f655` block already has a hardcoded `$0 (DE-588)4113937-9` for "Hochschulschrift" — this existing block is NOT modified (it's a static constant, not from reconciliation data).

Subject-heading fields (655/650 equivalent): If a field has an AAT or GND-subjects reconciliation, add `$0 {marc0Value}` and `$2 gnd` or `$2 aat` in the corresponding field. This requires generating MARC subject fields dynamically for reconciled subject fields — the planner should decide whether to add 650 fields for AAT-bound subject data or only 655.

---

**Dublin Core insertion point (inside `downloadDublinCore`, around line 383):**

Per CONTEXT: `<dcterms:identifier>{uri}</dcterms:identifier>` alongside the human-readable value.

The DC namespace must include `xmlns:dcterms="http://purl.org/dc/terms/"`. The current DC template already uses `xmlns:dc="http://purl.org/dc/elements/1.1/"` but not `dcterms`. Add dcterms to the namespace block.

For each field that has a reconciliation URI:
```ts
// After the dc:creator / dc:subject / etc. line for a mapped field:
const fieldUri = getReconciliationUri(row, field);
if (fieldUri) lines.push(`    <dcterms:identifier>${e(fieldUri)}</dcterms:identifier>`);
```

For unmapped fields (the `rest` block at line 397): Also emit `<dcterms:identifier>` for any unmapped field with a URI.

---

**EAD, Darwin Core, METS/MODS — NOT modified.** Per CONTEXT lock and DEFERRED section.

### 3.8 `checkValidationGate` in `useResultsExport.ts` — unchanged

Line 38. No modification. Reconciliation status is independent from validation status. `status === 'invalid'` is the only soft-block trigger. This stays exactly as-is.

---

## 4. Per-Batch Authority Cache

**File location:** `data/batches/{batch_name}/authority_cache.json`
(sibling to `checkpoint.json` and `config.json`)

**JSON shape:**
```json
{
  "gnd-persons:goethe, johann wolfgang von": [
    { "label": "Goethe, Johann Wolfgang von", "uri": "https://d-nb.info/gnd/118540238", "description": "Dt. Dichter und Naturforscher" }
  ],
  "wikidata:berlin": [
    { "label": "Berlin", "uri": "http://www.wikidata.org/entity/Q64", "description": "Bundesland und Hauptstadt Deutschlands" }
  ],
  "geonames:berlin": [],
  "aat:oil painting": [
    { "label": "oil painting (technique)", "uri": "http://vocab.getty.edu/aat/300178684", "description": "" }
  ]
}
```

**Cache key:** `{authority}:{normalizedQuery}` where `normalizedQuery` = Python `normalize_value(query)` (NFC + ß→ss + casefold + strip-combining-marks + NFC). Python implementation: `apps/backend/app/services/validation/vocab_rules.py` exports `normalize_value()` — import and reuse.

**Empty array `[]` for "no candidates":** Cache should store empty arrays for "queried, no results" responses. This prevents re-querying on subsequent bulk runs. The CONTEXT discretion confirms this: `{ "<authority>:<query>": [] }`.

**Cache helpers location:** `apps/backend/app/services/authority/cache.py` (new package `authority/`).

```python
# apps/backend/app/services/authority/cache.py
import json
from pathlib import Path
from app.services.validation.vocab_rules import normalize_value

def _cache_path(batch_dir: Path) -> Path:
    return batch_dir / "authority_cache.json"

def read_cache(batch_dir: Path) -> dict:
    p = _cache_path(batch_dir)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def write_cache_entry(batch_dir: Path, authority: str, query: str, candidates: list) -> None:
    """Write a single cache entry. Thread-safe via file-level atomic write."""
    cache = read_cache(batch_dir)
    key = f"{authority}:{normalize_value(query)}"
    cache[key] = candidates
    p = _cache_path(batch_dir)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.replace(p)  # atomic replace

def lookup_cache(batch_dir: Path, authority: str, query: str) -> list | None:
    """Returns list of candidates if cached (may be empty = no match), or None if not cached."""
    cache = read_cache(batch_dir)
    key = f"{authority}:{normalize_value(query)}"
    return cache.get(key, None)   # None = not in cache; [] = cached no-match

def clear_cache(batch_dir: Path) -> None:
    p = _cache_path(batch_dir)
    if p.exists():
        p.unlink()
```

**Concurrent-write safety:** Bulk mode serializes per authority (CONTEXT decision). Even if two cells fire simultaneously (from different authority queues), file-level atomic `tmp.replace(p)` (rename) prevents corrupt JSON — last writer wins, but because keys are independent, collision is benign (at worst, one result is written twice). For v1, the tmp→rename pattern is sufficient.

**Cache clear endpoint:** Add `DELETE /api/v1/batches/{batch_name}/authority-cache` that calls `clear_cache(batch_dir)`. Returns 204.

---

## 5. Backend Reconcile Endpoint

**Route:** `POST /api/v1/reconcile`

**Request body:**
```python
class ReconcileRequest(BaseModel):
    authority: str   # 'gnd-persons' | 'gnd-places' | 'gnd-subjects' | 'gnd-corporate-bodies' | 'gnd-works' | 'wikidata' | 'geonames' | 'aat'
    query: str
    batch_name: str  # needed to read/write per-batch cache
```

**Response:**
```python
class ReconcileResponse(BaseModel):
    candidates: List[dict]   # [{"label": ..., "uri": ..., "description": ...}]
    from_cache: bool
```

**Endpoint logic:**
1. Look up `(authority, query)` in `authority_cache.json` for `batch_name`
2. If cache hit: return `{ candidates, from_cache: true }`
3. If cache miss: call the appropriate authority client (GND/Wikidata/GeoNames/AAT)
4. Write result (including empty `[]` for no candidates) to cache
5. Return `{ candidates, from_cache: false }`

**Route registration:** Add to `apps/backend/app/api/api_v1/api.py` as a new router prefix `/reconcile`. The endpoint is at `/api/v1/reconcile` (not `/api/v1/batches/...`).

**Rate limit throttling:** Each authority client holds a per-authority asyncio.Semaphore or a simple rate-limiter. Bulk mode on the frontend serializes per-authority (not globally), so the backend endpoint doesn't need to enforce cross-request throttling beyond what's natural from sequential frontend calls.

---

## 6. Authority Clients Package

**Location:** `apps/backend/app/services/authority/`

Files:
```
apps/backend/app/services/authority/
  __init__.py
  cache.py          (Section 4)
  gnd.py            (Lobid client)
  wikidata.py       (wbsearchentities client)
  geonames.py       (searchJSON client)
  aat.py            (Getty Reconciliation API client)
  base.py           (shared retry / backoff helper)
```

**`base.py` — exponential backoff:**
```python
import asyncio
import aiohttp
from typing import Callable, Any

async def fetch_with_retry(
    url: str,
    *,
    method: str = "GET",
    params: dict = None,
    data: dict = None,
    headers: dict = None,
    max_retries: int = 3,
    backoff_base: float = 1.0,
) -> dict:
    """Perform an HTTP request with 3-attempt exponential backoff (1s/2s/4s).
    Raises RuntimeError after max_retries failures.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                req = session.get if method == "GET" else session.post
                async with req(url, params=params, data=data, headers=headers, timeout=10) as resp:
                    if resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", backoff_base * (2 ** attempt)))
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status >= 500:
                        await asyncio.sleep(backoff_base * (2 ** attempt))
                        continue
                    resp.raise_for_status()
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_exc = e
            await asyncio.sleep(backoff_base * (2 ** attempt))
    raise RuntimeError(f"Authority API failed after {max_retries} attempts") from last_exc
```

Each authority client exposes one async function:
```python
async def search_gnd(query: str, authority_type: str) -> list[dict]:
    """Returns [{"label": ..., "uri": ..., "description": ...}]"""
```

**`gnd.py`:**
```python
TYPE_MAP = {
    "gnd-persons":        "Person",
    "gnd-places":         "PlaceOrGeographicName",
    "gnd-subjects":       "SubjectHeading",
    "gnd-corporate-bodies": "CorporateBody",
    "gnd-works":          "Work",
}

async def search_gnd(query: str, authority_type: str) -> list[dict]:
    gnd_type = TYPE_MAP.get(authority_type, "AuthorityResource")
    data = await fetch_with_retry(
        "https://lobid.org/gnd/search",
        params={"q": query, "filter": f"type:{gnd_type}", "format": "json", "size": 5},
        headers={"User-Agent": "IndexcardsOCR/1.0 (contact@thulb.uni-jena.de)"}
    )
    return [
        {
            "label": m.get("preferredName", ""),
            "uri": m.get("id", ""),
            "description": (m.get("biographicalOrHistoricalInformation") or [""])[0],
        }
        for m in data.get("member", [])
    ]
```

**`wikidata.py`:**
```python
async def search_wikidata(query: str) -> list[dict]:
    data = await fetch_with_retry(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbsearchentities",
            "search": query,
            "language": "de",
            "uselang": "de",
            "type": "item",
            "limit": 5,
            "format": "json",
        },
        headers={"User-Agent": "IndexcardsOCR/1.0 (contact@thulb.uni-jena.de)"}
    )
    return [
        {
            "label": r.get("label", ""),
            "uri": r.get("concepturi", ""),
            "description": r.get("description", ""),
        }
        for r in data.get("search", [])
    ]
```

**`geonames.py`:**
```python
import os
from app.core.config import settings

async def search_geonames(query: str) -> list[dict]:
    username = settings.GEONAMES_USERNAME
    if not username:
        raise ValueError("GEONAMES_USERNAME not configured")
    data = await fetch_with_retry(
        "http://api.geonames.org/searchJSON",
        params={"q": query, "maxRows": 5, "username": username, "style": "SHORT"},
    )
    # GeoNames rate-limit detection: 200 response with status.value in body
    if "status" in data:
        code = data["status"].get("value")
        if code in (18, 19, 20, 22):
            raise RuntimeError(f"GeoNames rate limit exceeded (code {code}): {data['status'].get('message', '')}")
    return [
        {
            "label": r.get("toponymName", r.get("name", "")),
            "uri": f"https://www.geonames.org/{r['geonameId']}",
            "description": f"{r.get('fclName', '')}, {r.get('countryName', '')}".strip(", "),
        }
        for r in data.get("geonames", [])
        if r.get("geonameId")
    ]
```

**`aat.py`:**
```python
import json, re

async def search_aat(query: str) -> list[dict]:
    queries_param = json.dumps({"q1": {"query": query, "limit": 5}})
    data = await fetch_with_retry(
        "https://services.getty.edu/vocab/reconcile/aat",
        method="POST",
        data={"queries": queries_param},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    results = data.get("q1", {}).get("result", [])
    candidates = []
    for r in results:
        raw_id = r.get("id", "")
        # id is "aat/300178684" → extract numeric ID
        m = re.match(r"aat/(\d+)", raw_id)
        uri = f"http://vocab.getty.edu/aat/{m.group(1)}" if m else raw_id
        candidates.append({
            "label": r.get("name", ""),
            "uri": uri,
            "description": r.get("description", ""),
        })
    return candidates
```

---

## 7. Clean View — Reconcile Pane Placement

**Recommended placement:** Add a fourth slot to `ColumnWorkspace.tsx` — `reconcilePaneSlot?: React.ReactNode` — injected alongside the existing three slots. This makes reconciliation a peer of transform/cluster/facet, not subordinate to TransformBar.

The "Reconcile column" affordance appears as a distinct section header in the ColumnWorkspace vertical stack, rendered by the `reconcilePaneSlot`:

```
[TransformBar]            ← transformBarSlot
[ReconcilePane]           ← reconcilePaneSlot (NEW)
[ClusterPicker]           ← clusterPickerSlot
[FacetPanel]              ← facetPanelSlot
```

This mirrors the Phase 10 slot pattern exactly — zero coupling, no prop drilling, injected from CleanStep.

**ReconcilePane component (`apps/frontend/src/features/clean/ReconcilePane.tsx`):**
- Shows "Reconcile: {authorityLabel}" header with a "Reconcile column" button
- On click: runs bulk-mode flow for the active column's bound authority
- Progress bar during bulk mode ("Querying 4 / 42 cells...")
- "Needs review" queue count badge — clicking opens the Needs-Review list
- "Clear cache" button

The button is visible only when `activeColumn` has an authority binding (from batch config).

**Inline drawer — `CandidateDrawer` component:**
- Opens below the cell in question (or at fixed position in the ColumnWorkspace)
- Shows top-5 candidates: bold label, gray description, small URI as a clickable link, "Pick this" button
- "No match" button at bottom of candidate list
- "Search again" input lets curator type a refined query without leaving the drawer
- Keyboard: Tab to navigate candidates, Enter to pick, Escape to close

**Needs-review queue:**
- A filtered list of rows in the active column that have been queried (have an audit entry with source `reconciliation-*`) but have no `reconciliation` outcome yet (null reconciliation, not "no-match")
- Rendered as a table-like list inside ReconcilePane when "Needs review" badge is clicked
- Clicking a row in the queue opens the CandidateDrawer for that cell

**Results table per-cell icon:**
- Small `<Link2>` icon in the extraction cell's dd area when `validation[field].reconciliation` is set
- Clicking the icon opens the CandidateDrawer (or a small tooltip-style popover showing label + URI link)
- For Clean view, the same icon in the column cell also triggers the drawer

**Reconciliation badge in Results/Verify:**
- `ValidationBadge` component (`apps/frontend/src/features/results/ValidationBadge.tsx`) needs an extension for reconciliation state
- When `validation[field].reconciliation` is set: show a small `<Link2>` icon (e.g., blue-600) alongside the existing validation status icon
- Tooltip: "Reconciled to {authority}: {label} — {uri}"
- The two badges (validation status + reconciliation) sit side-by-side in the dd cell

---

## 8. Wave Structure and Plan Assignment

Confirmed 5-plan wave structure from the CONTEXT additional_context suggestion (research validates the dependencies):

**Wave 1 (sequential prerequisite — Plan 11-01: Schema + Foundation):**
- Extend `ValidationOutcome` JSON Schema with `reconciliation: ReconciliationOutcome | null`
- Add `ReconciliationOutcome`, `AuthorityBinding`, `AuthorityType` to both JSON Schema files
- Add `authority_bindings` to `BatchConfig`, `BatchCreate`, `Template*` in both schemas
- Regenerate `generated/ts/index.ts`
- Mirror all new Pydantic models in `apps/backend/app/models/schemas.py`
- Update `batchesApi.ts` type copies (CRITICAL — same hazard as Phases 8/9/10)
- Update `wizardStore.ts` `MetadataField` and add `updateFieldAuthority` action
- Snapshot `authority_bindings` into `batch_manager.create_batch()` via `config.json`
- Extend `ResultPatch` with `reconciliation` field
- Update `patch_result` endpoint handler for reconciliation persistence
- Add `authority/cache.py` helpers
- Add `POST /api/v1/reconcile` stub endpoint (route registered, returns empty candidates)
- Add `DELETE /api/v1/batches/{batch_name}/authority-cache` endpoint
- Add `GEONAMES_USERNAME` to `config.py`

**Wave 2 (parallel — Plans 11-02 and 11-03):**

*Plan 11-02: Backend authority clients*
- `apps/backend/app/services/authority/base.py` (fetch_with_retry)
- `apps/backend/app/services/authority/gnd.py`
- `apps/backend/app/services/authority/wikidata.py`
- `apps/backend/app/services/authority/geonames.py`
- `apps/backend/app/services/authority/aat.py`
- Wire all clients into the `POST /api/v1/reconcile` endpoint (replace stub)
- Add `aiohttp` to `requirements.txt` (check if already present)

*Plan 11-03: Configure step AuthorityBindingEditor*
- New `apps/frontend/src/features/configure/AuthorityBindingEditor.tsx`
- Update `FieldManager.tsx` to render `<AuthorityBindingEditor>` per field row
- Update `FieldManager.handleSaveTemplate` to serialize `authority_bindings`
- Update `templatesApi.ts` type copies
- Update `TemplateSelector` hydration to map `template.authority_bindings` to field state
- Update `useWizardStore` to add `updateFieldAuthority` action
- Batch creation wiring: `authority_bindings` sent in `createBatch` payload
- `BatchConfig.authority_bindings` exposed via `GET /api/v1/batches/{batch_name}/config` response (add to GET /config handler)
- `useBatchConfigQuery` already fetches config; `BatchConfig` type needs `authority_bindings` field

**Wave 3 (parallel — Plans 11-04 and 11-05):**

*Plan 11-04: Clean view Reconcile pane + bulk mode + candidate drawer*
- Add `reconcilePaneSlot` to `ColumnWorkspace.tsx` props
- New `apps/frontend/src/features/clean/ReconcilePane.tsx`
- New `apps/frontend/src/features/clean/CandidateDrawer.tsx`
- `reconcileCell` helper (POST to `/api/v1/reconcile`, apply result, PATCH checkpoint)
- Bulk-mode loop with per-authority serialization (one cell at a time per authority)
- Needs-review queue (filtered list of queried-but-unresolved cells)
- `normalizeValue` import for auto-accept exact-match check
- Audit entry emission (reconciliation-auto/manual/no-match)
- Reconciliation clearing on edit (client-side PATCH builder extension)
- `batchesApi.ts`: add `postReconcile(batchName, authority, query)` function + hook

*Plan 11-05: Export URI emission + ReconciliationBadge in Results/Verify*
- Update `useResultsExport.ts`: `downloadLIDO`, `downloadMARCXML`, `downloadDublinCore`
- Add `getReconciliationUri` helper
- Add `uriToMarc0` converter for GND `(DE-588)` vs full URI decision
- Add `xmlns:dcterms` to Dublin Core export namespace
- Update `ValidationBadge.tsx` to show `<Link2>` icon when reconciliation is set
- Add per-cell link icon in `ResultsTable.tsx` / `FieldsPane.tsx`

---

## 9. Pitfall Registry (Planner Must Address in Plans)

### P1: batchesApi.ts type-copy drift (CRITICAL)
Same hazard as Phases 8, 9, 10. The file has LOCAL copies of `ValidationOutcome`, `AuditEntry`, `BatchCreate`, `BatchConfig`. All must be updated in Plan 11-01. Failure to update `ValidationOutcome.reconciliation` here causes a TypeScript compile failure or silent runtime miss.

Files that need updating in Plan 11-01:
- `apps/frontend/src/api/batchesApi.ts` — `ValidationOutcome`, `AuditEntry.op/source`, `BatchCreate`, `BatchConfig`, `patchResult` signature
- `apps/frontend/src/store/wizardStore.ts` — `MetadataField`, `ResultRow.validation` (via re-export of `ValidationOutcome`)
- `apps/frontend/src/api/templatesApi.ts` — `Template`, `TemplateCreate` (check for local copies)

### P2: Wikidata User-Agent header (HIGH)
Without a descriptive User-Agent, Wikidata places requests in the "unidentified" tier (10 req/min as of 2026 rate limit rollout). All Wikidata requests MUST include:
```
User-Agent: IndexcardsOCR/1.0 (contact@thulb.uni-jena.de)
```
Apply this in `wikidata.py` and also in `gnd.py` (Lobid has no stated requirement but it's good practice).

### P3: GeoNames 200-but-error detection (HIGH)
GeoNames returns HTTP 200 even when rate-limited, with a JSON error body `{"status": {"value": 19, "message": "..."}}`. The `geonames.py` client MUST check for `status.value` codes (18, 19, 20, 22) in the response and raise a retriable error. Standard HTTP status checks alone WILL silently return empty results rather than triggering retry.

### P4: GeoNames username missing → 503 error UX (MEDIUM)
`GEONAMES_USERNAME` not in `.env` → `geonames.py` raises ValueError → reconcile endpoint returns HTTP 503. Frontend drawer shows "GeoNames not available (configuration required)". Bulk mode treats as persistent failure → needs review. Planner must spec this error path.

### P5: Getty AAT URI extraction from reconciliation response (MEDIUM)
The Getty reconciliation endpoint returns `id: "aat/300178684"` (relative-ish path, not a full URI). The `aat.py` client must extract the numeric ID and construct `http://vocab.getty.edu/aat/{id}`. The regex `r"aat/(\d+)"` covers the expected format. Edge: if Getty changes the `id` format, the URI construction breaks silently. Add a fallback that uses `id` as-is if the regex doesn't match (plan should note this).

### P6: GND MARC $0 conversion (MEDIUM)
The `reconciliation.uri` field stores `https://d-nb.info/gnd/{id}`. MARCXML $0 must use `(DE-588){id}` not the full URI. The `uriToMarc0()` helper in the LIDO/MARC exporter must detect GND URIs and convert. Full URIs (Wikidata, GeoNames, AAT) go directly into $0.

### P7: Bulk-mode per-authority serialization (MEDIUM)
Different authorities have different rate caps. Bulk mode must serialize requests within each authority, not globally. The frontend implementation should use per-authority sequential loops (one cell at a time per authority) rather than a global sequential queue. If a batch has two fields bound to different authorities, those two columns can reconcile concurrently (one cell at a time each), but cells within one column must be sequential. The CleanStep manages only one active column at a time, so in practice the bulk mode always runs one authority at a time anyway — but the plan should document this.

### P8: Wikidata canonical URI case (LOW)
`concepturi` from wbsearchentities is `http://www.wikidata.org/entity/Q64` (lowercase `entity`, not `wiki/`). This is correct. Do NOT use the `url` field which points to `//www.wikidata.org/wiki/Q64` (the human wiki page, not the entity URI).

### P9: Getty reconciliation POST vs GET (LOW)
The reconciliation spec supports both POST and GET. POST with `application/x-www-form-urlencoded` body is more reliable for queries with special characters. Use POST in `aat.py`. GET can hit URL length limits for long queries.

### P10: Reconciliation clearing on edit — correct PATCH ordering (MEDIUM)
When a curator edits a reconciled cell, the PATCH must set `reconciliation: null` alongside the new value. The CleanStep's `applyTransformOp` → PATCH chain must check: if the new value differs from old AND `row.validation[field]?.reconciliation != null`, include `reconciliation: null` in the PATCH. The `revalidateCell` call returns a new `ValidationOutcome` — but `revalidateCell` doesn't know about `reconciliation`. The PATCH builder must explicitly clear `reconciliation` when value changes.

### P11: EAD/Darwin Core/METS/MODS NOT modified (CRITICAL)
Plans 11-02 through 11-05 must NOT include `downloadEAD`, `downloadDarwinCore`, or `downloadMETSMODS` in `files_modified`. Only `downloadLIDO`, `downloadMARCXML`, `downloadDublinCore` change. The planner must ensure no plan accidentally lists those other functions as modified.

### P12: `aiohttp` dependency check (LOW)
Check if `aiohttp` is already in `apps/backend/requirements.txt`. If not, add it in Plan 11-02. The existing codebase uses `requests` (sync) for OpenRouter calls, not `aiohttp`. The reconcile endpoint runs in a FastAPI async handler, so async HTTP is necessary. Alternative: use `httpx` (async-capable, already popular in FastAPI projects) — check `requirements.txt` for whichever is already present.

---

## 10. Requirement Mapping

- **FR4 (Results Visualization & Export)** — PRIMARY. Authority URIs are emitted in the three export formats (LIDO, MARCXML, Dublin Core). This is the primary output-side deliverable of Phase 11.
- **FR2 (Metadata Field Configuration)** — SECONDARY. Per-field `authority` binding in the Configure step extends field configuration. The `AuthorityBindingEditor` and template round-trip are FR2 deliverables.
- **FR3 (OCR Processing)** — NOT applicable. Reconciliation runs on-demand after extraction, not as part of the OCR pipeline. The `POST /api/v1/reconcile` endpoint is independent of `process_batch`.
- **NFR3 (Security / API keys via env)** — applicable to `GEONAMES_USERNAME`. Must follow the same env-var pattern as `OPENROUTER_API_KEY`.
- **NFR1 (Performance / multi-threaded backend)** — partially applicable. Bulk-mode bulk volume is bounded by the per-batch card count (max ~500 cards) × authority rate limits. No multi-threading needed; per-authority sequential async calls are sufficient.

---

## 11. Open Questions for the Planner

1. **MARCXML subject fields for reconciled data:** Should reconciled subject-heading (GND-subjects, AAT) or place (GND-places, GeoNames) fields get added as MARC 650/651/655 fields with $0 URIs, or should Phase 11 only add $0 to existing hard-coded 100/655 fields? Recommendation: add $0 to existing fields only for v1; dynamic MARC field generation from arbitrary field bindings is a v2 concern.

2. **`GET /api/v1/batches/{batch_name}/config` endpoint and `authority_bindings`:** The current endpoint at batches.py line 251 returns `{ fields, field_rules }`. Plan 11-01 or 11-03 must add `authority_bindings` to this response. Confirm which plan handles this (11-01 as part of schema foundation, or 11-03 as part of Configure frontend wiring).

3. **Reconcile pane in Results/Verify vs Clean-only:** CONTEXT gives Claude's discretion. Recommendation: Clean view for bulk reconciliation, plus a per-cell trigger icon in the Results table extraction dd cell and in FieldsPane. This keeps the bulk workflow in Clean (where the column workspace lives) and allows ad-hoc picks from Results without requiring Clean entry. Plan 11-04 covers Clean; Plan 11-05 covers the Results/Verify icon.

4. **`templatesApi.ts` local type copies:** CONFIRMED — `templatesApi.ts` has a local `Template` interface (line 7) with `field_rules?: Record<string, FieldRule> | null`. It also has inline mutation payload types on lines 30 and 49 that include `field_rules`. All three need `authority_bindings?: Record<string, AuthorityBinding> | null` added. The `FieldRule` type is re-exported from `batchesApi` (imported at line 4), so `AuthorityBinding` should follow the same pattern — import from `batchesApi`. Plan 11-01 must update `templatesApi.ts`.

---

*Phase: 11-authority-reconciliation*
*Research complete: 2026-05-18*
