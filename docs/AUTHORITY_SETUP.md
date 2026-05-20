# Authority Setup

This document explains how to enable each of the four authority reconciliation backends.

## Overview

Phase 11 adds per-field reconciliation against four authority files:

| Authority | Coverage | API base | Auth | Rate limit (free tier, anonymous) |
|-----------|----------|----------|------|------------------------------------|
| **GND** | Persons, Places, Subjects, Corporate Bodies, Works (German National Library) | <https://lobid.org/gnd/search> | None | Generous (~6,000 simple / 30 complex req/min) |
| **Wikidata** | Everything, multilingual | <https://www.wikidata.org/w/api.php?action=wbsearchentities> | None (User-Agent header required) | 10 req/min anonymous (since 2026 policy change) |
| **GeoNames** | Places worldwide | <http://api.geonames.org/searchJSON> | `GEONAMES_USERNAME` env var | 1,000 req/hr free tier |
| **Getty AAT** | Art & Architecture Thesaurus | <https://services.getty.edu/vocab/reconcile/aat> | None | W3C Reconciliation API v0.2 throttling |

All four flow through a single backend endpoint (`POST /api/v1/reconcile`). The frontend never calls authorities directly.

## GND (Lobid)

**Setup:** Nothing. Lobid is an open API maintained by the Hochschulbibliothekszentrum NRW.

**URI form:** `https://d-nb.info/gnd/{id}` (e.g., `https://d-nb.info/gnd/118540238` for Goethe).

**MARCXML subfield $0 convention:** `(DE-588){id}` (parenthetical prefix only, no URI). This is the MARC21 standard for the Deutsche Nationalbibliothek's ISIL.

**Sub-collections:** Bind your field to one of the 5 specific types for precision:

| Configure dropdown | Lobid filter | Use for |
|--------------------|--------------|---------|
| GND-Persons | `type:Person` | Artists, makers, donors, authors |
| GND-Places | `type:PlaceOrGeographicName` | Origin, location, place of acquisition |
| GND-Subjects | `type:SubjectHeading` | Subject terms, themes, classifications |
| GND-CorporateBodies | `type:CorporateBody` | Companies, museums, institutions |
| GND-Works | `type:Work` | Specific works (paintings, manuscripts, etc.) |

Binding to "GND-Persons" prevents `Berlin (Familienname)` from polluting a Place column with `Berlin (Hauptstadt)`.

**Rate limit:** Most generous of the four. Lobid documentation lists 6,000 simple / 30 complex requests per minute. The backend client honors HTTP 429 / `Retry-After` headers via `base.py`.

## Wikidata

**Setup:** Nothing. Wikidata's `wbsearchentities` endpoint is open. A User-Agent header is sent automatically to identify the client.

**URI form:** `http://www.wikidata.org/entity/Q{n}` (e.g., `http://www.wikidata.org/entity/Q5879` for Goethe).

**MARCXML subfield $0:** full URI (no prefix).

**Language preference:** German first, English fallback. The backend client sends `language=de&uselang=de` but omits `strictlanguage` so English-only entries still match.

**Rate limit:** **10 requests per minute anonymous** under the 2026 Wikimedia policy. This is the strictest cap among the four.

The backend client enforces this **proactively**:

```python
# wikidata.py
MIN_INTERVAL_SECONDS = 6
_wikidata_lock = asyncio.Lock()
_wikidata_last_request_time = 0.0

# Before each request:
async with _wikidata_lock:
    elapsed = monotonic() - _wikidata_last_request_time
    if elapsed < MIN_INTERVAL_SECONDS:
        await asyncio.sleep(MIN_INTERVAL_SECONDS - elapsed)
    # ... fetch ...
    _wikidata_last_request_time = monotonic()
```

Reactive retry-on-429 is not sufficient — the cap is small enough that a bulk reconcile of even ~10 rows would exhaust it. The proactive 6-second minimum means **bulk reconcile of a Wikidata-bound column takes ~6 seconds per cell**. A 100-row column is ~10 minutes. Plan accordingly.

The User-Agent header is sent on every request to qualify for any per-application courtesy throttling Wikimedia may offer.

## GeoNames

**Setup required:**

1. Sign up at <https://www.geonames.org/login> (free).
2. Activate web services after confirming your email: log in → visit your account page → enable "Free Web Services".
3. Add to `.env`:
   ```
   GEONAMES_USERNAME=your_geonames_username
   ```
4. Restart `npm run dev`.

Without this, any GeoNames reconciliation call returns HTTP 503 from `/api/v1/reconcile` with a clear "GEONAMES_USERNAME not configured" message.

**URI form:** `https://www.geonames.org/{geonameId}` (e.g., `https://www.geonames.org/6547383` for Berlin).

**MARCXML subfield $0:** full URI.

**Rate limit:** 1,000 requests per hour on the free tier. **Critical caveat:** GeoNames signals rate-limit errors with **HTTP 200** plus an error code in the JSON body:

```json
{"status": {"value": 18, "message": "daily limit of credits exceeded"}}
```

Error codes treated as rate-limit hits:

| Code | Meaning |
|------|---------|
| 18 | Daily limit exceeded |
| 19 | Hourly limit exceeded |
| 20 | Weekly limit exceeded |
| 22 | Free webservice not enabled for this account |

The backend client (`geonames.py`) has a dedicated retry loop **inside** `search_geonames()` that inspects the body and retries with exponential backoff (2s / 4s / 8s) — this layer cannot be delegated to `base.py` because the HTTP status is 200.

If you exhaust the free tier, upgrade your GeoNames account or wait for the rolling window to reset.

## Getty AAT (Art & Architecture Thesaurus)

**Setup:** Nothing. Getty AAT exposes a W3C Reconciliation API v0.2 endpoint at `https://services.getty.edu/vocab/reconcile/aat`.

**URI form:** `http://vocab.getty.edu/aat/{id}` (e.g., `http://vocab.getty.edu/aat/300033618` for "paintings").

**MARCXML subfield $0:** full URI.

**Protocol difference:** Unlike the other three authorities, AAT uses **POST with a form-encoded body**, not GET with query parameters:

```
POST https://services.getty.edu/vocab/reconcile/aat
Content-Type: application/x-www-form-urlencoded

queries={"q1":{"query":"paintings","limit":5}}
```

Response is `{"q1": {"result": [{"id": "aat/300033618", "name": "paintings", ...}, ...]}}`. The backend client extracts `id` (`aat/300033618`) and constructs the canonical URI (`http://vocab.getty.edu/aat/300033618`).

**Rate limit:** Documented as "reasonable use"; the W3C Reconciliation protocol does not specify a hard cap. HTTP 429 is honored if returned.

## LIDO authority source attribute

When emitting `<lido:conceptID>` or `<lido:actorID>`, the `lido:source` attribute identifies the vocabulary. The frontend uses an `AUTHORITY_SOURCE_LABELS` map in `apps/frontend/src/features/results/useResultsExport.ts`:

| Authority binding | `lido:source` label |
|-------------------|---------------------|
| `gnd-persons`, `gnd-places`, `gnd-subjects`, `gnd-corporate-bodies`, `gnd-works` | `GND` |
| `wikidata` | `Wikidata` |
| `geonames` | `GeoNames` |
| `aat` | `AAT` |

If your institution requires different labels, edit the map in that file. The MARCXML `(DE-588)` GND prefix is also coded there in the `uriToMarc0` helper.

## Cache

Per-batch cache file at `apps/backend/data/batches/{batch_name}/authority_cache.json`.

```json
{
  "gnd-persons:johann wolfgang von goethe": [
    {"label": "Goethe, Johann Wolfgang von", "uri": "https://d-nb.info/gnd/118540238", "description": "..."}
  ],
  "wikidata:rumpelstilzchen": []
}
```

Cache key is `<authority>:<normalized_query>`. Normalisation matches the Phase 8 vocab rules (NFC + ß→ss + casefold + NFD + strip-combining-marks + NFC), so `"GOETHE "` and `"goethe"` hit the same cache row.

**No TTL.** Authority files change slowly; URIs are stable. Use the **Clear cache** button in the Reconcile pane (Clean view) if you suspect an authority has been updated.

**Empty arrays** in the cache mean "queried, no candidates found" — distinct from "never queried" (key absent). This avoids re-querying for known-empty results.

Writes are **atomic**: `cache.py` writes to a temp file then `os.rename` so concurrent bulk-reconcile requests cannot corrupt the file.

## Editing a reconciled cell

If a curator edits the value of a reconciled cell — either in the Verify cockpit, the Results table, or the Clean view — the reconciliation is **dropped** (the URI no longer corresponds to a moving target). The PATCH payload sends `clear_reconciliation: true` (Phase 12 Fix 2). An audit-log entry records `source: 'reconciliation-cleared-by-edit'`.

To re-reconcile after editing, click the reconcile icon in the Clean view again — the system queries the authority for the new value and offers fresh candidates.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| All Wikidata bulk reconciles take ~6 seconds per cell | Working as designed (10 req/min anonymous cap) | Use GND if German-archive data; otherwise plan for the slow rate |
| GeoNames returns 502 from `/api/v1/reconcile` | Free tier exhausted (codes 18/19/20/22) | Wait for the rolling window to reset, or upgrade GeoNames account |
| `503 GEONAMES_USERNAME not configured` | Env var missing | Add to `.env` and restart |
| AAT searches return no candidates for obvious terms | Query too specific or misspelled | Use the "Search again" affordance in the candidate drawer with a refined query |
| Reconciliation badge disappeared after edit | Working as designed (Phase 12 Fix 2) | Re-reconcile from the Clean view |
| LIDO export has `lido:source="My Field Name"` instead of "GND" | Pre-Phase-12 bug | Pull latest; Phase 12 Fix 6 corrects this via `AUTHORITY_SOURCE_LABELS` |
