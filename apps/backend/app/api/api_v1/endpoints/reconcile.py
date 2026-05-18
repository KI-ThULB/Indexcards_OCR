"""Authority reconciliation endpoint. Wave 2 (Plan 11-02) wires in the real authority clients."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path
from app.core.config import get_settings

router = APIRouter()


class ReconcileRequest(BaseModel):
    authority: str   # gnd-persons | gnd-places | gnd-subjects | gnd-corporate-bodies | gnd-works | wikidata | geonames | aat
    query: str
    batch_name: str  # needed to read/write per-batch cache


class ReconcileResponse(BaseModel):
    candidates: List[dict]
    from_cache: bool


@router.post("", response_model=ReconcileResponse)
async def reconcile(req: ReconcileRequest):
    """Query an authority for candidates matching the query string.
    Cache check/write and authority dispatch wired in Plan 11-02.
    """
    settings = get_settings()
    batch_dir = Path(settings.BATCHES_DIR) / req.batch_name
    if not batch_dir.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    from app.services.authority.cache import lookup_cache
    cached = lookup_cache(batch_dir, req.authority, req.query)
    if cached is not None:
        return ReconcileResponse(candidates=cached, from_cache=True)

    # Stub: real clients wired in Plan 11-02
    return ReconcileResponse(candidates=[], from_cache=False)
