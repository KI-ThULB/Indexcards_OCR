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
| `RATE_LIMIT_UPLOAD` / `_START` / `_RECONCILE` | `30/minute` / `12/minute` / `120/minute` | Per-action rate limits on expensive endpoints |

### Frontend (build-time, `VITE_` prefix)

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_API_TOKEN` | — | If set, the frontend sends `Authorization: Bearer <token>` on every API call and `?token=` on the WebSocket. Must match the backend `AUTH_TOKEN`. The same built bundle works with or without it |

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
├── batches.json              Batch index for the History dashboard
└── templates.json            Saved templates
```

`data/` is gitignored. Treat it as the curator's working directory.

## Backup and restore

A batch is fully self-contained in `apps/backend/data/batches/{batch_name}/`:

```bash
tar czf my-batch-backup.tar.gz apps/backend/data/batches/my-batch-name/
```

Restore by untarring into the same path — it reappears in History automatically (the endpoint scans the directory at request time). For global state:

```bash
cp apps/backend/data/templates.json apps/backend/data/batches.json /your/backup/location/
```

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

## Verification after deploy

Confirm the hardening is active (see [REMEDIATION_PLAN_WEBAPP.md](../IT_report/REMEDIATION_PLAN_WEBAPP.md) for full PoCs):

- `curl -kI https://host/` → response carries `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Strict-Transport-Security`.
- Upload with `session_id=../../tmp/x` → `400`.
- Request an uploaded `.html` under `/batches-static/…` → not served as `text/html`.
- WebSocket connect with a foreign `Origin` → closed (code 1008).
- With `AUTH_TOKEN` set: API call without the header → `401`.
- Second `POST /api/v1/batches/{b}/start` while one runs → `409`.

## What is NOT provided by the app (proxy / infra responsibility)

- **TLS termination**, **SSO/Shibboleth**, **global traffic throttling / body limits** — reverse proxy.
- **At-rest encryption** and a **security/access audit log** — future work (see the audit's I-2/I-3).
- **Windows** and bare **public exposure without a proxy** are not supported.

## Security notes

- Never commit `.env`; it is gitignored. The `OPENROUTER_API_KEY` has billing implications — guard it.
- Curator-supplied regex (validation rules, pattern facets) can in principle cause CPU exhaustion (ReDoS). Low priority for single-curator use; relevant once exposed to more users.
- `AUTH_TOKEN` is a backend safeguard, not a full auth system — production access control belongs to the authenticating proxy.
