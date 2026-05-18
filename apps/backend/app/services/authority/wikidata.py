"""Wikidata authority client via wbsearchentities Action API.
Rate limit (2026): 10 req/min anonymous. Proactive throttle: MIN_INTERVAL_SECONDS = 6.
Reactive 429-handling in base.py fetch_with_retry is NOT enough for bulk mode — 10 cells
exhaust the anonymous rate limit within seconds if fired back-to-back.
Solution: module-level asyncio.Lock + last-request timestamp. Before each outgoing request
we sleep until MIN_INTERVAL_SECONDS have elapsed since the previous request. This keeps
bulk-mode throughput at ≤ 10 req/min without relying on error-recovery alone.
ALWAYS set User-Agent — without it Wikidata applies the most restrictive anonymous tier.
Language: de primary, English fallback (strictlanguage=false).
URI: use concepturi field (http://www.wikidata.org/entity/Q{n}) NOT the url field (wiki page).
"""
import asyncio
import time
from .base import fetch_with_retry, INDEXCARDS_USER_AGENT

# Proactive rate-limit throttle — 10 req/min → one request every 6 seconds minimum
MIN_INTERVAL_SECONDS = 6
_wikidata_lock = asyncio.Lock()
_wikidata_last_request_time: float = 0.0


async def search_wikidata(query: str) -> list[dict]:
    """Search Wikidata for top-5 entity candidates.
    Returns list of {"label": ..., "uri": ..., "description": ...}.
    Canonical URI is http://www.wikidata.org/entity/Q{n} (http, not https — Wikidata convention).
    """
    global _wikidata_last_request_time

    # Proactive throttle: acquire lock, sleep until MIN_INTERVAL_SECONDS since last request
    async with _wikidata_lock:
        now = time.monotonic()
        elapsed = now - _wikidata_last_request_time
        if elapsed < MIN_INTERVAL_SECONDS:
            await asyncio.sleep(MIN_INTERVAL_SECONDS - elapsed)
        _wikidata_last_request_time = time.monotonic()

    data = await fetch_with_retry(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbsearchentities",
            "search": query,
            "language": "de",
            "uselang": "de",
            # Do NOT set strictlanguage — allow English fallback for international entities
            "type": "item",
            "limit": "5",
            "format": "json",
        },
        headers={"User-Agent": INDEXCARDS_USER_AGENT},
    )
    candidates = []
    for r in data.get("search", []):
        label = r.get("label", "")
        # CRITICAL: use concepturi (entity URI), NOT url (wiki page link)
        uri = r.get("concepturi", "")
        description = r.get("description", "")
        if label and uri:
            candidates.append({"label": label, "uri": uri, "description": description})
    return candidates
