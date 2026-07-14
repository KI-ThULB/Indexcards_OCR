---
phase: 11-authority-reconciliation
plan: 02
subsystem: api
tags: [fastapi, authority-reconciliation, gnd, wikidata, geonames, aat, aiohttp, rate-limiting]

# Dependency graph
requires:
  - phase: 11-authority-reconciliation
    plan: "01"
    provides: "authority/cache.py, POST /api/v1/reconcile stub, GEONAMES_USERNAME in config.py"
provides:
  - "apps/backend/app/services/authority/base.py — fetch_with_retry with 3-attempt backoff + Retry-After"
  - "apps/backend/app/services/authority/gnd.py — search_gnd() with TYPE_MAP (5 sub-collections)"
  - "apps/backend/app/services/authority/wikidata.py — search_wikidata() with proactive MIN_INTERVAL_SECONDS=6 throttle"
  - "apps/backend/app/services/authority/geonames.py — search_geonames() with RATE_LIMIT_CODES body-level retry"
  - "apps/backend/app/services/authority/aat.py — search_aat() via POST W3C Reconciliation API v0.2"
  - "POST /api/v1/reconcile fully wired — dispatches to all 4 clients, cache pre/post"
  - "aiohttp>=3.9.0 in requirements.txt"
affects: [11-04]

# Tech tracking
tech-stack:
  added:
    - "aiohttp>=3.9.0 — async HTTP client for all authority API calls"
  patterns:
    - "Module-level asyncio.Lock + monotonic timestamp for proactive Wikidata throttle"
    - "Body-level retry loop in geonames.py re-calling fetch_with_retry on RATE_LIMIT_CODES"
    - "content_type=None in aiohttp resp.json() for Getty AAT content-type mismatch safety"
    - "Regex ^aat/(\\d+)$ with fallback raw_id for Getty AAT URI extraction"

key-files:
  created:
    - apps/backend/app/services/authority/base.py
    - apps/backend/app/services/authority/gnd.py
    - apps/backend/app/services/authority/wikidata.py
    - apps/backend/app/services/authority/geonames.py
    - apps/backend/app/services/authority/aat.py
  modified:
    - apps/backend/app/api/api_v1/endpoints/reconcile.py
    - apps/backend/requirements.txt

key-decisions:
  - "aiohttp chosen over httpx — neither was present; aiohttp selected as it is the plan's first-choice async HTTP library for FastAPI async handlers"
  - "fetch_with_retry opens a new ClientSession per call — avoids shared state across authority clients running concurrently"
  - "GeoNames body-level retry loop lives INSIDE geonames.py (not base.py) because base.py only sees HTTP status codes and returns 200 responses before body inspection is possible"
  - "Wikidata proactive throttle uses module-level _wikidata_lock + _wikidata_last_request_time so concurrent bulk calls respect the 6-second minimum gap globally within a process"

requirements-completed: [FR4]

# Metrics
duration: ~2min
completed: 2026-05-18
---

# Phase 11 Plan 02: Backend Authority Clients Summary

**Four authority API clients (GND, Wikidata, GeoNames, Getty AAT) with shared exponential-backoff retry via base.py, Wikidata proactive 6-second throttle, GeoNames body-level RATE_LIMIT_CODES retry loop, Getty AAT W3C Reconciliation POST protocol, and fully wired POST /api/v1/reconcile endpoint replacing the Wave 1 stub**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-05-18T12:30:12Z
- **Completed:** 2026-05-18T12:32:35Z
- **Tasks:** 2
- **Files modified:** 7 (5 created, 2 modified)

## Accomplishments

- Created `base.py` with `fetch_with_retry` implementing 3-attempt exponential backoff (1s/2s/4s), HTTP 429 Retry-After honor, 5xx retry, and aiohttp ClientSession with 15-second timeout
- Created `gnd.py` with `TYPE_MAP` for all 5 GND sub-collections using exact Lobid filter values: `Person`, `PlaceOrGeographicName`, `SubjectHeading`, `CorporateBody`, `Work`; sends User-Agent on every request
- Created `wikidata.py` with proactive throttle using `MIN_INTERVAL_SECONDS = 6`, module-level `asyncio.Lock`, and `asyncio.sleep` — prevents bulk mode from exhausting the 10-req/min cap; extracts `concepturi` (not `url`) for canonical entity URI
- Created `geonames.py` with `RATE_LIMIT_CODES = {18, 19, 20, 22}` and a GEONAMES-SPECIFIC body-level retry loop (up to 3 retries at 2s/4s/8s backoff) that re-calls `fetch_with_retry` when the HTTP 200 body contains a rate-limit error code; raises `ValueError` on missing `GEONAMES_USERNAME`
- Created `aat.py` with `POST` to W3C Reconciliation API v0.2 at `services.getty.edu/vocab/reconcile/aat`, form-body `queries={"q1":...}`, regex extraction of `aat/NNNNNN` → `http://vocab.getty.edu/aat/{id}` canonical URI
- Replaced reconcile.py stub with full dispatch logic: GND_TYPES set, per-authority client dispatch, cache pre-check, cache post-write (including empty []), ValueError → 503, RuntimeError → 502

## Task Commits

1. **Task 1: base.py + 4 authority clients + requirements.txt** — `5a76a3c` (feat)
2. **Task 2: Wire all 4 clients into POST /api/v1/reconcile** — `12bcd09` (feat)

## Files Created/Modified

- `apps/backend/app/services/authority/base.py` — fetch_with_retry with exponential backoff (1s/2s/4s), 429 Retry-After, 5xx, INDEXCARDS_USER_AGENT constant
- `apps/backend/app/services/authority/gnd.py` — TYPE_MAP (5 entries), search_gnd() with User-Agent
- `apps/backend/app/services/authority/wikidata.py` — MIN_INTERVAL_SECONDS=6, asyncio.Lock throttle, concepturi extraction, User-Agent
- `apps/backend/app/services/authority/geonames.py` — RATE_LIMIT_CODES={18,19,20,22}, body-level retry loop, ValueError on missing username
- `apps/backend/app/services/authority/aat.py` — POST form-body W3C Reconciliation API, aat/NNNNNN regex → full URI
- `apps/backend/app/api/api_v1/endpoints/reconcile.py` — full dispatch replacing stub; cache pre-check, cache post-write, GeoNames 503, API failure 502
- `apps/backend/requirements.txt` — aiohttp>=3.9.0 added

## Decisions Made

- **aiohttp chosen** — neither `aiohttp` nor `httpx` was present in requirements.txt; added `aiohttp>=3.9.0` as the plan's first-choice async HTTP library for FastAPI async handlers
- **New ClientSession per call in base.py** — avoids shared session state across concurrent authority client calls; the overhead (connection pool setup) is negligible given authority rate limits
- **GeoNames body-level retry stays in geonames.py** — architecturally correct: `base.py` only sees HTTP status codes and returns 200 responses as successes; the body inspection for `status.value` codes can only happen after the HTTP response is parsed, which is inside the geonames-specific layer
- **Wikidata throttle is module-level global** — ensures that all concurrent reconcile requests within the same FastAPI process share a single throttle clock; prevents multiple simultaneous bulk operations from each thinking they own the rate limit

## Deviations from Plan

None — plan executed exactly as written. All three correctness hazards specified in the important_notes were implemented precisely:
1. Wikidata proactive throttle with `MIN_INTERVAL_SECONDS = 6`, module-level `asyncio.Lock`, and `asyncio.sleep` before every outgoing request
2. GeoNames body-level retry loop INSIDE `geonames.py` with `RATE_LIMIT_CODES = {18, 19, 20, 22}` re-calling `fetch_with_retry` on rate-limit body codes
3. Getty AAT POST form-body `queries={"q1":{"query":"X","limit":5}}`, parsing `q1.result[i]`, regex extraction of `aat/NNNNNN` → `http://vocab.getty.edu/aat/{id}`

## Self-Check

- `apps/backend/app/services/authority/base.py` — exists, contains `fetch_with_retry` and `INDEXCARDS_USER_AGENT`
- `apps/backend/app/services/authority/gnd.py` — exists, contains `TYPE_MAP` with 5 entries
- `apps/backend/app/services/authority/wikidata.py` — exists, contains `MIN_INTERVAL_SECONDS = 6` and `asyncio.sleep`
- `apps/backend/app/services/authority/geonames.py` — exists, contains `RATE_LIMIT_CODES` and body-level retry loop
- `apps/backend/app/services/authority/aat.py` — exists, contains `vocab.getty.edu/aat`
- `apps/backend/app/api/api_v1/endpoints/reconcile.py` — contains `search_gnd`, `search_wikidata`, `search_geonames`, `search_aat`, `write_cache_entry`, `lookup_cache`, `status_code=503`
- All 11 plan verification checks pass (grep and Python import tests)
- Commits `5a76a3c` and `12bcd09` both exist in git log

## Self-Check: PASSED

---
*Phase: 11-authority-reconciliation*
*Completed: 2026-05-18*
