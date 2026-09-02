# Deployment

Two supported modes:

1. **Local single-curator** (default) — one person runs both services on their workstation. Secure-by-default: the backend binds to `127.0.0.1`, no authentication is required, and nothing is network-exposed.
2. **Networked / multi-user** — the stack is placed behind an **authenticating reverse proxy** that terminates TLS and enforces access control (SSO in production). This is required before any network exposure; see the [pentest remediation](../IT_report/REMEDIATION_PLAN_WEBAPP.md).

> **Security model in one sentence:** the FastAPI backend is a trusted-internal service bound to localhost; the reverse proxy is the only network-exposed component and owns TLS + authentication. The app ships defense-in-depth (path validation, upload hardening, security headers, WebSocket origin checks, an optional bearer token, per-batch run locks, and scoped rate limits), but it does **not** terminate TLS, do SSO, or throttle global traffic — those belong to the proxy.

---

## Local single-curator operation (default)

```bash
npm run dev
```

That's the whole setup once [GETTING_STARTED.md](GETTING_STARTED.md) prerequisites are in place. The backend binds to `127.0.0.1:8000`, the Vite dev server to `localhost:5173`.

- **Stop:** `Ctrl+C` once — Turborepo propagates the signal to both processes.
- **Restart on crash:** uvicorn runs with `--reload`; Vite has HMR. If both crash, run `npm run dev` again.

No authentication is needed in this mode because nothing is reachable off the machine.

---

## Environment variables

Place in the repo-root `.env` (read by the backend via `pydantic-settings`; `VITE_`-prefixed ones are read by the frontend at build time via Vite `envDir`). See [`.env.example`](../.env.example) for the full annotated list.

### Core

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | OpenRouter OCR provider key (required to use OpenRouter) |
| `HOST` | `127.0.0.1` | Interface the backend binds to. Keep localhost; expose via the proxy only |
| `DATA_DIR` | `data` | Root of persistent state |

### Ollama (self-hosted VLM)

See [GETTING_STARTED.md → Using your own Ollama instance](GETTING_STARTED.md#using-your-own-ollama-instance). `OLLAMA_BASE_URL`, `OLLAMA_MODEL_NAME`, `OLLAMA_API_KEY`, `OLLAMA_ENABLED`, allow-list and vision-filter live there. `OLLAMA_BASE_URL` and `OLLAMA_API_KEY` are backend-only — never sent to the browser.

### Security / hardening

| Variable | Default | Purpose |
|----------|---------|---------|
| `AUTH_TOKEN` | `""` (off) | Optional bearer token guarding the JSON API + WebSocket. Empty ⇒ disabled (local dev). A backend safeguard, **not** a replacement for proxy SSO |
| `ALLOWED_WS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated Origin allow-list for the WebSocket handshake. Set to your production origin(s) |
| `ENABLE_DOCS` | `false` | Expose `/docs`, `/redoc`, and `openapi.json`. Keep off in production |
| `CORS_ALLOW_ORIGINS` | `""` (off) | Comma-separated CORS allow-list. Leave empty for same-origin behind a proxy. Never `*` with credentials |
| `MAX_UPLOAD_BYTES` | `26214400` (25 MB) | Per-file upload size cap |
| `MAX_UPLOAD_FILES` | `2000` | Per-request file count cap |
| `ALLOWED_IMAGE_EXTENSIONS` | `.jpg,.jpeg,.png,.tif,.tiff` | Upload + image-serving whitelist |
| `RATE_LIMIT_STORAGE_URI` | `memory://` | slowapi storage. **Use `redis://…` when running more than one worker** so limits are shared |
| `RATE_LIMIT_UPLOAD` / `_START` / `_RECONCILE` / `_BULK_START` | `30/minute` / `12/minute` / `120/minute` / `6/minute` | Per-action rate limits on expensive endpoints |

### Data retention (GDPR storage limitation — audit I-3)

| Variable | Default | Purpose |
|----------|---------|---------|
| `RETENTION_DAYS` | `0` (off) | Auto-purge *completed* batches this many days after completion. `0` disables retention entirely |
| `AUTO_PURGE_AFTER_EXPORT` | `false` | After a successful METS/MODS ingest export, purge that batch's working data |
| `AUTHORITY_CACHE_TTL_DAYS` | `0` (no expiry) | TTL for the per-batch authority reconciliation cache |

### Bulk / multi-batch processing (opt-in)

Off unless `BULK_IMPORT_ROOT` is set: with it empty every `/api/v1/bulk/*` route returns
`404` and the UI hides the entry point, so an unconfigured deployment has no bulk surface at
all. See [Bulk import root, hardlinks and immutability](#bulk-import-root-hardlinks-and-immutability)
below and [GETTING_STARTED.md → Bulk / multi-batch processing](GETTING_STARTED.md#bulk--multi-batch-processing).

| Variable | Default | Purpose |
|----------|---------|---------|
| `BULK_IMPORT_ROOT` | `""` (off) | Absolute path to a directory whose **immediate** subfolders each hold one card collection. Only those subfolders are ever offered; arbitrary paths are never accepted. Read-only to the app. Empty ⇒ bulk mode entirely unavailable |
| `BULK_IMPORT_MODE` | `hardlink` | `hardlink` (no extra disk; automatic per-file fallback to copy when the source is on another filesystem) or `copy` |
| `BULK_CONTINUE_ON_BATCH_ERROR` | `true` | Continue with the next folder when a folder finishes with recoverable image-level errors. Structural faults always stop the run |
| `BULK_MAX_FOLDERS` | `200` | Cap on the folder listing and on the folders selectable in one run — guards against a pathological root |
| `RATE_LIMIT_BULK_START` | `6/minute` | Rate limit on creating and starting a run |

### Security audit log (GDPR accountability — audit I-2)

| Variable | Default | Purpose |
|----------|---------|---------|
| `AUDIT_ENABLED` | `true` | Write the append-only JSONL security audit log |
| `AUDIT_LOG_FILE` | `data/audit.log.jsonl` | Audit log destination |
| `AUDIT_USER_HEADER` | `X-Forwarded-User` | Trusted proxy header carrying the SSO user (configurable name) |
| `TRUSTED_PROXY_IPS` | `""` | Proxy IPs/CIDRs whose user header is trusted. Empty ⇒ header never trusted (actor = `unknown`). Set this for real per-user accountability |

### Frontend (build-time, `VITE_` prefix)

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_API_TOKEN` | — | If set, the frontend sends `Authorization: Bearer <token>` on every API call and `?token=` on the WebSocket. Must match the backend `AUTH_TOKEN`. The same built bundle works with or without it |

---

## Data protection (GDPR)

The app processes personal data (historic card scans + extracted metadata), so three
obligations are handled explicitly. **Encryption at rest is deliberately delegated to
the infrastructure; retention and accountability are handled in the app.**

### Encryption at rest — infrastructure responsibility

The application does **not** encrypt files, checkpoints or metadata itself. Provide
encryption at rest via the hosting platform:

- **LUKS** (Linux), **BitLocker** (Windows), **FileVault** (macOS), or an encrypted
  storage volume / SAN.
- Mount `apps/backend/data/` (or `DATA_DIR`) on the encrypted volume.
- Restrict filesystem access to the service user (`chmod 700 data/`).

This protects the realistic threat (lost/stolen/decommissioned media) at near-zero
complexity. Application-level encryption was intentionally **not** implemented (it would
break "tar a batch dir to back up" and add key-management burden without addressing the
primary threat for an on-prem single-instance deployment).

### Retention (storage limitation, Art. 5(1)(e))

Retention is **opt-in** (`RETENTION_DAYS=0` by default — nothing is ever auto-deleted).
When enabled:

- Only batches with status **`completed`** are eligible. `uploaded`, `running`, `failed`,
  `cancelled` and currently-**exporting** batches are never auto-purged.
- A batch with an active OCR run (run-lock present) is never purged.
- A purge removes images, temp derivatives, `checkpoint.json` and the authority cache,
  but keeps a **minimal non-sensitive tombstone** (`batch_name`, `custom_name`,
  `created_at`, `status: purged`, `purged_at`) for accountability.
- Every purge — automatic or manual — is written to the audit log.

Operator controls (all audited):

- `GET  /api/v1/batches/retention/preview` — **dry-run**: lists what would be purged now and why others are skipped. Deletes nothing.
- `POST /api/v1/batches/retention/purge` — run the sweep now.
- `POST /api/v1/batches/{batch}/purge` — immediately purge one batch (refuses with `409` while it is running or exporting).
- The existing `DELETE /api/v1/batches/{batch}` still fully removes a batch (history entry included).

A retention sweep also runs once at backend startup. For continuous operation, trigger
`POST /retention/purge` from a scheduler (cron/systemd timer) — the app does not run its
own background scheduler.

### Audit log (accountability, Art. 5(2) / Art. 30)

An append-only **JSON Lines** log (`AUDIT_LOG_FILE`) records security-relevant events
only: authenticated user (when available), batch start / cancel / delete, export
start / complete, purge (auto + manual), configuration (template) changes, and
authentication failures. Each record carries `ts, actor, action, target, result,
request_id, source_ip`.

It **never** contains OCR text, extracted metadata, uploaded content, prompts, API keys
or bearer tokens. It **complements**, and does not replace, the reverse-proxy access log.

**Trusted-header handling (important).** The `actor` is read from `AUDIT_USER_HEADER`
(e.g. `X-Forwarded-User`) **only** when the request's immediate client IP is in
`TRUSTED_PROXY_IPS`. Otherwise the actor is recorded as `unknown` — never a fabricated
identity. To make this meaningful you must, at the proxy:

1. Authenticate the user (SSO / Shibboleth / OIDC).
2. **Strip any client-supplied `X-Forwarded-User` (or your chosen header) from the
   inbound request**, then set it from the verified identity — so a client cannot spoof it.
3. Ensure the backend sees the proxy's IP as the client (loopback or the compose network),
   and list that IP/CIDR in `TRUSTED_PROXY_IPS`.

NGINX example for step 2:

```nginx
location /api/ {
    proxy_set_header X-Forwarded-User "";                 # clear any client value
    proxy_set_header X-Forwarded-User $remote_user;       # set from verified SSO
    # …plus the proxy_pass / upgrade headers from the NGINX block above
}
```

---

## Networked deployment (production)

### Backend process

```bash
cd apps/backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4 --no-reload
```

- `--host 127.0.0.1` — never bind `0.0.0.0` in production; the proxy reaches the backend over loopback.
- `--workers 4` — parallel workers; tune to CPU. **With more than one worker you must set `RATE_LIMIT_STORAGE_URI=redis://…`**, otherwise each worker keeps its own in-memory rate-limit counters and the per-batch run lock is the only cross-worker guard.
- `--no-reload` — disable the file watcher.

### Frontend build

```bash
npm run build            # from repo root, or: cd apps/frontend && npm run build
```

Output: `apps/frontend/dist/` — static assets served by the proxy. The build reads `VITE_API_TOKEN` if present.

### Reverse-proxy requirements (all examples below satisfy these)

- **Terminate TLS** at the proxy; redirect 80 → 443. The app never speaks TLS itself.
- **One origin** for the SPA, `/api`, and `/batches-static` so the frontend's relative URLs and same-origin WebSocket work.
- **Forward headers:** `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`.
- **WebSocket upgrade** for `/api/v1/ws/` with a long read timeout (progress sockets are long-lived; OCR batches can run for hours).
- **Security headers at the proxy** in addition to the ones the app already sets: `Strict-Transport-Security` (HSTS) especially, since the app cannot know it is behind TLS.
- **Enforce authentication** (SSO / Shibboleth / basic auth) — this is the proxy's job and covers **all** routes, including `/batches-static` images (which cannot carry a bearer token).
- Optionally set a **global body-size limit** and **global rate limit** as an outer layer; the app's per-action limits are an inner safeguard, not a substitute.

---

### NGINX

```nginx
server {
    listen 443 ssl;
    server_name indexcards.example.org;

    ssl_certificate     /etc/ssl/certs/indexcards.pem;
    ssl_certificate_key /etc/ssl/private/indexcards.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    # Security headers (app also sets CSP/nosniff/etc; HSTS must come from the proxy)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header X-Frame-Options "DENY" always;

    client_max_body_size 30m;   # >= MAX_UPLOAD_BYTES, with headroom

    # --- REST + WebSocket API ---
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;          # WebSocket
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;                        # long-lived progress sockets
    }

    # --- Batch images (access control enforced here by the proxy) ---
    location /batches-static/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # --- SPA static files ---
    root /var/www/indexcards/dist;
    location / {
        try_files $uri $uri/ /index.html;                # client-side routing fallback
    }
}

server {                       # redirect HTTP → HTTPS
    listen 80;
    server_name indexcards.example.org;
    return 301 https://$host$request_uri;
}
```

### Apache (httpd)

Requires `mod_ssl`, `mod_proxy`, `mod_proxy_http`, `mod_proxy_wstunnel`, `mod_headers`, `mod_rewrite`.

```apache
<VirtualHost *:443>
    ServerName indexcards.example.org

    SSLEngine on
    SSLCertificateFile      /etc/ssl/certs/indexcards.pem
    SSLCertificateKeyFile   /etc/ssl/private/indexcards.key
    SSLProtocol             -all +TLSv1.2 +TLSv1.3

    Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains"
    Header always set X-Content-Type-Options "nosniff"
    Header always set Referrer-Policy "no-referrer"
    Header always set X-Frame-Options "DENY"

    LimitRequestBody 31457280

    # WebSocket first (most specific), then REST, then images
    ProxyPass        /api/v1/ws/  ws://127.0.0.1:8000/api/v1/ws/
    ProxyPassReverse /api/v1/ws/  ws://127.0.0.1:8000/api/v1/ws/
    ProxyPass        /api/           http://127.0.0.1:8000/api/
    ProxyPassReverse /api/           http://127.0.0.1:8000/api/
    ProxyPass        /batches-static/ http://127.0.0.1:8000/batches-static/
    ProxyPassReverse /batches-static/ http://127.0.0.1:8000/batches-static/
    ProxyTimeout 3600

    # SPA static files + client-side routing fallback
    DocumentRoot /var/www/indexcards/dist
    <Directory /var/www/indexcards/dist>
        Require all granted
        RewriteEngine On
        RewriteCond %{REQUEST_FILENAME} !-f
        RewriteCond %{REQUEST_URI} !^/(api|batches-static)/
        RewriteRule ^ /index.html [L]
    </Directory>
</VirtualHost>

<VirtualHost *:80>
    ServerName indexcards.example.org
    Redirect permanent / https://indexcards.example.org/
</VirtualHost>
```

### Caddy

Automatic HTTPS (Let's Encrypt) and native WebSocket support — the simplest option.

```caddy
indexcards.example.org {
    encode gzip

    header {
        Strict-Transport-Security "max-age=63072000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "no-referrer"
        X-Frame-Options "DENY"
    }

    # REST + WebSocket (Caddy upgrades WS automatically)
    reverse_proxy /api/* 127.0.0.1:8000
    # Batch images (access control enforced by Caddy, e.g. forward_auth / basicauth)
    reverse_proxy /batches-static/* 127.0.0.1:8000

    # SPA static files with client-side routing fallback
    root * /var/www/indexcards/dist
    try_files {path} /index.html
    file_server
}
```

Long-lived WebSockets: Caddy has no default read timeout that would cut idle progress sockets, so no extra tuning is needed.

### Docker Compose

Backend on an internal network only; the proxy is the sole published service. Optional Redis backs shared rate-limit state for multi-worker setups.

```yaml
services:
  backend:
    build: ./apps/backend
    command: uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --no-reload
    # NOTE: 0.0.0.0 is safe HERE because the port is only reachable on the
    # internal compose network — it is never published to the host.
    expose:
      - "8000"
    environment:
      - DATA_DIR=/data
      - AUTH_TOKEN=${AUTH_TOKEN}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-}
      - ALLOWED_WS_ORIGINS=https://indexcards.example.org
      - RATE_LIMIT_STORAGE_URI=redis://redis:6379
      - ENABLE_DOCS=false
    volumes:
      - batch-data:/data
    networks: [internal]
    depends_on: [redis]

  redis:
    image: redis:7-alpine
    expose:
      - "6379"
    networks: [internal]

  proxy:
    image: caddy:2-alpine
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./apps/frontend/dist:/var/www/indexcards/dist:ro
      - caddy-data:/data
    networks: [internal]
    depends_on: [backend]

networks:
  internal:

volumes:
  batch-data:
  caddy-data:
```

Secrets (`AUTH_TOKEN`, `OPENROUTER_API_KEY`) come from a `.env` file next to the compose file. The `proxy` service's Caddyfile is the "Caddy" example above with `reverse_proxy … backend:8000` instead of `127.0.0.1:8000`.

---

## Data folders

All persistent state lives under `apps/backend/data/` (or `DATA_DIR`). Back it up for durability.

```
apps/backend/data/
├── temp/                     Per-session upload staging (auto-cleaned after 24h)
├── batches/
│   └── {batch_name}/
│       ├── config.json          Field set, rules, authority bindings (immutable per batch)
│       ├── checkpoint.json      {results, audit} — the authoritative record
│       ├── authority_cache.json Per-batch reconciliation cache
│       ├── .run.lock            Present while an OCR run is active (single-run guard)
│       ├── _errors/             Cards that failed extraction (Retry moves them back)
│       └── *.jpg …              Original card scans
├── bulk_runs/                Bulk / multi-batch runs (only when BULK_IMPORT_ROOT is set)
│   └── {bulk_run_id}/
│       ├── run.json             Orchestration state: folder order, per-folder progress,
│       │                        counts, timestamps, provider/model. NO extracted metadata
│       ├── consolidated.csv     Generated export — CONTAINS extracted metadata
│       └── failures.csv         Generated export — CONTAINS extracted metadata
├── .bulk_run.lock            Present while a bulk run is active (single-run guard)
├── batches.json              Batch index for the History dashboard
└── templates.json            Saved templates
```

`data/` is gitignored. Treat it as the curator's working directory.

> **`data/bulk_runs/{id}/consolidated.csv` and `failures.csv` carry personal data.** They
> hold the extracted card metadata for a whole collection in one file, so they belong on the
> same encrypted volume as `data/batches/`, must be included in the backup and access
> controls you apply to that directory, and should be deleted once the records have been
> ingested. `run.json` itself holds only folder names, counts and timestamps.
>
> Retention (`RETENTION_DAYS`, `AUTO_PURGE_AFTER_EXPORT`) covers the **batches** a bulk run
> creates, because they are ordinary batches. It does **not** delete a generated
> `consolidated.csv` — remove those with the rest of your export handling.

## Bulk import root, hardlinks and immutability

Bulk mode reads source images from `BULK_IMPORT_ROOT` on a filesystem the backend process
can see, so tens of thousands of scans never traverse the browser. Two properties matter
operationally.

### Source files are immutable

**The app only ever reads the directories under `BULK_IMPORT_ROOT`.** It never modifies,
renames, moves or deletes a source file, and the source directory listing is never changed.
That holds through successful processing, failed processing, retries, batch cleanup/purge and
deletion of the generated batches — a regression test suite
(`tests/test_bulk_immutability.py`) fingerprints every source file with SHA-256, size and
mtime and asserts byte identity after each of those operations, in both import modes.

This matters because of how the import works. In the default `hardlink` mode, a batch-side
image is a **second directory entry for the same inode** as the archival original. Moving or
deleting the batch-side link is safe and is exactly what the pipeline does (failed cards move
into `_errors/`, retries move them back, purge and delete remove the batch directory). But an
*in-place write* to a batch-side image would corrupt the source scan. The pipeline is built
and tested not to do that: image resizing happens in memory only, image serving is read-only,
and no code path opens an image for writing.

If you extend the pipeline, keep that rule: **moving or deleting a batch-side image is fine;
modifying its contents is not.**

### Disk implications

| Mode | Extra disk for 28 × 500 scans | Notes |
|------|-------------------------------|-------|
| `hardlink` (default) | ~none (directory entries only) | Requires `BULK_IMPORT_ROOT` and `DATA_DIR` on the **same filesystem** |
| `copy` (and the automatic fallback) | A full second copy of every image | Used automatically per file when a hardlink cannot be made (e.g. `EXDEV`: source on another mount) |

So plan capacity by asking whether the import root and `DATA_DIR` share a filesystem. If they
do not, budget for a full duplicate of the collection — for ~14,000 scans that is typically
tens of GB. Deleting or purging the generated batches reclaims it, and leaves the originals
untouched.

Other operational notes:

- Only the root's **immediate** subfolders are offered; there is no recursion.
- Symlinked subfolders are refused and symlinked files are skipped, so a link inside the
  import root cannot pull an arbitrary file into a batch directory (from which
  `/batches-static/` would serve it).
- The client sends folder **names** chosen from the backend's listing. Names are re-resolved
  against the root and re-checked against that listing, and the root path itself is never
  sent to the browser.
- Mount the import root **read-only** if your storage allows it. The app does not need write
  access to it, and that turns the guarantee above into a filesystem-enforced one.

### Restart and resume behaviour

The orchestrator is an in-process asyncio task, so restarting the backend necessarily
interrupts a run. **It is never resumed automatically** — a run recorded as `running` at
startup is marked `interrupted`, keeping the folder, image and timestamp it stopped at, and
nothing is sent to the model until a human clicks **Resume**. This is deliberate: an
unattended crash-loop or a routine redeploy must not silently restart hours of model spend.

Consequences for deployment:

- A redeploy during a long run is safe but requires a human to resume it afterwards. Plan
  redeploys around long runs, or expect to click Resume.
- Resuming skips completed folders entirely and, within the interrupted folder, never
  re-sends a card that was already extracted — the per-batch `checkpoint.json` is the unit of
  recovery, and checkpoint writes are atomic.
- A lock left behind by the dead process is released at startup, so an interrupted run never
  blocks future runs.
- Only one bulk run executes at a time, enforced by an `O_EXCL` lock in `data/bulk_runs/`.
  Folders within a run are processed strictly sequentially; the existing per-batch
  `MAX_WORKERS` concurrency is unchanged, so peak VLM load is the same as a single batch.

### Validate before authoritative ingest

Bulk mode skips the mandatory per-folder quality-control stop. Per-card QC data is still
written and every folder remains an ordinary, individually inspectable batch — but nothing
has been curator-approved. **Validate the consolidated CSV before publishing it or ingesting
it into an authoritative system**, and check the failures CSV for cards that need a retry or
manual handling.

## Backup and restore

A batch is fully self-contained in `apps/backend/data/batches/{batch_name}/`:

```bash
tar czf my-batch-backup.tar.gz apps/backend/data/batches/my-batch-name/
```

Restore by untarring into the same path — it reappears in History automatically (the endpoint scans the directory at request time). For global state:

```bash
cp apps/backend/data/templates.json apps/backend/data/batches.json /your/backup/location/
```

Bulk-run state and its exports live in `apps/backend/data/bulk_runs/{bulk_run_id}/`. Back it
up alongside the batches it refers to — a `run.json` on its own is just an index; the records
are in the batches' `checkpoint.json` files. Remember the generated CSVs contain personal
data.

## Ports

| Service | Port | Configurable in |
|---------|------|-----------------|
| Frontend (Vite dev) | 5173 | `apps/frontend/vite.config.ts`, `apps/frontend/package.json` |
| Backend (uvicorn) | 8000 | `apps/backend/package.json` dev script |

## Resource expectations

| Workload | Typical CPU | Memory | Network |
|----------|-------------|--------|---------|
| Idle (dev servers running) | 1–3% | 200–400 MB | None |
| OCR processing (100-card batch) | 2–4 cores active | 500 MB–1 GB | Sustained 1–5 MB/s to the VLM provider |
| Wikidata bulk reconcile | Single-threaded (6s gap) | Negligible | 1 req / 6s |
| GeoNames bulk reconcile | Up to 1000 req/hr | Negligible | Bursty within rate limit |
| Bulk run (28 folders × ~500 cards) | Same as one batch — folders are sequential | Same as one batch; the consolidated export is streamed, so peak memory is one folder | Same as one batch, sustained for the length of the run |

## Verification after deploy

Confirm the hardening is active (see [REMEDIATION_PLAN_WEBAPP.md](../IT_report/REMEDIATION_PLAN_WEBAPP.md) for full PoCs):

- `curl -kI https://host/` → response carries `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Strict-Transport-Security`.
- Upload with `session_id=../../tmp/x` → `400`.
- Request an uploaded `.html` under `/batches-static/…` → not served as `text/html`.
- WebSocket connect with a foreign `Origin` → closed (code 1008).
- With `AUTH_TOKEN` set: API call without the header → `401`.
- Second `POST /api/v1/batches/{b}/start` while one runs → `409`.
- With `BULK_IMPORT_ROOT` unset: `GET /api/v1/bulk/sources` → `404`, and `GET /api/v1/config`
  reports `bulk_enabled: false`.
- With it set: a folder name containing `..` or a separator → `400`; the response never
  contains the import-root path.

## What is NOT provided by the app (proxy / infra responsibility)

- **TLS termination**, **SSO/Shibboleth**, **global traffic throttling / body limits** — reverse proxy.
- **Encryption at rest** — infrastructure responsibility (LUKS/BitLocker/FileVault); see [Data protection](#data-protection-gdpr).
- **A network access log** — the reverse proxy's job. The app provides a complementary *semantic* audit log (I-2), and a retention policy (I-3), both documented under [Data protection](#data-protection-gdpr).
- **Windows** and bare **public exposure without a proxy** are not supported.

## Security notes

- Never commit `.env`; it is gitignored. The `OPENROUTER_API_KEY` has billing implications — guard it.
- Curator-supplied regex (validation rules, pattern facets) can in principle cause CPU exhaustion (ReDoS). Low priority for single-curator use; relevant once exposed to more users.
- `AUTH_TOKEN` is a backend safeguard, not a full auth system — production access control belongs to the authenticating proxy.
