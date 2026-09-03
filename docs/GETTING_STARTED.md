# Getting Started

This guide walks you through installing Indexcards OCR locally and running your first batch.

## Prerequisites

- **Node.js 20 or later** (check with `node --version`)
- **Python 3.10 or later** (check with `python3 --version`)
- **uv** — Python package manager (`pip install uv` or see <https://docs.astral.sh/uv/>)
- **An OpenRouter API key** — sign up at <https://openrouter.ai>; pay-as-you-go pricing applies
- *(Optional)* A free **GeoNames username** if you want GeoNames authority reconciliation. Sign up at <https://www.geonames.org/login>.

The app is developed and tested on macOS. Linux should work identically. Windows has not been verified.

## Install

```bash
git clone https://github.com/KI-ThULB/Indexcards_OCR.git
cd Indexcards_OCR
npm install
```

`npm install` runs in the monorepo root and bootstraps both `apps/frontend` and `apps/backend` through Turborepo workspaces. The Python venv at `apps/backend/.venv` is created on first `npm run dev`.

## Configure

```bash
cp .env.example .env
```

Edit `.env` and set the required key:

```
OPENROUTER_API_KEY=sk-or-v1-...your-key...
```

Optional environment variables:

```
# Optional: enable GeoNames authority reconciliation
# GEONAMES_USERNAME=your_geonames_username

# Optional: override the LLM-corrector model (default is a cheap text-only OpenRouter model)
# CORRECTOR_MODEL_NAME=...
```

### Using your own Ollama instance

The app can run OCR against a self-hosted [Ollama](https://ollama.com) server instead of
OpenRouter. **Every institution can point at their own Ollama purely through the backend
`.env` — no code change and no frontend rebuild.** The frontend reads the non-sensitive
parts at runtime from `GET /api/v1/config`, so the same built frontend can be deployed by
different institutions.

Add to your `.env` (all optional — shown with defaults):

```
# Base URL of your Ollama server (OpenAI-compatible API). HTTP or HTTPS.
OLLAMA_BASE_URL=http://localhost:11434

# Default model pre-selected in the UI when Ollama is chosen
OLLAMA_MODEL_NAME=qwen3-vl:235b

# Bearer token, only if a reverse proxy in front of Ollama requires one
OLLAMA_API_KEY=your-ollama-token

# Show/hide the Ollama provider in the UI
OLLAMA_ENABLED=true

# Cosmetic UI strings (safe for the browser — never the real URL)
OLLAMA_LABEL=Ollama (self-hosted)
OLLAMA_ENDPOINT_HINT=Lokal · on-premise

# Explicit allow-list: only these exact model ids are offered (comma-separated).
# Empty = use the vision filter below instead.
# OLLAMA_MODEL_ALLOWLIST=qwen3-vl:235b,qwen2.5vl:72b

# Vision filter (default ON): with no explicit allow-list, only show
# vision-capable models — OCR needs a VLM. Hides embedding/coder/text models.
OLLAMA_VISION_FILTER=true
# Substrings that mark a model id as vision-capable (extend for local naming).
OLLAMA_VISION_KEYWORDS=vl,vision,llava,-ocr,ocr:,minicpm-v,pixtral,granite3.2-vision,gemma3
```

Notes:

- **The browser never contacts Ollama directly.** `OLLAMA_BASE_URL` and `OLLAMA_API_KEY`
  stay backend-only; the model list is fetched server-side and proxied to the UI.
- The Configure step **auto-discovers installed models** from your server. If the server
  is unreachable, the UI shows a warning and lets the curator type a model id manually —
  OCR still works.
- **Model filtering priority:** explicit `OLLAMA_MODEL_ALLOWLIST` → vision filter (default)
  → full list. A filter that would remove *every* model falls back to the full list, so the
  dropdown is never empty. Ollama servers often host dozens of non-vision models (embeddings,
  coders); the vision filter keeps the picker focused on models that can actually do OCR.
- Restart the backend after editing `.env` (the dev server auto-reloads on file changes).

### Data protection: retention & audit log (GDPR)

For local single-curator use you need **none** of this — it is off by default. For a
networked/institutional deployment (behind an authenticating reverse proxy), the app
supports GDPR obligations without any application-level encryption:

- **Encryption at rest** is provided by the infrastructure (LUKS / BitLocker / FileVault /
  encrypted volume) — mount `apps/backend/data/` on the encrypted disk. The app does not
  encrypt files itself.
- **Retention** (`RETENTION_DAYS`, off by default) auto-purges the working data of
  *completed* batches after N days; `AUTO_PURGE_AFTER_EXPORT=true` purges a batch after its
  final METS/MODS ingest export. Preview what would be deleted with
  `GET /api/v1/batches/retention/preview`; purge a single batch immediately with
  `POST /api/v1/batches/{batch}/purge`. Active and exporting batches are never purged, and a
  minimal non-sensitive tombstone is kept for accountability.
- **Audit log** (`AUDIT_ENABLED`, on by default) writes an append-only JSONL record of
  security events (start/cancel/delete/export/purge/config changes/auth failures). It never
  contains OCR text, metadata or secrets. Per-user accountability requires the reverse proxy
  to forward a verified SSO identity — see the full setup in
  [DEPLOYMENT.md → Data protection](DEPLOYMENT.md#data-protection-gdpr).

**Never commit `.env`** — it is excluded by `.gitignore`. Only `.env.example` ships with the repo.

## Run

```bash
npm run dev
```

This launches:

- Frontend: <http://localhost:5173> (Vite)
- Backend: <http://localhost:8000> (uvicorn with `--reload`)

Both run in parallel under Turborepo with combined log output. Press `Ctrl+C` once to stop both.

If port 5173 or 8000 is already in use, the dev script aborts with a clear error message.

## Your first batch

1. Open <http://localhost:5173>. You land on the **Upload** step.
2. Drag 1–3 JPG scans of index cards into the dropzone. Files appear immediately as table rows.
3. Click **Next** to advance to **Configure**.
4. **Field setup:** the default fields are loaded from `data/templates.json`. Add or remove fields as needed. Each field row exposes:
   - **Validation Rule** (Phase 8) — optional. Pick a regex preset (Year, Year Range, ISO Date, German Date, GND ID, RKD ID, AAT ID, VIAF ID, custom regex with prefix builder), or a vocabulary list (case-insensitive exact match with optional fuzzy distance).
   - **Authority Binding** (Phase 11) — optional. Pick from None / GND-Persons / GND-Places / GND-Subjects / GND-CorporateBodies / GND-Works / Wikidata / GeoNames / Getty AAT.
5. *(Optional)* Expand the **Prompt Template** editor to customise the OCR prompt; use `{{fields}}` as a placeholder for the field list.
6. *(Optional)* Toggle **Enable LLM correction** and set a per-batch call cap if you want the corrector to propose fixes when validation rules fail.
6a. *(Optional)* Toggle **„Bilder auf den Karten beschreiben“** to have the model detect any picture/drawing/photo on a card and add a short description in a dedicated `Bildbeschreibung` field. Off by default; adds no cost to text-only cards beyond a slightly larger prompt.
7. Click **Save Template** to persist the field set + rules + bindings for reuse.
8. Click **Start Processing**. The wizard advances to **Processing**.
9. Watch the progress bar and live feed. Each card streams its extracted fields as it completes. Cancel with the toolbar button if needed.
10. When extraction finishes, the wizard advances to **Results**. The table shows:
    - One row per card (multi-entry cards expand into sub-rows).
    - Inline-editable cells (auto-resizing textarea; `Ctrl+Enter` commits, `Esc` cancels, plain `Enter` inserts newline).
    - Per-cell validation badges and tooltips.
    - **Confidence scores**: a colour-banded per-field chip (green ≥85%, amber ≥60%, red below) and a sortable **"Ø Konf."** column with the card-level overall — click the column header to bring the least-confident cards to the top for review.
    - Filter chips (All / Invalid / Corrected / Verified OK / Auto-corrected).
    - Status colour-coded chip per row.
    - Image thumbnail with click-to-open lightbox.
    - A `Bildbeschreibung` column when picture description was enabled.
11. Click **Download** to export. Available formats: CSV, JSON, LIDO, MARCXML, Dublin Core, EAD, Darwin Core, METS/MODS. If any rows have status `invalid`, a soft-block sonner toast asks for confirmation before downloading.

## Optional next steps

### Verify cards one by one (Phase 9)

From Results, click **Verify cards**. The cockpit opens with a 50/50 split:

- **Left** — the original card image with wheel-zoom (scroll to zoom toward the cursor, drag to pan, double-click to reset).
- **Right** — the extracted fields, inline-editable. Status badges per field. A bottom filmstrip lets you jump to any card.
- **Keyboard shortcuts:** `J` / `K` next/previous card; `Tab` / `Shift+Tab` next/previous field; `V` mark current field verified; `Enter` accept the corrector proposal if present; `Esc` exit the active edit.
- Edits auto-save via debounced PATCH; status auto-flips to `verified` when the value changes.
- Click **Back to Results** when done.

### Column-wise cleaning (Phase 10)

From Results or Verify, click **Clean columns**. The Clean view opens with:

- **Left sidebar** — one row per extracted field with row-count and unique-value count.
- **Main pane** — the active column, with three tools:
  - **Cluster picker:** OpenRefine-style fingerprint clustering of near-duplicate values. Each cluster shows the variants, row count, an editable canonical value, and Apply / Skip buttons.
  - **Facets:** Text facet (frequency-sorted unique values, click to filter) and Pattern facet (regex with try/catch guard against malformed input).
  - **Transforms:** Trim, Upper, Lower, Title Case, Collapse-whitespace, Regex Replace (find/replace with capture groups), Set-to-NULL. Operate on currently-faceted rows. 100+ row operations trigger a confirmation toast.
- **Audit panel** (bottom or right, collapsible) — every operation, most recent first, with per-entry Undo. Audit log persists to `checkpoint.json`.

### Authority reconciliation (Phase 11)

In the Clean view, the **Reconcile pane** appears for columns that have an authority binding configured. Two modes:

- **Per-cell:** click the reconcile icon on any cell. A drawer opens below with the top 5 candidates from the bound authority. Pick one, click No-match, or search again with a different query.
- **Bulk column:** click Reconcile column. Cells whose value matches exactly one candidate after normalisation auto-accept; ambiguous cells go to a Needs-review queue. Operations over 100 rows ask for confirmation.

Reconciled URIs flow into LIDO `<lido:conceptID>`, MARCXML `$0` subfield (with `(DE-588)` prefix for GND), and Dublin Core `<dcterms:identifier>` on export.

See [docs/AUTHORITY_SETUP.md](AUTHORITY_SETUP.md) for credentials and rate-limit details.

## Bulk / multi-batch processing

*Opt-in. Off unless `BULK_IMPORT_ROOT` is set — with it unset the API returns 404 and the
UI shows no trace of the feature.*

The standard workflow processes **one** batch at a time and stops for quality control
before results are exported. That is right for careful single-batch curation, but it makes
large homogeneous collections impractical: every folder needs its own "Commence
Processing" click and its own CSV export, which then has to be merged by hand.

Bulk mode orchestrates the **same** batch engine sequentially across many source folders
and produces one consolidated CSV:

```
Bulk run
  → folder 1  (an ordinary batch)
  → folder 2  (an ordinary batch)
  → …
  → one consolidated CSV, with source-folder and source-filename provenance
```

Nothing is replaced. Each folder becomes a normal batch that appears in the Batch Archive
and can be inspected, verified, cleaned, exported and purged individually. Per-card QC data
is still written for every card — only the *mandatory stop between folders* is skipped.

### The example this was built for

> 28 folders containing approximately 500 homogeneous machine-written historical index
> cards each can be processed sequentially using one tested extraction template. No
> intermediate QC stop is required, and all extracted records are consolidated into a
> final CSV while preserving source-folder and source-filename provenance.

### When to use it — and when not to

| Use bulk mode | Do **not** use bulk mode |
|---|---|
| Homogeneous collection, one card type | Mixed layouts or card types in one run |
| Template already tested on a sample | Untested or newly written template |
| Per-folder human QC not required | Every record must be curator-approved before export |
| Results will be validated before authoritative ingest | Output feeds an authoritative system unvalidated |

> **Bulk mode is intended for homogeneous collections with a previously tested extraction
> template. Intermediate manual quality control is skipped. Results should be validated
> before publication or ingest into authoritative systems.**

Test your template on a handful of cards through the normal workflow first. A template that
is wrong for the collection will be wrong for all 14,000 cards.

### Configure the import root

Bulk mode reads images from a directory the **backend process** can see, so tens of
thousands of files never travel through the browser. Point `BULK_IMPORT_ROOT` at a directory
whose *immediate* subfolders each hold one collection:

```
/srv/scans/amiga-tonbandkartei/
├── Batch_001/        ← offered in the UI
│   ├── IMG_0001.JPG
│   └── …
├── Batch_002/        ← offered in the UI
└── …
```

```bash
# .env
BULK_IMPORT_ROOT=/srv/scans/amiga-tonbandkartei

# Optional (defaults shown)
BULK_IMPORT_MODE=hardlink          # or "copy"
BULK_CONTINUE_ON_BATCH_ERROR=true
BULK_MAX_FOLDERS=200
RATE_LIMIT_BULK_START=6/minute
```

Restart the backend. **Bulk Processing** then appears in the sidebar.

Notes:

- Only immediate subfolders are offered — there is no recursion into nested directory
  trees in this version.
- Extensions are matched case-insensitively, so `.JPG`, `.jpeg` and `.TIFF` all work.
- The client only ever sends folder *names* chosen from the backend's listing; arbitrary
  filesystem paths are never accepted, and the root path is never sent to the browser.
- **Source folders are only ever read.** They are never modified, moved or deleted, and
  their files remain byte-identical throughout. See
  [DEPLOYMENT.md](DEPLOYMENT.md#bulk-import-root-hardlinks-and-immutability).

### Run it

1. **Bulk Processing** in the sidebar.
2. Tick the source folders. Each row shows its supported-image count.
3. Choose the already-tested extraction template.
4. Choose provider and model.
5. Give the run a name (a label for the run and its download — never a file path).
6. Review folder count, image count and the reminder that intermediate QC is skipped.
7. **Start bulk run.**
8. Watch progress: folders completed, current folder, images in that folder, images
   overall, failed images, elapsed time and status, with a per-folder breakdown.
   **Pause**, **Resume** and **Cancel** are available while it runs; completed results are
   always kept.
9. When it finishes, download the **consolidated CSV** (and the failed-records CSV if any
   cards failed).

Closing or reloading the browser does not affect the run — reopening the view re-attaches
to it.

### If the backend restarts mid-run

The run is *not* resumed automatically. That is deliberate: an unattended crash-loop or a
routine redeploy must never silently restart hours of model spend.

On startup, a run that was processing is marked **interrupted**, and the UI shows the last
folder, the last image and the interruption timestamp so you can check where it stopped.
Click **Resume** to continue:

- folders already completed are skipped entirely,
- within the interrupted folder, cards that were already extracted are **not** sent to the
  model again,
- the remaining folders proceed in order.

The same applies after a **Pause**.

### The consolidated CSV

One row per record, every row traceable to its scan:

```
bulk_run_id, source_folder, source_filename, batch_id,
File, Status, Error, Duration(s), Confidence_overall,
<Field>_ocr, <Field>_edited, <Field>_confidence, …
```

The columns are fixed when the run is created, so editing the template later cannot shift
them mid-run. A record missing a field gets an empty cell; unexpected extra fields never
add columns. Folders appear in processing order and files in filename order, so the export
is reproducible. Cards holding several entries (the Findmittel case) expand to one row per
entry, which is why the row count can exceed the image count.

Same conventions as the per-batch CSV export: UTF-8 BOM for Excel, CRLF line endings, every
cell quoted.

### Limitations

- A backend restart interrupts a run by design; resuming is an explicit human action.
- Hardlink import needs the source and `DATA_DIR` on the same filesystem, otherwise it
  falls back to copying (extra disk use).
- The import root must be reachable by the backend process — no remote/S3/object-store
  sources.
- Only immediate subfolders; no recursion in this version.
- Folders are processed sequentially; there is no cross-folder parallelism.
- When a pause or cancel lands, cards already in flight in the worker pool are discarded
  and re-processed on resume (at most `MAX_WORKERS - 1` cards).
- A paused folder's batch shows as `cancelled` in the Batch Archive until the run resumes
  and completes it. This is cosmetic.
- Provider cost is not reported, because the application does not track it.

## Repeatable field groups

Most template fields hold a single value. Some cards, though, repeat a small record several
times — and flattening that loses data.

The AMIGA Tonband-Karteikarte is the case this was built for. One card carries:

```
Gesamttitel:   Gershwin - Evergreens

1 | The Man I Love | 3'21
2 | I Got Rhythm   | 2'48
3 | Summertime     | 4'06

Gesamtspieldauer: 10'15
```

A flat template reduces this to `Titel = "Gershwin - Evergreens"` and
`Spieldauer = "10'15"` — every track is gone. A **repeatable group** keeps the
title↔duration pairing intact.

### Creating one

In **Configure**, type a name and press the **layers** button instead of the plus button.
The field appears as a group and expands so you can add the fields that make up **one**
entry:

```
▸ Bestellnummer                    (normal field)
▸ Gesamttitel                      (normal field)
▾ Titel_Tracks       [Gruppe · max. 20]
    ├─ Lfd_Nr
    ├─ Titel
    └─ Spieldauer
▸ Gesamtspieldauer                 (normal field)
```

Child fields can be named, described, reordered and removed. The description is passed to
the model, so it is worth being explicit — "the individual title of this row, not the
overall title" measurably helps.

A ready-made **AMIGA Tonband-Karteikarte** template ships with the application, with
`Titel_Tracks` already configured. The older flat `AMIGA Tonbandkartei` template is kept as
it is, so existing batches are unaffected; pick the new one for new runs.

### What the model is told

For every group the generated prompt states that zero, one or many entries may exist, that
**all** of them must be extracted in document order, that values in the same visual row
belong in one entry, that a missing value must be left **empty** rather than pulling the
next row's value up, and that nothing may be invented or calculated.

Where a normal field's name contains a child's name — `Gesamttitel` and `Titel`,
`Gesamtspieldauer` and `Spieldauer` — the prompt adds that they are different things and
that the overall value must **never** cause the individual ones to be omitted.

### Curating entries

The **Verify** cockpit shows a group as a list of entries:

```
Titel_Tracks                       3 Einträge   [+ Eintrag]

#1                                    [↑] [↓] [✕]
  Lfd_Nr        1
  Titel         The Man I Love     92%
  Spieldauer    3'21               88%

#2                                    [↑] [↓] [✕]
  Lfd_Nr        2
  Titel         I Got Rhythm       95%
  Spieldauer    2'48
```

Values are edited in place; entries can be added, removed and reordered. Structural changes
are recorded in the batch's audit log. Edits survive navigation, reload and export.

Column-wise cleaning in **Clean** does not apply to group fields — clustering or a regex
replacement over a repeating structure has no clear meaning — so groups are curated in
Verify.

### In the CSV export

One row per card, as always. A group expands into deterministic numbered columns:

```
Titel_Tracks_count,
Titel_Tracks_1_Lfd_Nr_ocr, Titel_Tracks_1_Lfd_Nr_edited, Titel_Tracks_1_Lfd_Nr_confidence,
Titel_Tracks_1_Titel_ocr,  …
…
Titel_Tracks_20_Spieldauer_confidence,
Titel_Tracks_overflow_json
```

- `Titel_Tracks_count` is the **real** number of entries, even when it exceeds 20.
- Columns exist for the first `max_items` entries (20 for AMIGA, 12 for a new group).
- Anything beyond that is preserved verbatim in `Titel_Tracks_overflow_json` — **never
  silently dropped**.
- A missing value is an empty cell. No duration is ever calculated.

This makes for a wide file: the AMIGA group alone adds 182 columns. That is the price of
keeping every track addressable in a spreadsheet.

Bulk runs work the same way and freeze the group definitions when the run is created, so a
later template edit cannot change the export's shape mid-run.

### Limitations

- Groups cannot be nested; children are single values.
- `max_items` bounds the *columns*, not the data — the overflow column and the count keep
  everything.
- Per-entry confidence appears only when the model reports it.
- Group fields are not offered in Clean, and the XML export formats are not group-aware in
  this version (CSV is the target format for this collection).

## Data locations

- `apps/backend/data/temp/` — per-session staged uploads (cleaned up automatically after 24h).
- `apps/backend/data/batches/{batch_name}/` — committed batches, one folder per batch.
  - `config.json` — field set, rules, authority bindings, prompt template snapshot.
  - `checkpoint.json` — `{results, audit}`: per-card results + persistent audit log.
  - `authority_cache.json` — cached authority API responses per batch.
  - `_errors/` — cards that failed extraction; retry button moves them back.
- `apps/backend/data/templates.json` — saved templates.
- `apps/backend/data/batches.json` — batch index for the History dashboard.
- `apps/backend/data/bulk_runs/{bulk_run_id}/` — bulk-run state and exports.
  - `run.json` — orchestration state: folder order, per-folder progress, counts,
    timestamps, provider/model. Contains **no** extracted metadata.
  - `consolidated.csv` / `failures.csv` — generated exports. These **do** contain
    extracted metadata; treat them as personal-data-bearing.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Port 5173 / 8000 already in use` | Another process holds the port | `lsof -i :5173` or `:8000` and kill, or change port in `apps/frontend/vite.config.ts` / dev script |
| `OPENROUTER_API_KEY not set` | `.env` missing or unread | Confirm `.env` exists in repo root and contains the key without quotes |
| `503 Authority service unavailable: GEONAMES_USERNAME not configured` | GeoNames username not in `.env` | Sign up at <https://www.geonames.org/login>, add `GEONAMES_USERNAME=...` to `.env`, restart dev server |
| WebSocket disconnects mid-batch | Reverse proxy stripping the WS upgrade | Confirm `rewriteWsOrigin: true` in `apps/frontend/vite.config.ts`; if behind nginx/Caddy, ensure WebSocket upgrade is forwarded |
| Cards extract but show `status: failed` | OpenRouter returned 4xx or 5xx | Check `apps/backend/data/batches/{name}/_errors/` for the offending file; click Retry in Results |
| No **Bulk Processing** entry in the sidebar | `BULK_IMPORT_ROOT` unset, or not a directory the backend can read | Set it in `.env` to an absolute path and restart the backend; `GET /api/v1/config` should report `bulk_enabled: true` |
| Bulk source list is empty | The root's immediate subfolders hold no supported images, or the images sit one level deeper | Bulk mode does not recurse — each collection must be a direct subfolder of the root |
| Bulk run shows `interrupted` | The backend stopped while it was processing | Expected: nothing resumes automatically. Check the last folder/image shown, then click **Resume** |
| Bulk run stopped with status `failed` | A structural fault — missing template, rejected provider credential, unreachable import root, a folder that produced no successful extractions | The run's error message names the cause; fix it and start a new run. Completed folders keep their results |

For anything not listed, open an issue with the relevant log line from the backend terminal.
