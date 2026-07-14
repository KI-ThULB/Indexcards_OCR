"""
Per-batch authority cache helpers.
Cache file: data/batches/{batch_name}/authority_cache.json
Shape: { "<authority>:<normalized_query>": {"candidates": [...], "ts": "<iso>"} }
  candidates=[] means "queried before, no results found" — distinct from absent key.
Legacy shape (bare list value) is still read transparently and treated as never-expiring.
TTL: entries older than AUTHORITY_CACHE_TTL_DAYS are ignored on read and pruned on write
  (0 = no expiry — previous behaviour). See config.AUTHORITY_CACHE_TTL_DAYS (audit I-3).
Concurrent-write safety: atomic tmp-file rename (last writer wins; keys are independent so benign).
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from app.core.config import settings
from app.services.validation.vocab_rules import normalize_value


def _cache_path(batch_dir: Path) -> Path:
    return batch_dir / "authority_cache.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_expired(entry: dict) -> bool:
    """True if a wrapped entry is older than the configured TTL (0 = never)."""
    ttl_days = settings.AUTHORITY_CACHE_TTL_DAYS
    if ttl_days <= 0:
        return False
    ts = entry.get("ts")
    if not ts:
        return False  # legacy/undated entries never expire
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(ts)
    except ValueError:
        return False
    return age.total_seconds() > ttl_days * 86400


def read_cache(batch_dir: Path) -> dict:
    """Read the entire raw cache. Returns empty dict if file absent or corrupt."""
    p = _cache_path(batch_dir)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _candidates_of(value):
    """Extract the candidates list from either the wrapped or legacy entry shape."""
    if isinstance(value, dict):
        return value.get("candidates", [])
    return value  # legacy bare-list entry


def write_cache_entry(batch_dir: Path, authority: str, query: str, candidates: list) -> None:
    """Write a single cache entry atomically via tmp-file rename.
    candidates=[] is a valid entry meaning "queried, no results" — do NOT skip empty lists.
    Expired entries are pruned opportunistically on each write.
    """
    cache = read_cache(batch_dir)
    # Opportunistic prune of expired entries (keeps the file bounded).
    if settings.AUTHORITY_CACHE_TTL_DAYS > 0:
        cache = {
            k: v for k, v in cache.items()
            if not (isinstance(v, dict) and _is_expired(v))
        }
    key = f"{authority}:{normalize_value(query)}"
    cache[key] = {"candidates": candidates, "ts": _now_iso()}
    p = _cache_path(batch_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp.replace(p)  # atomic rename — prevents corrupt JSON on concurrent writes


def lookup_cache(batch_dir: Path, authority: str, query: str):
    """Return cached candidates list, or None if not yet queried (or expired).
    Returns [] for a cached no-match (queried before, found nothing).
    Returns None when the key has never been queried or its entry has expired.
    """
    cache = read_cache(batch_dir)
    key = f"{authority}:{normalize_value(query)}"
    if key not in cache:
        return None
    value = cache[key]
    if isinstance(value, dict) and _is_expired(value):
        return None  # treat expired as a miss → re-query
    return _candidates_of(value)


def clear_cache(batch_dir: Path) -> None:
    """Delete the authority_cache.json file. Called by DELETE /authority-cache endpoint."""
    p = _cache_path(batch_dir)
    if p.exists():
        p.unlink()
