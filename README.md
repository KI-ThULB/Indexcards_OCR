# Indexcards OCR

A browser-based curator workflow for digitising historical index-card catalogues. Upload scanned cards, extract metadata with a vision-language model, validate it against domain rules, verify each card against the image, clean column-wise data quality issues, reconcile values against authority files (GND, Wikidata, GeoNames, Getty AAT), and export to LIDO / MARCXML / Dublin Core with authority URIs.

Built for GLAM institutions — museums, archives, libraries, memorial sites — that need to turn legacy card catalogues into standards-compliant digital records.

## What it does

The application is a 6-step web workflow:

1. **Upload** — drag JPG/JPEG scans of index cards (any size batch).
2. **Configure** — define which metadata fields to extract; per-field validation rules (regex / vocabulary / LLM corrector); per-field authority bindings (GND-Persons, GND-Places, GND-Subjects, GND-CorporateBodies, GND-Works, Wikidata, GeoNames, Getty AAT); custom extraction prompt template. Saveable as reusable templates.
3. **Processing** — real-time WebSocket progress while the configured VLM extracts each card; resilient against rate limits, network errors, and partial failures. Choose between **OpenRouter** (cloud) and a **self-hosted Ollama** instance; installed Ollama models are auto-discovered at runtime.
4. **Results** — sortable / editable data table with per-cell validation badges, filter chips, soft-block export gate when invalid rows exist. Eight export formats: CSV, JSON, LIDO, MARCXML, Dublin Core, EAD, Darwin Core, METS/MODS.
5. **Verify** *(optional)* — side-by-side cockpit with deep-zoom image and inline-editable fields. Keyboard-driven (J/K for cards, Tab for fields, V to verify, Enter to accept corrector proposals). Marks each field as `verified`.
6. **Clean** *(optional)* — OpenRefine-style column-wise data quality view. Fingerprint clustering for near-duplicates, text + regex faceting, seven bulk transforms (Trim/Upper/Lower/Title/Collapse-whitespace/Regex Replace/Set-to-NULL), per-operation session undo, persistent audit log. Includes a Reconcile pane for authority lookup against the four supported authorities with bulk auto-accept on exact matches.

## What's new in v1.0

- **Configurable OCR provider** — point the app at your own **self-hosted Ollama** instance purely through the backend `.env` (no code change, no frontend rebuild). Endpoint and credentials stay backend-only; the browser never contacts Ollama directly. Installed models are auto-discovered and filtered to vision-capable ones, with an optional allow-list. See [Using your own Ollama instance](docs/GETTING_STARTED.md#using-your-own-ollama-instance).
- **Security hardening** — the backend now closes the findings from a full penetration test: optional bearer-token auth on the API + WebSocket, path-traversal validation, safe image serving (no stored-XSS), upload type/size checks, WebSocket origin allow-list, per-batch run lock, scoped rate limiting, security headers, and localhost-by-default binding. Designed to run behind an authenticating reverse proxy (TLS + SSO) in production.
- **Data protection (GDPR)** — a configurable **retention policy** (auto-purge completed batches, opt-in) with dry-run preview and explicit per-batch purge, plus an append-only **security audit log** of privacy-relevant events. Encryption at rest is delegated to the hosting infrastructure. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#data-protection-gdpr).

> **Deployment note:** local single-curator use is secure and unchanged out of the box (auth off, bound to `127.0.0.1`). Network/multi-user deployment must sit behind an authenticating reverse proxy — see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Quick start

Requires Node 20+, Python 3.10+, `uv`, and an OpenRouter API key (or a self-hosted Ollama instance).

```bash
# Clone and install
git clone https://github.com/KI-ThULB/Indexcards_OCR.git
cd Indexcards_OCR
npm install

# Configure environment
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY (or point OLLAMA_BASE_URL at your own Ollama)
# Optionally set GEONAMES_USERNAME if you want GeoNames reconciliation
# .env.example documents all security, retention, and audit options

# Run both backend (uvicorn :8000) and frontend (Vite :5173)
npm run dev
```

Open <http://localhost:5173>. The backend serves at <http://localhost:8000/api/v1>.

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for a step-by-step first-batch walkthrough.

## Repository layout

This is a Turborepo monorepo with two apps and one shared package:

```
apps/
├── backend/                  FastAPI service: OCR engine, batch lifecycle, WebSocket, authority clients
├── frontend/                 React + Vite + Tailwind: wizard UI, results table, verify cockpit, clean view
└── legacy/                   Original Python batch script (preserved; not part of the web app)
packages/
└── shared-types/             JSON Schema → TS + Pydantic codegen for cross-app types
.planning/                    Phase-by-phase planning records (CONTEXT/RESEARCH/PLAN/SUMMARY/VERIFICATION)
docs/                         How-to guides and architecture documentation
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for component-level detail.

## Key concepts

| Concept | Where it lives | Purpose |
|---------|----------------|---------|
| **Field rules** | per-field config, snapshotted into batch `config.json` | Regex / vocabulary / LLM-corrector validation, run after VLM extraction |
| **Validation outcome** | `{status, rule_failed?, vlm_value?, corrector_proposal?, reconciliation?}` per cell | Five statuses: `valid` / `invalid` / `corrected` / `verified` / `skipped`; reconciliation is an independent dimension |
| **Authority binding** | per-field config, snapshotted into batch `config.json` | One of 8 authority types per field (5 GND sub-collections + Wikidata + GeoNames + AAT) |
| **Cleaning audit log** | per-batch `checkpoint.json` | Every cleaning/reconciliation action recorded with timestamp and source provenance |
| **Security audit log** | `data/audit.log.jsonl` (configurable) | Append-only JSONL of security events (auth, start/cancel/delete, export, purge, config changes); no OCR text or secrets |
| **Retention policy** | `RETENTION_DAYS` / `AUTO_PURGE_AFTER_EXPORT` | Opt-in auto-purge of completed batches (off by default); dry-run preview + manual per-batch purge |
| **Per-batch authority cache** | `data/batches/{name}/authority_cache.json` | All authority API responses cached; optional TTL (`AUTHORITY_CACHE_TTL_DAYS`), manual clear button |
| **Templates** | `data/templates.json` | Reusable field-set + prompt-template + field_rules + authority_bindings configurations |

## Stack

- **Frontend:** React 19, Vite 7, Tailwind 3, Zustand, TanStack Query, lucide-react, sonner. Native WebSocket, no react-use-websocket.
- **Backend:** FastAPI, Pydantic v2, uvicorn, aiohttp. ThreadPoolExecutor for OCR concurrency; module-level asyncio.Lock for proactive Wikidata rate-limiting.
- **OCR:** Qwen3-VL via OpenRouter by default; a self-hosted Ollama instance is configurable at runtime via `.env` (model list auto-discovered server-side).
- **LLM corrector** *(optional, opt-in per batch)*: cheap text-only OpenRouter model fires only on rule failure, hard call cap.
- **Authorities:** GND via Lobid, Wikidata `wbsearchentities`, GeoNames `search` JSON, Getty AAT via W3C Reconciliation API v0.2.
- **Build orchestration:** Turborepo with local-only caching.

## Documentation

- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) — Install, configure, run your first batch.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Monorepo layout, data flow, key components per phase.
- [docs/AUTHORITY_SETUP.md](docs/AUTHORITY_SETUP.md) — How to register for each authority, which need credentials, rate-limit notes.
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — Local vs. production behind a reverse proxy (NGINX/Apache/Caddy/Docker Compose), TLS, security hardening, GDPR retention & audit, data folders, ports.
- [CONTRIBUTING.md](CONTRIBUTING.md) — How to propose changes.
- [README.legacy.md](README.legacy.md) — The original Python-only batch-script README, preserved for historical reference.

## Background

This workflow was developed at the **Thuringian University and State Library (ThULB)** in support of a multi-year digitisation initiative across GLAM institutions in Thuringia. Many museums and archives hold tens of thousands of legacy catalogue cards that contain irreplaceable information about objects, collections, and provenance — yet these analog systems are increasingly inaccessible. The web application turns the original batch script into an interactive curator workflow with quality-control gates suitable for institutional cataloguing.

## License

MIT. See [LICENSE](LICENSE).

## ⚠️ AI-assisted code

This repository contains code that has been assisted by AI tools, including planning, research, and implementation. Substantial portions are AI-generated. Before any productive use:

- Conduct code reviews.
- Validate against your institution's coding and security standards.
- Test with your own data and infrastructure.
- Do not commit `.env` or any other file containing credentials.

You use this code at your own risk.
