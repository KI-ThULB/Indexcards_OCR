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
# Optional: switch from OpenRouter to a local Ollama instance
# OLLAMA_API_KEY=your-ollama-token

# Optional: enable GeoNames authority reconciliation
# GEONAMES_USERNAME=your_geonames_username

# Optional: override the LLM-corrector model (default is a cheap text-only OpenRouter model)
# CORRECTOR_MODEL_NAME=...
```

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
7. Click **Save Template** to persist the field set + rules + bindings for reuse.
8. Click **Start Processing**. The wizard advances to **Processing**.
9. Watch the progress bar and live feed. Each card streams its extracted fields as it completes. Cancel with the toolbar button if needed.
10. When extraction finishes, the wizard advances to **Results**. The table shows:
    - One row per card (multi-entry cards expand into sub-rows).
    - Inline-editable cells (auto-resizing textarea; `Ctrl+Enter` commits, `Esc` cancels, plain `Enter` inserts newline).
    - Per-cell validation badges and tooltips.
    - Filter chips (All / Invalid / Corrected / Verified OK / Auto-corrected).
    - Status colour-coded chip per row.
    - Image thumbnail with click-to-open lightbox.
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

## Data locations

- `apps/backend/data/temp/` — per-session staged uploads (cleaned up automatically after 24h).
- `apps/backend/data/batches/{batch_name}/` — committed batches, one folder per batch.
  - `config.json` — field set, rules, authority bindings, prompt template snapshot.
  - `checkpoint.json` — `{results, audit}`: per-card results + persistent audit log.
  - `authority_cache.json` — cached authority API responses per batch.
  - `_errors/` — cards that failed extraction; retry button moves them back.
- `apps/backend/data/templates.json` — saved templates.
- `apps/backend/data/batches.json` — batch index for the History dashboard.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Port 5173 / 8000 already in use` | Another process holds the port | `lsof -i :5173` or `:8000` and kill, or change port in `apps/frontend/vite.config.ts` / dev script |
| `OPENROUTER_API_KEY not set` | `.env` missing or unread | Confirm `.env` exists in repo root and contains the key without quotes |
| `503 Authority service unavailable: GEONAMES_USERNAME not configured` | GeoNames username not in `.env` | Sign up at <https://www.geonames.org/login>, add `GEONAMES_USERNAME=...` to `.env`, restart dev server |
| WebSocket disconnects mid-batch | Reverse proxy stripping the WS upgrade | Confirm `rewriteWsOrigin: true` in `apps/frontend/vite.config.ts`; if behind nginx/Caddy, ensure WebSocket upgrade is forwarded |
| Cards extract but show `status: failed` | OpenRouter returned 4xx or 5xx | Check `apps/backend/data/batches/{name}/_errors/` for the offending file; click Retry in Results |

For anything not listed, open an issue with the relevant log line from the backend terminal.
