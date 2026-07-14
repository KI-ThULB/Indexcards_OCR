import unicodedata
from typing import List, Optional


def normalize_value(value: str) -> str:
    """Trim, NFC normalize, casefold, diacritic-fold."""
    if value is None:
        return ""
    v = value.strip()
    v = unicodedata.normalize("NFC", v)
    v = v.casefold()
    v = unicodedata.normalize("NFD", v)
    v = "".join(c for c in v if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", v)


def matches_vocabulary(value: str, vocabulary: List[str], fuzzy_distance: Optional[int] = None) -> bool:
    """Check if value matches any entry in vocabulary.

    Uses normalize_value for case-insensitive, diacritic-folded exact matching.
    Opt-in Levenshtein fuzzy matching when fuzzy_distance is set and > 0.
    """
    if not vocabulary:
        return True
    nv = normalize_value(value)
    normed = [normalize_value(v) for v in vocabulary]
    if nv in normed:
        return True
    if fuzzy_distance is not None and fuzzy_distance > 0:
        from rapidfuzz.distance import Levenshtein
        return any(Levenshtein.distance(nv, v) <= fuzzy_distance for v in normed)
    return False
