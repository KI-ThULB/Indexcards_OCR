"""GND authority client via Lobid API.
GND sub-collection filter values (exact strings for Lobid filter=type:X):
  gnd-persons        → Person
  gnd-places         → PlaceOrGeographicName
  gnd-subjects       → SubjectHeading
  gnd-corporate-bodies → CorporateBody
  gnd-works          → Work
Rate: 6000 req/min simple queries — lenient; no special throttle needed.
"""
from .base import fetch_with_retry, INDEXCARDS_USER_AGENT

TYPE_MAP = {
    "gnd-persons":          "Person",
    "gnd-places":           "PlaceOrGeographicName",
    "gnd-subjects":         "SubjectHeading",
    "gnd-corporate-bodies": "CorporateBody",
    "gnd-works":            "Work",
}


async def search_gnd(query: str, authority_type: str) -> list[dict]:
    """Search Lobid GND for top-5 candidates.
    Returns list of {"label": ..., "uri": ..., "description": ...}.
    """
    gnd_type = TYPE_MAP.get(authority_type, "AuthorityResource")
    data = await fetch_with_retry(
        "https://lobid.org/gnd/search",
        params={"q": query, "filter": f"type:{gnd_type}", "format": "json", "size": "5"},
        headers={"User-Agent": INDEXCARDS_USER_AGENT},
    )
    candidates = []
    for m in data.get("member", []):
        label = m.get("preferredName", "")
        uri = m.get("id", "")
        # biographicalOrHistoricalInformation is a list; take first entry as description
        bio = m.get("biographicalOrHistoricalInformation") or []
        description = bio[0] if bio else ""
        if label and uri:
            candidates.append({"label": label, "uri": uri, "description": description})
    return candidates
