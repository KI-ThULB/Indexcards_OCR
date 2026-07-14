# Architecture

This document describes the monorepo layout, the data flow through the app, and the key components per workflow phase.

## Monorepo layout

```
apps/
├── backend/                  FastAPI service
│   ├── app/
│   │   ├── api/api_v1/       Routes: config, upload, batches, templates, reconcile, ws
│   │   ├── core/             config.py (pydantic-settings), env loading
│   │   ├── models/           schemas.py (Pydantic models)
│   │   └── services/
│   │       ├── ocr_engine.py         Qwen3-VL via OpenRouter
│   │       ├── batch_manager.py      Upload lifecycle, batch creation
│   │       ├── template_service.py   Template CRUD
│   │       ├── ws_manager.py         WebSocket progress broadcaster
│   │       ├── validation/           Field-rules engine (regex + vocab + corrector)
│   │       └── authority/            GND, Wikidata, GeoNames, AAT clients + cache
│   ├── data/                 Runtime data (gitignored; created at startup)
│   └── requirements.txt
├── frontend/                 React 19 + Vite 7 + Tailwind 3
│   ├── src/
│   │   ├── App.tsx           Top-level view router (wizard | history)
│   │   ├── store/            Zustand store (wizardStore.ts)
│   │   ├── api/              TanStack Query hooks (configApi, batchesApi, templatesApi, uploadApi)
│   │   ├── components/       Sidebar, Header, WizardNav, Footer
│   │   └── features/
│   │       ├── upload/       Dropzone + UploadStep
│   │       ├── configure/    FieldManager, ValidationRuleEditor, AuthorityBindingEditor, ConfigureStep
│   │       ├── processing/   ProgressBar, LiveFeed, ProcessingStep
│   │       ├── results/      ResultsTable, ValidationBadge, ValidationFilterChips, SummaryBanner, useResultsExport
│   │       ├── verify/       CockpitLayout, ImagePane, Filmstrip, FieldsPane, CockpitBadge, useVerifyKeyboard
│   │       ├── clean/        CleanStep, ColumnList, ColumnWorkspace, AuditPanel, ClusterPicker, FacetPanel, TransformBar, ReconcilePane, CandidateDrawer
│   │       └── history/      BatchHistoryDashboard
│   └── vite.config.ts
└── legacy/                   Original Python batch script (preserved; not used by the web app)

packages/
└── shared-types/             JSON Schema → TypeScript + Pydantic codegen
    ├── schemas/              .schema.json source files (batch, template, upload, progress, health)
    ├── scripts/generate.mjs  Custom codegen (enum → TS union literals; preserves frontmatter)
    └── generated/            ts/ + py/ outputs (committed)

.planning/                    Phase-by-phase planning records (CONTEXT/RESEARCH/PLAN/SUMMARY/VERIFICATION)
docs/                         User-facing documentation
```

## Wizard flow

The app is a six-step linear wizard with two optional steps:

```
Upload → Configure → Processing → Results → [Verify] → [Clean] → Export
                                       ↑                              ↓
                                       └──────── exports ─────────────┘
```

`WizardStep` is a Zustand union: `'upload' | 'configure' | 'processing' | 'results' | 'verify' | 'clean'`. Step transitions only happen through Zustand actions to enforce wizard order. The Sidebar displays steps but clickability is guarded by `batchId` for `'results'`, `'verify'`, and `'clean'`.

The top-level view is `AppView`: `'wizard' | 'history'`. The Header toggles between the active wizard and the Batch History dashboard.

## Data shape

The single canonical record is `ExtractionResult` (one per card):

```typescript
type ExtractionResult = {
  filename: string
  status: 'completed' | 'failed' | 'pending'
  data: Record<string, string>         // VLM-extracted values
  edited_data?: Record<string, string> // Curator overrides, persisted via PATCH
  validation?: Record<string, ValidationOutcome>
  _entries?: string                    // Multi-entry cards (JSON-encoded array)
  _entry_count?: number
  duration?: number
  error?: string
}

type ValidationOutcome = {
  status: 'valid' | 'invalid' | 'corrected' | 'verified' | 'skipped'
  rule_failed?: string                 // Which rule the value violated
  vlm_value?: string                   // Original VLM output before edits
  corrector_proposal?: string          // LLM-corrector suggestion (Phase 8)
  corrector_rationale?: string
  reconciliation?: ReconciliationOutcome | null  // Authority URI (Phase 11)
}

type ReconciliationOutcome = {
  authority: 'gnd-persons' | 'gnd-places' | 'gnd-subjects' | 'gnd-corporate-bodies' | 'gnd-works' | 'wikidata' | 'geonames' | 'aat'
  uri: string
  label: string
  picked_by: 'auto' | 'manual'
  picked_at: string  // ISO date
}
```

`status` is a single enum with five values; `reconciliation` is an independent dimension. A cell can be `verified` AND reconciled, or `invalid` and reconciled, or any combination.

## Persistence: `checkpoint.json`

Every batch has a `checkpoint.json` file under `data/batches/{batch_name}/`. Shape since Phase 10:

```json
{
  "results": [ExtractionResult, ...],
  "audit": [AuditEntry, ...]
}
```

Old batches with the flat-array shape auto-migrate on first read via the shared `read_checkpoint()` / `write_checkpoint()` helpers in `apps/backend/app/api/api_v1/endpoints/batches.py`. All four endpoints that touch `checkpoint.json` (`GET /results`, `PATCH /results/{filename}`, `POST /revalidate`, `POST /retry-image/{filename}`) use these helpers.

`AuditEntry`:

```typescript
type AuditEntry = {
  ts: string                           // ISO timestamp
  op: 'bulk-transform' | 'cluster-merge' | 'reconciliation' | ...
  source: 'vlm-original' | 'cockpit-edit' | 'bulk-transform' | 'cluster-merge'
        | 'reconciliation-auto' | 'reconciliation-manual'
        | 'reconciliation-cleared-by-edit' | 'reconciliation-no-match'
  field?: string
  before?: string
  after?: string
  // ... operation-specific keys
}
```

The audit log gives institutional curators full provenance: every change to every cell is recorded with timestamp and source.

## Persistence: `config.json`

Per batch, captures the snapshot of the batch configuration at creation time:

```json
{
  "fields": ["Object Name", "Inventory No", ...],
  "prompt_template": null | "...",
  "field_rules": { "Inventory No": {"type": "regex", "pattern": "^INV-\\d+$"}, ... },
  "authority_bindings": { "Artist": {"type": "gnd-persons"}, ... },
  "corrector_enabled": false,
  "corrector_cap": 100,
  "describe_pictures": false,
  "ocr_provider": "openrouter",
  "ocr_model": "qwen/qwen3-vl-...",
  ...
}
```

Once a batch is created, this snapshot is immutable. Editing fields, rules, or bindings in Configure affects only future batches. When `describe_pictures` is on, the engine appends a `Bildbeschreibung` field to the effective field list so the model is asked to describe any picture on the card.

## VLM response contract (confidence)

`ocr_engine._generate_prompt` instructs the model to return a **wrapped** object carrying values plus self-reported confidence:

```json
{
  "fields": { "Komponist": "Bach, J.S.", ... },
  "confidence": { "Komponist": 0.95, ... },     // 0.0–1.0 per field
  "confidence_overall": 0.78                      // 0.0–1.0 per card
}
```

Parsing (`ocr_engine._split_extraction`) is **defensive**: a model that ignores the contract and returns a flat `{field: value}` object is treated as fields-only with no confidence, so extraction never breaks on response shape. Confidences are clamped to `[0,1]`, non-numeric values dropped, and keys not present in `fields` ignored. Confidence is stored on the `ExtractionResult` (`confidence`, `confidence_overall`) separate from `data`, so it never pollutes exported metadata values (CSV/JSON carry it in dedicated columns; XML formats stay value-only). Multi-entry pages skip confidence in v1.

## Persistence: `authority_cache.json`

Per batch, sibling to `checkpoint.json`. Shape:

```json
{
  "gnd-persons:johann wolfgang von goethe": [
    {"label": "Goethe, Johann Wolfgang von", "uri": "https://d-nb.info/gnd/118540238", "description": "..."},
    ...
  ],
  "wikidata:berlin": [],   // Empty array = "queried, no candidates"
  ...
}
```

Keyed by `<authority>:<normalized_query>` where normalisation matches the Phase 8 vocab rules (NFC + ß→ss + casefold + NFD + strip-combining-marks + NFC). No TTL; manual "Clear cache" button per batch.

Writes are atomic (tmp-file + rename) for safety under concurrent bulk-reconcile requests.

## OCR pipeline

```
process_batch(batch_dir, fields, prompt_template, field_rules, corrector_enabled, ...)
  │
  ├─ ThreadPoolExecutor with N workers (configurable)
  │   └─ for each card image:
  │       └─ _process_card_sync(image_path, config)
  │           ├─ _call_vlm_api_resilient(image, prompt, provider, model)
  │           │   ├─ Build prompt from template + field list ({{fields}} substitution)
  │           │   ├─ POST to provider (OpenRouter / Ollama via _resolve_provider)
  │           │   ├─ Retry strategy: 401 exit, 5xx backoff, 4xx exit, ConnectionError/Timeout retry
  │           │   └─ Parse JSON response, detect multi-entry (isinstance(data, list))
  │           ├─ run_validation(extracted, field_rules, corrector_enabled, cap_state)
  │           │   ├─ For each field with a rule: regex test, then vocab match
  │           │   └─ On failure with corrector_enabled: fire cheap text-only model (capped)
  │           ├─ Write result to checkpoint.json (via write_checkpoint helper)
  │           └─ Broadcast progress over WebSocket via captured event loop
  └─ When complete: final BatchProgress broadcast (status: completed | cancelled | failed)
```

Cancellation uses `threading.Event` (thread-safe from worker threads, unlike `asyncio.Event`). On any error path, `run_ocr_task` broadcasts a terminal status with a fallback `BatchProgress` to ensure the frontend always sees an end state.

## Authority pipeline

Four backend clients in `apps/backend/app/services/authority/`:

| Client | Endpoint | Auth | Rate limit handling |
|--------|----------|------|---------------------|
| `gnd.py` | Lobid REST | None | base.py exponential backoff (429/5xx) |
| `wikidata.py` | `wbsearchentities` | None (User-Agent required) | Proactive `asyncio.Lock` + `MIN_INTERVAL_SECONDS = 6` (10 req/min anonymous policy) |
| `geonames.py` | `searchJSON` | `GEONAMES_USERNAME` env var | Body-level retry: HTTP 200 with `status.value ∈ {18, 19, 20, 22}` → backoff and retry (NOT delegated to base.py) |
| `aat.py` | W3C Reconciliation API v0.2 | None | base.py 429 backoff; ID extraction `^aat/(\d+)$` → `http://vocab.getty.edu/aat/{id}` |

All four route through a single endpoint: `POST /api/v1/reconcile` with body `{authority, query}`. Cache check before external call; cache write after successful response (including empty-array no-match results).

## OCR provider configuration (runtime)

The app supports two OCR providers — **OpenRouter** (cloud) and **Ollama** (self-hosted VLM). Every institution can point the app at their own Ollama instance **purely through the backend `.env`** — no code change and no frontend rebuild. See [`GETTING_STARTED.md`](./GETTING_STARTED.md#using-your-own-ollama-instance) for the operator-facing variable reference.

**Backend settings** (`apps/backend/app/core/config.py`, all env-overridable via `pydantic-settings`):

| Setting | Purpose |
|---------|---------|
| `OLLAMA_BASE_URL` | Base URL of the Ollama server (HTTP or HTTPS). The chat (`/v1/chat/completions`) and model-listing (`/v1/models`) endpoints are derived from it. |
| `OLLAMA_API_ENDPOINT` (legacy) | Full chat URL. Still honored via an `AliasChoices` override for backward compatibility with older `.env` files; if set it wins over the derived value. |
| `OLLAMA_MODEL_NAME` | Default model pre-selected in the UI. |
| `OLLAMA_API_KEY` | Bearer token (backend-only; for a reverse proxy in front of Ollama). |
| `OLLAMA_ENABLED`, `OLLAMA_LABEL`, `OLLAMA_ENDPOINT_HINT` | UI presentation of the provider. |
| `OLLAMA_MODEL_ALLOWLIST` | Explicit comma-separated model allow-list. |
| `OLLAMA_VISION_FILTER`, `OLLAMA_VISION_KEYWORDS` | Default vision-capable model heuristic (see below). |

**Config API** (`apps/backend/app/api/api_v1/endpoints/config.py`, consumed by `apps/frontend/src/api/configApi.ts`):

- `GET /api/v1/config` — non-sensitive, UI-facing provider descriptors (label, endpoint hint, default model, enabled flag). **No base URLs, no credentials.** Lets the same built frontend be deployed by different institutions.
- `GET /api/v1/config/ollama/models` — the backend fetches the installed model list from the configured Ollama server **server-side** (the browser never contacts Ollama directly), applies filtering, and returns `{models, reachable, error}`. A connection failure returns `reachable: false` with a message so the UI can offer a free-text model field instead of breaking.

**Model filtering priority** (in `_filter_models`): explicit `OLLAMA_MODEL_ALLOWLIST` → vision-keyword heuristic (default on) → full list. A filter that would leave the list empty falls back to the full list, so the dropdown is never blank.

## Frontend state

Zustand single-store pattern. The store lives in `apps/frontend/src/store/wizardStore.ts`. Partialized (persisted to localStorage) keys:

```
files                      Uploaded file metadata (not blobs — those are blob URLs created on upload)
fields                     Current MetadataField[] in Configure
selectedTemplateName       For TemplateSelector restoration
promptTemplate             Custom prompt template (null = use backend default)
correctorEnabled, correctorCap
batchId, batchName, step, view
results                    Hydrated from REST (GET /results), not WebSocket
editedData                 Per-row, per-field curator overrides
cockpitSplitPercent        Verify cockpit drag-handle position
```

Excluded from partialize (intentionally ephemeral):

```
processingState            Live progress; rebuilds from WebSocket on reconnect
undoStack                  Clean view per-session operation stack
cockpit transient state    activeCardIndex, zoom, filter, active tab
```

## TypeScript ↔ Python type sync

`packages/shared-types/schemas/*.schema.json` is the intended single source of truth. `packages/shared-types/scripts/generate.mjs` produces `generated/ts/index.ts` (frontend) and `generated/py/*.py` (backend Pydantic).

**Caveat for the current state (Phase 13 will address):** The frontend code imports types from `apps/frontend/src/api/batchesApi.ts` and `apps/frontend/src/store/wizardStore.ts` — hand-maintained type copies. The backend imports from `apps/backend/app/models/schemas.py` — also hand-maintained. The generated/ directories exist and are correct but are not yet wired into either app's import chain. Some types added in Phases 9–11 (`AuditEntry`, `ResultPatch`, `AuthorityBinding`, `ReconciliationOutcome`) live only in the hand-written files and were never added to the JSON Schema.

If you modify schemas: edit the .schema.json source, run `node packages/shared-types/scripts/generate.mjs`, then mirror the change manually to `batchesApi.ts` and `schemas.py` until the pipeline is re-adopted.

## Phase index

The codebase grew through 12 numbered phases. Each phase is documented in `.planning/phases/{N}-.../`:

| Phase | Subject | Key artefacts |
|-------|---------|---------------|
| 01 | Backend foundation | FastAPI, OcrEngine, BatchManager, TemplateService, WebSocket |
| 02 | Frontend scaffold + Configure step | Vite + Tailwind, Parchment theme, Dropzone, FieldManager |
| 02.1 | Turborepo + shared-types codegen | monorepo restructure |
| 03 | Processing + Results | WebSocket hook, ProgressBar, LiveFeed, ResultsTable, CSV/JSON export |
| 03.1 | Dynamic prompt template | `{{fields}}` substitution, PromptTemplateEditor |
| 06 | Feature merge | Provider selection (Ollama), OCR resilience, multi-entry, 8 XML exports, ThULB branding |
| 07 | UAT bug fixes | 14 bug fixes across 4 clusters |
| 08 | Validation rules engine | FieldRule, ValidationOutcome, run_validation, corrector, ValidationBadge, FilterChips, soft-block gate |
| 09 | Verification cockpit | VerifyStep, CockpitLayout, ImagePane wheel-zoom, FieldsPane, useVerifyKeyboard, `verified` status |
| 10 | OpenRefine cleaning stage | CleanStep, fingerprint clustering, transforms, undo, persistent audit log |
| 11 | Authority reconciliation | 4 authority clients, ReconcilePane, CandidateDrawer, URI emission in LIDO/MARC/DC |
| 12 | Cross-phase integration fixes | Gap closure for v1.0 milestone audit (template_service authority_bindings, CleanStep clear_reconciliation, CockpitBadge Link2 icon, edited_data round-trip) |

See [.planning/ROADMAP.md](../.planning/ROADMAP.md) for the full roadmap and per-phase plan listings.
