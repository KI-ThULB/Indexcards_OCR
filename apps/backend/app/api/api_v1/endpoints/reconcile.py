"""Authority reconciliation endpoint.
POST /api/v1/reconcile — dispatches to 4 authority clients based on 'authority' field.
Cache pre-check: returns cached candidates (including empty [] for no-match) without API call.
Cache post-write: writes all responses (including empty []) to per-batch cache.
Rate-limit note: frontend bulk-mode serializes per-authority (one cell at a time per column).
  The endpoint itself does NOT enforce cross-request throttling — sequential frontend calls
  naturally stay within authority rate limits.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List
from pathlib import Path
from app.core.config import get_settings, settings
from app.core.rate_limit import limiter
from app.core.security import validate_batch_name

router = APIRouter()


class ReconcileRequest(BaseModel):
    authority: str   # gnd-persons | gnd-places | gnd-subjects | gnd-corporate-bodies | gnd-works | wikidata | geonames | aat
    query: str
    batch_name: str  # needed to read/write per-batch cache


class ReconcileResponse(BaseModel):
    candidates: List[dict]
    from_cache: bool


GND_TYPES = {"gnd-persons", "gnd-places", "gnd-subjects", "gnd-corporate-bodies", "gnd-works"}


@router.post("", response_model=ReconcileResponse)
@limiter.limit(settings.RATE_LIMIT_RECONCILE)
async def reconcile(request: Request, req: ReconcileRequest):
    """Query an authority for candidates matching the query string.
    Cache hit: returns cached candidates without external API call.
    Cache miss: calls authority API, writes result to cache (including empty list), returns candidates.
    Error handling:
      - GeoNames missing username → 503 Service Unavailable
      - Authority API failure after 3 retries → 502 Bad Gateway (surface as "API error — retry?" in UI)
    """
    cfg = get_settings()
    try:
        validate_batch_name(req.batch_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch name")
    batch_dir = Path(cfg.BATCHES_DIR) / req.batch_name
    if not batch_dir.exists():
        raise HTTPException(status_code=404, detail=f"Batch '{req.batch_name}' not found")

    from app.services.authority.cache import lookup_cache, write_cache_entry

    # Cache pre-check: None = never queried; [] = queried, no results
    cached = lookup_cache(batch_dir, req.authority, req.query)
    if cached is not None:
        return ReconcileResponse(candidates=cached, from_cache=True)

    # Dispatch to authority client
    candidates: list[dict] = []
    try:
        if req.authority in GND_TYPES:
            from app.services.authority.gnd import search_gnd
            candidates = await search_gnd(req.query, req.authority)
        elif req.authority == "wikidata":
            from app.services.authority.wikidata import search_wikidata
            candidates = await search_wikidata(req.query)
        elif req.authority == "geonames":
            from app.services.authority.geonames import search_geonames
            candidates = await search_geonames(req.query)
        elif req.authority == "aat":
            from app.services.authority.aat import search_aat
            candidates = await search_aat(req.query)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown authority type: {req.authority}")

    except ValueError as e:
        # GeoNames missing username (or other configuration error)
        raise HTTPException(status_code=503, detail=str(e))

    except RuntimeError as e:
        # Authority API failed after retries (rate limit, network error, etc.)
        # Surface as 502 so frontend can show "API error — retry?" affordance
        raise HTTPException(status_code=502, detail=f"Authority API error: {e}")

    # Cache post-write: always write, including empty [] (no-match cached to avoid re-querying)
    write_cache_entry(batch_dir, req.authority, req.query, candidates)

    return ReconcileResponse(candidates=candidates, from_cache=False)
