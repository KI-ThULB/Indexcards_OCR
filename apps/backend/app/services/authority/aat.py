"""Getty AAT authority client via W3C Reconciliation Service API v0.2.
Endpoint: https://services.getty.edu/vocab/reconcile/aat
Protocol: POST with application/x-www-form-urlencoded body: queries={"q1":{"query":"...","limit":5}}
Response: {"q1": {"result": [{"id": "aat/300178684", "name": "...", "score": 100.0, ...}]}}
URI construction: extract numeric ID from "aat/NNNNNN" → http://vocab.getty.edu/aat/NNNNNN
Use POST (not GET) to avoid URL length issues with special characters in queries.
Rate limit: ~60 req/min conservative (not formally documented). 429 → retry via base.py.
"""
import json
import re
from .base import fetch_with_retry


async def search_aat(query: str) -> list[dict]:
    """Search Getty AAT for top-5 subject/concept candidates.
    Returns list of {"label": ..., "uri": ..., "description": ...}.
    Canonical URI: http://vocab.getty.edu/aat/{numericId} (concept URI, not page URI).
    """
    queries_param = json.dumps({"q1": {"query": query, "limit": 5}})

    data = await fetch_with_retry(
        "https://services.getty.edu/vocab/reconcile/aat",
        method="POST",
        data={"queries": queries_param},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    results = data.get("q1", {}).get("result", [])
    candidates = []
    for r in results:
        raw_id = r.get("id", "")
        # Extract numeric ID from "aat/300178684" format
        m = re.match(r"^aat/(\d+)$", raw_id)
        if m:
            uri = f"http://vocab.getty.edu/aat/{m.group(1)}"
        else:
            # Fallback: use raw_id as-is if format changes
            uri = raw_id
        label = r.get("name", "")
        description = r.get("description", "")
        if label and uri:
            candidates.append({"label": label, "uri": uri, "description": description})
    return candidates
