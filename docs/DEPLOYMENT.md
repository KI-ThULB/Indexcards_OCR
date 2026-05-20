# Deployment

The application is designed to run **locally by default** on a curator's workstation. The backend binds to `0.0.0.0:8000` and the frontend dev server binds to `localhost:5173`. Both are intended for trusted networks; there is no authentication layer.

## Local-only operation (recommended)

This is the only mode that has been validated against the requirements (NFR3: privacy-conscious institutions). A single curator runs both services locally and works through the browser.

```bash
npm run dev
```

That's the entire setup once the prerequisites in [GETTING_STARTED.md](GETTING_STARTED.md) are in place.

**Stop:** `Ctrl+C` once in the terminal. Turborepo propagates the signal to both processes.

**Restart on crash:** uvicorn runs with `--reload` and auto-restarts on Python file changes. Vite has HMR. If both crash, run `npm run dev` again.

## Data folders

All persistent state lives under `apps/backend/data/`. Back this up regularly if you want batch durability beyond the local machine.

```
apps/backend/data/
├── temp/                     Per-session upload staging (auto-cleaned after 24h)
├── batches/
│   └── {batch_name}/
│       ├── config.json          Field set, rules, authority bindings (immutable per batch)
│       ├── checkpoint.json      {results, audit} — the authoritative record
│       ├── authority_cache.json Per-batch reconciliation cache
│       ├── _images/             Original card scans
│       └── _errors/             Cards that failed extraction (Retry button moves them back)
├── batches.json              Batch index for the History dashboard
└── templates.json            Saved templates
```

`data/` is in `.gitignore`. Treat it as the curator's working directory.

## Ports

| Service | Port | Configurable in |
|---------|------|-----------------|
| Frontend (Vite dev) | 5173 | `apps/frontend/vite.config.ts` and `apps/frontend/package.json` dev script |
| Backend (uvicorn) | 8000 | `apps/backend/package.json` dev script |

Both dev scripts include an inline Node.js port check that exits with a clear red error if the port is already taken. Override the ports by editing those scripts or by passing `--port` to vite / uvicorn directly.

## Behind a reverse proxy

Not validated but should work with attention to WebSocket forwarding. The backend WebSocket endpoint is `/api/v1/ws/task/{batch_id}`.

### nginx example

```nginx
location /api/ {
    proxy_pass http://localhost:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 600s;  # OCR batches can run for hours
}

location / {
    proxy_pass http://localhost:5173;  # Or serve npm run build output statically
}
```

### Caddy example

```
your-domain.example {
    handle /api/* {
        reverse_proxy localhost:8000
    }
    handle {
        reverse_proxy localhost:5173
    }
}
```

Caddy handles WebSocket upgrade automatically.

**Caveats if you proxy:**

- You are responsible for adding any access control (the app has none).
- Large batches may exceed default proxy timeouts; raise `proxy_read_timeout` accordingly.
- The Vite dev server is not production-grade. For a public-facing deployment, run `npm run build` and serve the static `apps/frontend/dist/` instead.

## Production build (frontend)

```bash
npm run build
```

Output: `apps/frontend/dist/`. Serve with any static host (nginx, Caddy, Apache, or a CDN).

The backend (`apps/backend/`) does not have a "build" step — uvicorn runs the Python source directly. For production:

```bash
cd apps/backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --no-reload
```

`--workers 4` enables multiple worker processes for parallel batches; tune based on CPU. `--no-reload` disables the file watcher.

## Environment variables

Place in repo-root `.env` (read by both backend via `pydantic-settings` and frontend via Vite `envDir`):

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENROUTER_API_KEY` | Yes | Default OCR provider |
| `OLLAMA_API_KEY` | No | Only if you point the OCR engine at an Ollama instance |
| `GEONAMES_USERNAME` | No | Required only if you use GeoNames reconciliation |
| `CORRECTOR_MODEL_NAME` | No | Override the default LLM corrector model |
| `CORRECTOR_MAX_TOKENS` | No | Default 256 |
| `CORRECTOR_TIMEOUT_SECONDS` | No | Default 30 |

The frontend does not read API keys (the backend always proxies authority and VLM calls). Frontend-readable variables would need a `VITE_` prefix — none are currently used.

## Resource expectations

| Workload | Typical CPU | Memory | Network |
|----------|-------------|--------|---------|
| Idle (dev servers running) | 1–3% | 200–400 MB | None |
| OCR processing (100-card batch) | 2–4 cores active during extraction | 500 MB–1 GB | Sustained 1–5 MB/s to OpenRouter |
| Wikidata bulk reconcile | Single-threaded by design (6s gap between requests) | Negligible | Bursty 1 req per 6s |
| GeoNames bulk reconcile | Up to 1000 req/hr | Negligible | Bursty within rate limit |

OpenRouter cost depends on the chosen Qwen3-VL model and the average image size. Optional image resizing in `OcrEngine._encode_image_to_base64` reduces cost; tune `MAX_IMAGE_DIMENSION` in `apps/backend/app/core/config.py` if you need a different ceiling.

## Backup and restore

A batch is fully self-contained in `apps/backend/data/batches/{batch_name}/`. To back up:

```bash
tar czf my-batch-backup.tar.gz apps/backend/data/batches/my-batch-name/
```

To restore on another machine, untar into the same path and the batch will appear in the History dashboard automatically (the History endpoint scans the directory at request time).

For the global templates and batch index:

```bash
cp apps/backend/data/templates.json /your/backup/location/
cp apps/backend/data/batches.json /your/backup/location/
```

## What is NOT validated

- **Windows** — has not been tested. The port-check uses Node.js, which is cross-platform, but path handling may have edge cases.
- **Docker** — no Dockerfile is provided. The legacy Python script's README mentions Docker as a future option (deferred).
- **Multi-user** — there is no authentication, no per-user data scoping, and the dev servers expose ports without any access control. Multiple curators on different machines should run separate local instances.
- **HTTPS** — not configured. If you proxy, terminate TLS at the proxy.

## Security notes

- Never commit `.env`. It is gitignored.
- The OpenRouter API key in `.env` is a secret with billing implications — guard it accordingly.
- The app accepts arbitrary regex from curators (validation rules and pattern facets). Both backend and frontend wrap regex compilation in try/catch, but a deliberately-crafted regex could still cause CPU exhaustion on the frontend ("ReDoS"). Since the app is single-curator local-by-default, this is a low-priority concern, but be aware before exposing to untrusted users.
- The backend has no rate limiting on its own endpoints (`/upload`, `/batches`, `/reconcile`, etc.). Suitable for a single trusted user; not suitable for public exposure.
