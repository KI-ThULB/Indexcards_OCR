"""Data-retention service (audit I-3 — storage limitation, GDPR Art. 5(1)(e)).

Policy: auto-purge the working data of *completed* batches once they are older
than RETENTION_DAYS. Encryption at rest is a deployment concern (see
DEPLOYMENT.md); this module bounds how long personal data is kept.

Safeguards (a batch is purgeable ONLY if ALL hold):
  - status == "completed"          → never touch uploaded/running/failed/cancelled
  - not currently processing        → run lock absent
  - not currently exporting         → .exporting marker absent
  - completed_at older than TTL      → RETENTION_DAYS elapsed
  - RETENTION_DAYS > 0               → feature is opt-in; disabled by default

Purge removes images/temp/checkpoint/cache but keeps a minimal non-sensitive
tombstone in history. Every automatic and manual purge is audit-logged by the
caller (endpoints / sweep below).
"""
import logging
from datetime import datetime
from typing import List, Optional

from app.core.audit import log_event
from app.core.config import settings
from app.services.batch_manager import batch_manager

logger = logging.getLogger(__name__)

# Statuses that are candidates for time-based retention. Anything else
# (uploaded, running, failed, cancelled, purged) is never auto-purged.
_PURGEABLE_STATUS = "completed"


def _age_days(iso_ts: Optional[str]) -> Optional[float]:
    if not iso_ts:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(iso_ts)).total_seconds() / 86400
    except ValueError:
        return None


def _blocking_reason(entry: dict) -> Optional[str]:
    """Return why a batch may NOT be auto-purged, or None if it is eligible."""
    name = entry.get("batch_name", "")
    status = entry.get("status", "")
    if status != _PURGEABLE_STATUS:
        return f"status is '{status}', not completed"
    if batch_manager.is_run_active(name):
        return "a run is active"
    if batch_manager.is_exporting(name):
        return "an export is in progress"
    age = _age_days(entry.get("completed_at"))
    if age is None:
        return "no completion timestamp"
    if age < settings.RETENTION_DAYS:
        return f"only {age:.1f}d old (< {settings.RETENTION_DAYS}d)"
    return None


def preview_purgeable() -> dict:
    """Dry-run: list batches that WOULD be auto-purged now, plus why others are skipped.
    Never deletes anything. Safe to call even when retention is disabled."""
    enabled = settings.RETENTION_DAYS > 0
    eligible: List[dict] = []
    skipped: List[dict] = []
    for entry in batch_manager._read_history_raw():
        name = entry.get("batch_name", "")
        if not name:
            continue
        reason = _blocking_reason(entry)
        if reason is None:
            eligible.append({
                "batch_name": name,
                "completed_at": entry.get("completed_at"),
                "age_days": round(_age_days(entry.get("completed_at")) or 0, 1),
            })
        else:
            skipped.append({"batch_name": name, "reason": reason})
    return {
        "enabled": enabled,
        "retention_days": settings.RETENTION_DAYS,
        "eligible": eligible,
        "skipped": skipped,
    }


def run_retention_sweep(request=None) -> dict:
    """Purge all currently-eligible batches. No-op when RETENTION_DAYS == 0.
    Returns {purged: [...], errors: [...]}. Each purge is audit-logged."""
    if settings.RETENTION_DAYS <= 0:
        return {"purged": [], "errors": [], "enabled": False}

    purged: List[str] = []
    errors: List[dict] = []
    preview = preview_purgeable()
    for item in preview["eligible"]:
        name = item["batch_name"]
        try:
            batch_manager.purge_batch_data(name)
            purged.append(name)
            log_event(
                "batch.purge",
                result="success",
                target=name,
                request=request,
                mode="auto-retention",
                age_days=item["age_days"],
            )
        except Exception as e:
            logger.exception("Retention purge failed for %s", name)
            errors.append({"batch_name": name, "error": str(e)})
            log_event("batch.purge", result="failure", target=name, request=request, mode="auto-retention")
    if purged:
        logger.info("Retention sweep purged %d batch(es): %s", len(purged), ", ".join(purged))
    return {"purged": purged, "errors": errors, "enabled": True}
