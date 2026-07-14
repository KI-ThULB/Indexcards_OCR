# Security Policy

## Supported versions

Security fixes are applied to the latest released minor version. The project follows
Semantic Versioning; see [CHANGELOG.md](CHANGELOG.md).

| Version | Supported |
|---------|-----------|
| 1.1.x   | ✅        |
| 1.0.x   | ✅        |
| < 1.0   | ❌        |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report privately via one of:

- GitHub → **Security** tab → **Report a vulnerability** (private advisory), or
- email the maintainers (see the repository owner / `git log` for the current maintainer address).

Include: affected component, a description, reproduction steps or a proof-of-concept, and the
impact you observed. We aim to acknowledge within a few working days and to agree a disclosure
timeline with you before any public write-up.

## Security posture (what an operator must know)

This application is **secure-by-default for local single-curator use** and requires explicit
hardening for any networked/multi-user deployment.

- **Local default:** authentication is **off** and the backend binds to `127.0.0.1`
  (`HOST=127.0.0.1`). Nothing is network-exposed unless you deliberately place a proxy in front.
- **Production requirement:** a networked deployment **must** sit behind an authenticating
  reverse proxy (TLS + SSO). The backend's own bearer token (`AUTH_TOKEN`) is a safeguard, not
  a replacement for the proxy. Full instructions: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

### Built-in protections (pentest remediation W-01…W-08)

- **Authentication** — optional env-gated bearer token on the JSON API and WebSocket
  (`?token=`), constant-time comparison.
- **Path traversal** — central validators (uuid4 session ids, `[A-Za-z0-9._-]` names/filenames,
  `safe_join` anchor) in `apps/backend/app/core/security.py`.
- **Upload hardening** — extension whitelist + magic-byte sniffing + per-file/size/count caps;
  validated image-serving route with explicit content-type and `nosniff` (no stored-XSS).
- **WebSocket** — Origin allow-list + token check *before* `accept()` (close code 1008).
- **Abuse control** — single-active-run-per-batch lockfile (409 on concurrent runs) and
  scoped rate limits (slowapi; point `RATE_LIMIT_STORAGE_URI` at Redis for multi-worker).
- **Information disclosure** — generic 500 responses (no exception leakage); OpenAPI/docs gated
  behind `ENABLE_DOCS` (off by default).
- **Headers** — CSP, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `X-Frame-Options`;
  optional strict CORS.
- **Dependencies** — pinned with `==` for reproducibility and CVE control
  (`apps/backend/requirements.txt`).

### Operator responsibilities (NOT provided by the app)

- **TLS termination**, HSTS, and SSO/authentication at the reverse proxy.
- **Encryption at rest** — delegated to the hosting infrastructure (LUKS / BitLocker /
  FileVault / encrypted volume).
- **Secret management** — never commit `.env`; supply secrets via your platform's secret store.
- **Backups** and **data-retention** configuration (`RETENTION_DAYS`, `AUTO_PURGE_AFTER_EXPORT`);
  see the GDPR section in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
- **Per-user accountability** — set `TRUSTED_PROXY_IPS` and `AUDIT_USER_HEADER` so the security
  audit log can attribute actions to the SSO user.

## Handling of personal data

The application processes archival card images that may contain personal data. It provides a
configurable retention policy and an append-only security audit log (`data/audit.log.jsonl`)
that never records OCR text, extracted metadata, prompts, keys, or tokens. See the
**Data protection (GDPR)** section of [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
