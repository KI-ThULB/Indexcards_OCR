# Indexcards OCR — Full-Stack Documentation / Vollständige Stack-Dokumentation

> Bilingual reference for Confluence. English first, German follows (`— DE —`).
> Zweisprachige Referenz für Confluence. Zuerst Englisch, danach Deutsch.

---

# 🇬🇧 English

## 1. Overview

**Indexcards OCR** is a browser-based curator workflow for digitising historical index-card
catalogues. A curator uploads scanned cards, a vision-language model (VLM) extracts the
metadata, the data is validated against domain rules, verified against the image, cleaned
column-wise, reconciled against authority files, and finally exported to standards-compliant
formats (LIDO / MARCXML / Dublin Core / EAD / Darwin Core / METS-MODS).

It is built for **GLAM institutions** (Galleries, Libraries, Archives, Museums) and was
developed at the **Thuringian University and State Library (ThULB)**.

The application is a **6-step web workflow**: Upload → Configure → Processing → Results →
Verify *(optional)* → Clean *(optional)*.

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser (SPA)                          │
│  React 19 + Vite 7 + Tailwind 3 + Zustand + TanStack Query    │
└───────────────┬───────────────────────────┬──────────────────┘
                │ REST (axios /api/v1)        │ WebSocket (native)
                ▼                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Backend — FastAPI (uvicorn)                │
│  Endpoints · OCR engine · Batch lifecycle · Validation ·      │
│  Authority clients · WebSocket manager · Retention · Audit    │
└───────┬───────────────┬───────────────┬──────────────────────┘
        │               │               │
        ▼               ▼               ▼
   VLM provider    Authority APIs    Filesystem store
 (OpenRouter /   (GND/Lobid,         (data/batches,
  self-hosted     Wikidata,           templates.json,
  Ollama)         GeoNames, AAT)      audit.log.jsonl)
```

- **Monorepo:** Turborepo with local-only caching, npm workspaces.
- **Type sharing:** JSON Schema is the single source of truth; code-gen produces both
  TypeScript types and Pydantic models so frontend and backend never drift.
- **Transport:** REST for commands/queries; a native WebSocket streams real-time OCR progress.

## 3. Repository Layout

```
apps/
├── backend/       FastAPI service: OCR engine, batch lifecycle, WebSocket, authority clients
├── frontend/      React + Vite + Tailwind: wizard UI, results table, verify cockpit, clean view
└── legacy/        Original Python batch script (preserved; not part of the web app)
packages/
└── shared-types/  JSON Schema → TypeScript + Pydantic codegen for cross-app types
.planning/         Phase-by-phase planning records (CONTEXT/RESEARCH/PLAN/SUMMARY/VERIFICATION)
docs/              How-to guides and architecture documentation
```

## 4. Technology Stack

### 4.1 Frontend

| Concern | Technology | Version |
|---|---|---|
| Framework | React | 19.2 |
| Build tool / dev server | Vite | 7.3 |
| Styling | Tailwind CSS | 3.4 |
| Client state | Zustand | 5.0 |
| Server state / caching | TanStack Query | 5.90 |
| Data table | TanStack Table | 8.21 |
| HTTP client | axios | 1.13 |
| Icons | lucide-react | 0.575 |
| Toasts | sonner | 2.0 |
| File upload | react-dropzone | 15.0 |
| Deep-zoom image | yet-another-react-lightbox | 3.29 |
| Language | TypeScript | 5.9 |
| Real-time | **Native WebSocket** (no react-use-websocket) | — |

Feature folders (`apps/frontend/src/features/`): `upload`, `configure`, `processing`,
`results`, `verify`, `clean`, `history`.

### 4.2 Backend

| Concern | Technology | Version |
|---|---|---|
| Web framework | FastAPI | 0.137 |
| ASGI server | uvicorn | 0.49 |
| Validation / settings | Pydantic v2 / pydantic-settings | 2.14 |
| Async HTTP | aiohttp | 3.14 |
| Sync HTTP | requests | 2.34 |
| Data handling | pandas | 3.0 |
| Image handling | pillow | 12.2 |
| WebSocket | websockets | 16.0 |
| Fuzzy matching | rapidfuzz | 3.14 |
| Rate limiting | slowapi | 0.1.10 |
| Async file IO | aiofiles | 25.1 |
| Language | Python | 3.10+ |

Concurrency: `ThreadPoolExecutor` for OCR parallelism; a module-level `asyncio.Lock`
for proactive Wikidata rate-limiting.

Backend module map (`apps/backend/app/`):

- `api/api_v1/endpoints/` — `batches`, `upload`, `config`, `reconcile`, `templates`, `ws`, `health`
- `core/` — `config` (settings), `security` (auth + path validation), `rate_limit`, `audit`
- `services/` — `ocr_engine`, `batch_manager`, `ws_manager`, `retention`, `template_service`
- `services/authority/` — `gnd`, `wikidata`, `geonames`, `aat`, `base`, `cache`
- `services/validation/` — `runner`, `regex_rules`, `vocab_rules`, `corrector`, `presets`
- `models/` — Pydantic schemas

### 4.3 Shared Types (`packages/shared-types`)

JSON Schemas in `schemas/` (`batch`, `template`, `upload`, `progress`, `health`) are the
single source of truth. `scripts/generate.mjs` (via `json-schema-to-typescript`) emits
TypeScript types and Pydantic models into `generated/`. Run `npm run generate` after any
schema change.

### 4.4 OCR / VLM

- **Default:** Qwen3-VL via **OpenRouter** (cloud).
- **Alternative:** a **self-hosted Ollama** instance, configurable at runtime via backend `.env`
  (no code change, no frontend rebuild). Installed models are auto-discovered server-side and
  filtered to vision-capable ones, with an optional allow-list.
- **LLM corrector** *(opt-in per batch):* a cheap text-only OpenRouter model fires only on
  rule failure, with a hard call cap.
- The browser never contacts the VLM provider directly — all calls go through the backend.

### 4.5 Authority Files

| Authority | Access | Credentials |
|---|---|---|
| GND (Persons, Places, Subjects, Corporate, Works) | Lobid API | none |
| Wikidata | `wbsearchentities` | none |
| GeoNames | `search` JSON | username (`GEONAMES_USERNAME`) |
| Getty AAT | W3C Reconciliation API v0.2 | none |

## 5. Key Concepts

| Concept | Where it lives | Purpose |
|---|---|---|
| **Field rules** | per-field config → batch `config.json` | Regex / vocabulary / LLM-corrector validation after VLM extraction |
| **Validation outcome** | per cell | Statuses: `valid` / `invalid` / `corrected` / `verified` / `skipped`; reconciliation is independent |
| **Authority binding** | per-field config → batch `config.json` | One of 8 authority types per field |
| **Confidence** | per field + card-level overall | VLM self-reported 0–100% QA signal (green/amber/red), sortable for triage |
| **Cleaning audit log** | per-batch `checkpoint.json` | Every cleaning/reconciliation action with timestamp + provenance |
| **Security audit log** | `data/audit.log.jsonl` | Append-only JSONL of security events; no OCR text or secrets |
| **Retention policy** | `RETENTION_DAYS` / `AUTO_PURGE_AFTER_EXPORT` | Opt-in auto-purge of completed batches (off by default) |
| **Authority cache** | `data/batches/{name}/authority_cache.json` | Cached API responses; optional TTL |
| **Templates** | `data/templates.json` | Reusable field-set + prompt + rules + bindings |

## 6. Data Flow (one batch)

1. **Upload** — JPG/JPEG scans posted to the backend; validated (extension + magic bytes +
   size/count caps) and stored under `data/batches/{name}/`.
2. **Configure** — fields, per-field validation rules, authority bindings, prompt template and
   optional picture description are snapshotted into the batch `config.json`.
3. **Processing** — `ocr_engine` runs each card through the VLM (single call carries values +
   confidence + optional picture description); progress streams over the WebSocket.
4. **Results** — editable table with validation badges, confidence chips/column, export gate.
5. **Verify** *(optional)* — side-by-side deep-zoom image + inline fields; keyboard-driven.
6. **Clean** *(optional)* — column-wise quality view; fingerprint clustering, faceting, bulk
   transforms, undo, audit log, and authority reconciliation.
7. **Export** — CSV, JSON, LIDO, MARCXML, Dublin Core, EAD, Darwin Core, METS/MODS
   (CSV/JSON also carry confidence).

## 7. Security & Compliance

Secure-by-default. Local single-curator use is unchanged (auth off, bound to `127.0.0.1`).
Network/multi-user deployment must sit behind an authenticating reverse proxy (TLS + SSO).

- **Auth:** optional env-gated bearer token on the JSON API + WebSocket `?token=`
  (constant-time compare).
- **Path traversal:** central validators (`core/security.py`) — uuid4 session ids,
  `[A-Za-z0-9._-]` names/filenames, `safe_join` anchor.
- **Upload:** extension whitelist + magic-byte sniffing + size/count caps.
- **Serving:** validated image route (explicit content-type, `nosniff`) — no stored-XSS.
- **WebSocket:** Origin allow-list + token check before `accept()`.
- **Abuse control:** single-active-run-per-batch lockfile (409 on concurrent runs) +
  slowapi rate limits.
- **Headers:** CSP, nosniff, Referrer-Policy, X-Frame-Options; optional strict CORS.
- **Docs:** OpenAPI/docs gated behind `ENABLE_DOCS`; generic 500s (no exception leakage).
- **GDPR:** configurable retention (opt-in) with dry-run preview + manual per-batch purge,
  plus an append-only security audit log.
- Dependencies pinned with `==` for reproducibility and CVE control.

## 8. Build, Run & Test

**Prerequisites:** Node 20+, Python 3.10+, `uv`, an OpenRouter API key (or a self-hosted Ollama).

```bash
git clone https://github.com/KI-ThULB/Indexcards_OCR.git
cd Indexcards_OCR
npm install

cp .env.example .env        # set OPENROUTER_API_KEY or OLLAMA_BASE_URL; optionally GEONAMES_USERNAME

npm run dev                 # backend uvicorn :8000, frontend Vite :5173
```

Open <http://localhost:5173>; the API serves at <http://localhost:8000/api/v1>.

Turborepo scripts (root): `dev`, `build`, `test`, `lint`, `typecheck`, `format`, `clean`.

## 9. Documentation Map

- `docs/GETTING_STARTED.md` — install, configure, first batch.
- `docs/ARCHITECTURE.md` — monorepo layout, data flow, components per phase.
- `docs/AUTHORITY_SETUP.md` — authority registration, credentials, rate limits.
- `docs/DEPLOYMENT.md` — local vs. production behind a reverse proxy, TLS, security, GDPR.
- `CONTRIBUTING.md` — how to propose changes.

---

# 🇩🇪 Deutsch

## 1. Überblick

**Indexcards OCR** ist ein browserbasierter Kurator-Workflow zur Digitalisierung historischer
Karteikarten-Kataloge. Ein Kurator lädt eingescannte Karten hoch, ein Vision-Language-Modell
(VLM) extrahiert die Metadaten, die Daten werden gegen fachliche Regeln validiert, gegen das
Bild verifiziert, spaltenweise bereinigt, gegen Normdateien abgeglichen und schließlich in
standardkonforme Formate exportiert (LIDO / MARCXML / Dublin Core / EAD / Darwin Core /
METS-MODS).

Die Anwendung richtet sich an **GLAM-Einrichtungen** (Galerien, Bibliotheken, Archive, Museen)
und wurde an der **Thüringer Universitäts- und Landesbibliothek (ThULB)** entwickelt.

Die Anwendung ist ein **6-Schritte-Web-Workflow**: Upload → Konfiguration → Verarbeitung →
Ergebnisse → Verifizieren *(optional)* → Bereinigen *(optional)*.

## 2. Architektur auf hoher Ebene

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser (SPA)                          │
│  React 19 + Vite 7 + Tailwind 3 + Zustand + TanStack Query    │
└───────────────┬───────────────────────────┬──────────────────┘
                │ REST (axios /api/v1)        │ WebSocket (nativ)
                ▼                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Backend — FastAPI (uvicorn)                │
│  Endpunkte · OCR-Engine · Batch-Lebenszyklus · Validierung ·  │
│  Normdatei-Clients · WebSocket-Manager · Retention · Audit    │
└───────┬───────────────┬───────────────┬──────────────────────┘
        │               │               │
        ▼               ▼               ▼
   VLM-Anbieter     Normdatei-APIs   Dateisystem-Speicher
 (OpenRouter /    (GND/Lobid,        (data/batches,
  selbst-          Wikidata,          templates.json,
  gehostetes       GeoNames, AAT)     audit.log.jsonl)
  Ollama)
```

- **Monorepo:** Turborepo mit rein lokalem Caching, npm-Workspaces.
- **Typen-Sharing:** JSON Schema ist die einzige Quelle der Wahrheit; Code-Generierung
  erzeugt sowohl TypeScript-Typen als auch Pydantic-Modelle, sodass Frontend und Backend
  nie auseinanderdriften.
- **Transport:** REST für Befehle/Abfragen; ein nativer WebSocket streamt den OCR-Fortschritt
  in Echtzeit.

## 3. Repository-Aufbau

```
apps/
├── backend/       FastAPI-Dienst: OCR-Engine, Batch-Lebenszyklus, WebSocket, Normdatei-Clients
├── frontend/      React + Vite + Tailwind: Wizard-UI, Ergebnistabelle, Verify-Cockpit, Clean-Ansicht
└── legacy/        Ursprüngliches Python-Batch-Skript (erhalten; nicht Teil der Web-App)
packages/
└── shared-types/  JSON Schema → TypeScript + Pydantic Code-Generierung für app-übergreifende Typen
.planning/         Phasenweise Planungsunterlagen (CONTEXT/RESEARCH/PLAN/SUMMARY/VERIFICATION)
docs/              Anleitungen und Architektur-Dokumentation
```

## 4. Technologie-Stack

### 4.1 Frontend

| Bereich | Technologie | Version |
|---|---|---|
| Framework | React | 19.2 |
| Build-Werkzeug / Dev-Server | Vite | 7.3 |
| Styling | Tailwind CSS | 3.4 |
| Client-Zustand | Zustand | 5.0 |
| Server-Zustand / Caching | TanStack Query | 5.90 |
| Datentabelle | TanStack Table | 8.21 |
| HTTP-Client | axios | 1.13 |
| Icons | lucide-react | 0.575 |
| Benachrichtigungen | sonner | 2.0 |
| Datei-Upload | react-dropzone | 15.0 |
| Deep-Zoom-Bild | yet-another-react-lightbox | 3.29 |
| Sprache | TypeScript | 5.9 |
| Echtzeit | **Nativer WebSocket** (kein react-use-websocket) | — |

Feature-Ordner (`apps/frontend/src/features/`): `upload`, `configure`, `processing`,
`results`, `verify`, `clean`, `history`.

### 4.2 Backend

| Bereich | Technologie | Version |
|---|---|---|
| Web-Framework | FastAPI | 0.137 |
| ASGI-Server | uvicorn | 0.49 |
| Validierung / Einstellungen | Pydantic v2 / pydantic-settings | 2.14 |
| Async-HTTP | aiohttp | 3.14 |
| Sync-HTTP | requests | 2.34 |
| Datenverarbeitung | pandas | 3.0 |
| Bildverarbeitung | pillow | 12.2 |
| WebSocket | websockets | 16.0 |
| Fuzzy-Matching | rapidfuzz | 3.14 |
| Rate-Limiting | slowapi | 0.1.10 |
| Async-Datei-IO | aiofiles | 25.1 |
| Sprache | Python | 3.10+ |

Nebenläufigkeit: `ThreadPoolExecutor` für OCR-Parallelität; ein modulweiter `asyncio.Lock`
für proaktives Wikidata-Rate-Limiting.

Backend-Modulkarte (`apps/backend/app/`):

- `api/api_v1/endpoints/` — `batches`, `upload`, `config`, `reconcile`, `templates`, `ws`, `health`
- `core/` — `config` (Einstellungen), `security` (Auth + Pfad-Validierung), `rate_limit`, `audit`
- `services/` — `ocr_engine`, `batch_manager`, `ws_manager`, `retention`, `template_service`
- `services/authority/` — `gnd`, `wikidata`, `geonames`, `aat`, `base`, `cache`
- `services/validation/` — `runner`, `regex_rules`, `vocab_rules`, `corrector`, `presets`
- `models/` — Pydantic-Schemata

### 4.3 Gemeinsame Typen (`packages/shared-types`)

Die JSON-Schemata in `schemas/` (`batch`, `template`, `upload`, `progress`, `health`) sind die
einzige Quelle der Wahrheit. `scripts/generate.mjs` (über `json-schema-to-typescript`) erzeugt
TypeScript-Typen und Pydantic-Modelle in `generated/`. Nach jeder Schema-Änderung
`npm run generate` ausführen.

### 4.4 OCR / VLM

- **Standard:** Qwen3-VL über **OpenRouter** (Cloud).
- **Alternative:** eine **selbst-gehostete Ollama-Instanz**, zur Laufzeit über die
  Backend-`.env` konfigurierbar (keine Code-Änderung, kein Frontend-Rebuild). Installierte
  Modelle werden serverseitig automatisch erkannt und auf vision-fähige gefiltert, mit
  optionaler Allow-List.
- **LLM-Korrektor** *(pro Batch aktivierbar):* ein günstiges reines Text-OpenRouter-Modell
  wird nur bei Regelverstoß ausgelöst, mit hartem Aufruf-Limit.
- Der Browser kontaktiert den VLM-Anbieter nie direkt — alle Aufrufe laufen über das Backend.

### 4.5 Normdateien

| Normdatei | Zugriff | Zugangsdaten |
|---|---|---|
| GND (Personen, Orte, Schlagwörter, Körperschaften, Werke) | Lobid-API | keine |
| Wikidata | `wbsearchentities` | keine |
| GeoNames | `search` JSON | Benutzername (`GEONAMES_USERNAME`) |
| Getty AAT | W3C Reconciliation API v0.2 | keine |

## 5. Zentrale Konzepte

| Konzept | Speicherort | Zweck |
|---|---|---|
| **Feld-Regeln** | Feld-Konfig → Batch-`config.json` | Regex-/Vokabular-/LLM-Korrektor-Validierung nach VLM-Extraktion |
| **Validierungs-Ergebnis** | pro Zelle | Status: `valid` / `invalid` / `corrected` / `verified` / `skipped`; Reconciliation ist unabhängig |
| **Normdatei-Bindung** | Feld-Konfig → Batch-`config.json` | Einer von 8 Normdatei-Typen pro Feld |
| **Konfidenz** | pro Feld + Gesamtwert je Karte | Vom VLM selbst gemeldetes 0–100 %-QS-Signal (grün/gelb/rot), sortierbar zur Triage |
| **Bereinigungs-Audit-Log** | Batch-`checkpoint.json` | Jede Bereinigungs-/Reconciliation-Aktion mit Zeitstempel + Herkunft |
| **Sicherheits-Audit-Log** | `data/audit.log.jsonl` | Append-only-JSONL der Sicherheitsereignisse; kein OCR-Text, keine Secrets |
| **Aufbewahrungs-Richtlinie** | `RETENTION_DAYS` / `AUTO_PURGE_AFTER_EXPORT` | Optionales Auto-Löschen abgeschlossener Batches (standardmäßig aus) |
| **Normdatei-Cache** | `data/batches/{name}/authority_cache.json` | Gecachte API-Antworten; optionale TTL |
| **Vorlagen** | `data/templates.json` | Wiederverwendbares Feld-Set + Prompt + Regeln + Bindungen |

## 6. Datenfluss (ein Batch)

1. **Upload** — JPG/JPEG-Scans an das Backend gesendet; validiert (Endung + Magic-Bytes +
   Größen-/Anzahl-Limits) und unter `data/batches/{name}/` gespeichert.
2. **Konfiguration** — Felder, Feld-Validierungsregeln, Normdatei-Bindungen, Prompt-Vorlage
   und optionale Bildbeschreibung werden in die Batch-`config.json` als Snapshot geschrieben.
3. **Verarbeitung** — `ocr_engine` verarbeitet jede Karte über das VLM (ein einziger Aufruf
   liefert Werte + Konfidenz + optionale Bildbeschreibung); Fortschritt streamt über den
   WebSocket.
4. **Ergebnisse** — editierbare Tabelle mit Validierungs-Badges, Konfidenz-Chips/-Spalte,
   Export-Gate.
5. **Verifizieren** *(optional)* — Bild mit Deep-Zoom neben Inline-Feldern; tastaturgesteuert.
6. **Bereinigen** *(optional)* — spaltenweise Qualitätsansicht; Fingerprint-Clustering,
   Faceting, Massen-Transformationen, Undo, Audit-Log und Normdatei-Reconciliation.
7. **Export** — CSV, JSON, LIDO, MARCXML, Dublin Core, EAD, Darwin Core, METS/MODS
   (CSV/JSON tragen zusätzlich die Konfidenz).

## 7. Sicherheit & Compliance

Sicher per Voreinstellung. Lokale Einzel-Kurator-Nutzung bleibt unverändert (Auth aus, an
`127.0.0.1` gebunden). Netzwerk-/Mehrbenutzer-Betrieb muss hinter einem authentifizierenden
Reverse-Proxy laufen (TLS + SSO).

- **Auth:** optionales, per Umgebungsvariable aktiviertes Bearer-Token auf der JSON-API +
  WebSocket-`?token=` (Constant-Time-Vergleich).
- **Path-Traversal:** zentrale Validierer (`core/security.py`) — uuid4-Session-IDs,
  `[A-Za-z0-9._-]` für Namen/Dateinamen, `safe_join`-Anker.
- **Upload:** Endungs-Whitelist + Magic-Byte-Prüfung + Größen-/Anzahl-Limits.
- **Auslieferung:** validierte Bild-Route (expliziter Content-Type, `nosniff`) — kein
  Stored-XSS.
- **WebSocket:** Origin-Allow-List + Token-Prüfung vor `accept()`.
- **Missbrauchsschutz:** Lockfile für genau einen aktiven Lauf pro Batch (409 bei parallelen
  Läufen) + slowapi-Rate-Limits.
- **Header:** CSP, nosniff, Referrer-Policy, X-Frame-Options; optional striktes CORS.
- **Docs:** OpenAPI/Docs hinter `ENABLE_DOCS`; generische 500er (kein Ausnahme-Leak).
- **DSGVO:** konfigurierbare Aufbewahrung (opt-in) mit Dry-Run-Vorschau + manuellem
  Batch-Löschen, plus append-only Sicherheits-Audit-Log.
- Abhängigkeiten mit `==` gepinnt für Reproduzierbarkeit und CVE-Kontrolle.

## 8. Build, Ausführung & Test

**Voraussetzungen:** Node 20+, Python 3.10+, `uv`, ein OpenRouter-API-Key (oder ein
selbst-gehostetes Ollama).

```bash
git clone https://github.com/KI-ThULB/Indexcards_OCR.git
cd Indexcards_OCR
npm install

cp .env.example .env        # OPENROUTER_API_KEY oder OLLAMA_BASE_URL setzen; optional GEONAMES_USERNAME

npm run dev                 # Backend uvicorn :8000, Frontend Vite :5173
```

<http://localhost:5173> öffnen; die API läuft unter <http://localhost:8000/api/v1>.

Turborepo-Skripte (Root): `dev`, `build`, `test`, `lint`, `typecheck`, `format`, `clean`.

## 9. Dokumentations-Übersicht

- `docs/GETTING_STARTED.md` — Installation, Konfiguration, erster Batch.
- `docs/ARCHITECTURE.md` — Monorepo-Aufbau, Datenfluss, Komponenten je Phase.
- `docs/AUTHORITY_SETUP.md` — Normdatei-Registrierung, Zugangsdaten, Rate-Limits.
- `docs/DEPLOYMENT.md` — Lokal vs. Produktion hinter Reverse-Proxy, TLS, Sicherheit, DSGVO.
- `CONTRIBUTING.md` — Wie Änderungen vorgeschlagen werden.
