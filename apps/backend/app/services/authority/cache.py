"""
Per-batch authority cache helpers.
Cache file: data/batches/{batch_name}/authority_cache.json
Shape: { "<authority>:<normalized_query>": [{"label": ..., "uri": ..., "description": ...}, ...] }
Empty array [] means "queried before, no results found" — distinct from absent key (never queried).
Concurrent-write safety: atomic tmp-file rename (last writer wins; keys are independent so benign).
"""
import json
from pathlib import Path
from app.services.validation.vocab_rules import normalize_value


def _cache_path(batch_dir: Path) -> Path:
    return batch_dir / "authority_cache.json"


def read_cache(batch_dir: Path) -> dict:
    """Read the entire cache. Returns empty dict if file absent or corrupt."""
    p = _cache_path(batch_dir)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_cache_entry(batch_dir: Path, authority: str, query: str, candidates: list) -> None:
    """Write a single cache entry atomically via tmp-file rename.
    candidates=[] is a valid entry meaning "queried, no results" — do NOT skip empty lists.
    """
    cache = read_cache(batch_dir)
    key = f"{authority}:{normalize_value(query)}"
    cache[key] = candidates
    p = _cache_path(batch_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.replace(p)  # atomic rename — prevents corrupt JSON on concurrent writes


def lookup_cache(batch_dir: Path, authority: str, query: str):
    """Return cached candidates list, or None if not yet queried.
    Returns [] for a cached no-match (queried before, found nothing).
    Returns None only when the key has never been queried.
    """
    cache = read_cache(batch_dir)
    key = f"{authority}:{normalize_value(query)}"
    return cache.get(key, None)   # None = cache miss; [] = cached no-match


def clear_cache(batch_dir: Path) -> None:
    """Delete the authority_cache.json file. Called by DELETE /authority-cache endpoint."""
    p = _cache_path(batch_dir)
    if p.exists():
        p.unlink()
