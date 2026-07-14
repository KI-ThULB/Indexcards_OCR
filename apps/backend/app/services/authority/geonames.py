"""GeoNames authority client via searchJSON API.
Authentication: GEONAMES_USERNAME env var (required). Returns 503 if missing.
Rate limit: 1000 credits/hr per account (~16 req/min).
CRITICAL: GeoNames returns HTTP 200 even for rate-limit errors.
Rate-limit body detection: check response["status"]["value"] for codes 18/19/20/22.
These MUST trigger a GEONAMES-SPECIFIC retry loop (NOT delegated to base.py fetch_with_retry).
Rationale: fetch_with_retry only sees HTTP status codes — it returns the 200 response as a
success before geonames.py can inspect the body. We need our own retry loop inside this file
that re-calls fetch_with_retry when the body reveals a rate-limit error code.
"""
import asyncio
from .base import fetch_with_retry
from app.core.config import get_settings


# GeoNames error codes in HTTP 200 responses that indicate rate/service limits
RATE_LIMIT_CODES = {18, 19, 20, 22}

# Geonames-specific retry settings (separate from base.py HTTP-level retry)
_GEONAMES_BODY_MAX_RETRIES = 3
_GEONAMES_BODY_BACKOFF_BASE = 2.0  # seconds


async def search_geonames(query: str) -> list[dict]:
    """Search GeoNames for top-5 place candidates.
    Returns list of {"label": ..., "uri": ..., "description": ...}.
    Raises ValueError if GEONAMES_USERNAME not configured.
    Raises RuntimeError on rate limit after _GEONAMES_BODY_MAX_RETRIES body-level retries.
    """
    settings = get_settings()
    username = settings.GEONAMES_USERNAME
    if not username:
        raise ValueError(
            "GEONAMES_USERNAME not configured. "
            "Add GEONAMES_USERNAME=your_account to .env. "
            "Register at https://www.geonames.org/login"
        )

    params = {
        "q": query,
        "maxRows": "5",
        "username": username,
        "style": "SHORT",
    }
    # Note: GeoNames API uses http:// (not https). aiohttp follows redirect transparently.
    url = "http://api.geonames.org/searchJSON"

    # GEONAMES-SPECIFIC BODY-LEVEL RETRY LOOP
    # base.py fetch_with_retry handles HTTP 429/5xx/network errors.
    # This loop handles the separate case where GeoNames returns HTTP 200 but includes
    # a rate-limit error code in the response body (codes 18/19/20/22).
    for attempt in range(_GEONAMES_BODY_MAX_RETRIES):
        data = await fetch_with_retry(url, params=params)

        # CORRECTNESS HAZARD: check body for GeoNames status codes before parsing results.
        if "status" in data:
            code = data["status"].get("value")
            msg = data["status"].get("message", "")
            if code in RATE_LIMIT_CODES:
                # Rate-limit error disguised as HTTP 200 — retry with backoff
                wait = _GEONAMES_BODY_BACKOFF_BASE * (2 ** attempt)  # 2s, 4s, 8s
                if attempt < _GEONAMES_BODY_MAX_RETRIES - 1:
                    await asyncio.sleep(wait)
                    continue
                # Exhausted retries — surface as RuntimeError for reconcile endpoint
                raise RuntimeError(
                    f"GeoNames rate limit exceeded after {_GEONAMES_BODY_MAX_RETRIES} retries "
                    f"(code {code}): {msg}"
                )
            # Other status codes (e.g., 15 = no results) are treated as empty response
            return []

        # No error body — parse results normally
        candidates = []
        for r in data.get("geonames", []):
            geoname_id = r.get("geonameId")
            if not geoname_id:
                continue
            label = r.get("toponymName") or r.get("name", "")
            uri = f"https://www.geonames.org/{geoname_id}"
            fcl_name = r.get("fclName", "")
            country = r.get("countryName", "")
            description = ", ".join(p for p in [fcl_name, country] if p)
            if label:
                candidates.append({"label": label, "uri": uri, "description": description})
        return candidates

    # Should not be reached — loop always returns or raises
    raise RuntimeError("GeoNames search_geonames: unexpected loop exit")
