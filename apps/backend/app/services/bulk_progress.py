"""Publishing bulk-run progress over the existing WebSocket.

No new transport: the run reuses ``/api/v1/ws/task/{channel}`` with channel id
``bulk:<bulk_run_id>``. ``ws_manager`` is already keyed by an arbitrary string,
keeps the Origin allow-list plus ``?token=`` handshake check unchanged, and
already replays the last state on connect — which is what makes a browser
reload or reconnect pick a running bulk job back up.

:func:`publish_bulk_progress` is deliberately **synchronous**. It stores the
latest state immediately (so an HTTP poll or a fresh WebSocket connection always
sees current numbers) and schedules the socket fan-out on the running loop when
there is one. That lets the orchestrator publish from both async and sync code
paths without threading an event loop through every call site.
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from app.models.schemas import BulkFolderProgress, BulkProgress
from app.services.bulk_manager import bulk_manager
from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)


def bulk_channel(bulk_run_id: str) -> str:
    """The WebSocket channel id for a run."""
    return f"bulk:{bulk_run_id}"


def to_progress(run: Dict[str, Any]) -> BulkProgress:
    """Project run state onto the wire model (folder names and counts only)."""
    return BulkProgress(
        bulk_run_id=run["bulk_run_id"],
        name=run.get("name", ""),
        status=run.get("status", "queued"),
        provider=run.get("provider", ""),
        model=run.get("model"),
        folders_total=int(run.get("folders_total", 0)),
        folders_completed=int(run.get("folders_completed", 0)),
        images_total=int(run.get("images_total", 0)),
        images_processed=int(run.get("images_processed", 0)),
        images_failed=int(run.get("images_failed", 0)),
        current_folder=run.get("current_folder"),
        current_batch_id=run.get("current_batch_id"),
        last_image=run.get("last_image"),
        created_at=run.get("created_at"),
        started_at=run.get("started_at"),
        completed_at=run.get("completed_at"),
        interrupted_at=run.get("interrupted_at"),
        error=run.get("error"),
        pause_requested=bool(run.get("pause_requested")),
        cancel_requested=bool(run.get("cancel_requested")),
        schema_fields=list(run.get("schema_fields", [])),
        folders=[
            BulkFolderProgress(
                source_folder=f.get("source_folder", ""),
                batch_name=f.get("batch_name"),
                status=f.get("status", "pending"),
                images_total=int(f.get("images_total", 0)),
                images_processed=int(f.get("images_processed", 0)),
                images_failed=int(f.get("images_failed", 0)),
                started_at=f.get("started_at"),
                completed_at=f.get("completed_at"),
                error=f.get("error"),
            )
            for f in run.get("folders", [])
        ],
    )


def publish_bulk_progress(bulk_run_id: str) -> Optional[BulkProgress]:
    """Store and broadcast the run's current state. Never raises.

    Progress reporting must not be able to abort a 14,000-card run, so any
    failure here is logged and swallowed.
    """
    try:
        run = bulk_manager.get_run(bulk_run_id)
        if run is None:
            return None
        progress = to_progress(run)
    except Exception:
        logger.exception("Could not build bulk progress for %s", bulk_run_id)
        return None

    channel = bulk_channel(bulk_run_id)
    # Store first: a reconnecting client is served from this even if the
    # fan-out below cannot be scheduled.
    ws_manager.bulk_states[channel] = progress
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return progress  # no loop (e.g. a sync test) — state is stored, nothing to send
    loop.create_task(_send(channel, progress))
    return progress


async def _send(channel: str, progress: BulkProgress) -> None:
    try:
        await ws_manager.broadcast_bulk_progress(channel, progress)
    except Exception:
        logger.exception("Could not broadcast bulk progress on %s", channel)
