"""Atomic JSON writes for on-disk state.

Every persistent file in this application is JSON on disk (``batches.json``,
``templates.json``, ``checkpoint.json``, ``run.json``). A plain ``open(path,
"w")`` truncates first, so a crash or reboot mid-write leaves a truncated,
unparseable file — losing hours of extraction state. These helpers write to a
temp file in the *same directory* (so ``os.replace`` stays on one filesystem and
is therefore atomic), fsync it, then move it into place. A crash leaves either
the old file or the new one, never a half-written one.

One implementation, used by every writer of long-lived state.
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Union


def atomic_write_chunks(path: Union[str, Path], chunks: Iterable[str]) -> None:
    """Write an iterable of text *chunks* to *path* atomically.

    Streaming form of :func:`atomic_write_text`: chunks are written as they are
    produced, so a large generated file (a 14,000-row consolidated CSV, say) is
    never held in memory as one string.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        # newline="" disables newline translation, so content that deliberately
        # uses CRLF (the consolidated CSV, for Excel) is written byte-for-byte
        # rather than becoming "\r\r\n" on Windows.
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            for chunk in chunks:
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(target))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Union[str, Path], text: str) -> None:
    """Write *text* to *path* atomically (temp file in the same dir + os.replace)."""
    atomic_write_chunks(path, (text,))


def atomic_write_json(path: Union[str, Path], payload: Any, *, indent: int = 2) -> None:
    """Serialise *payload* as UTF-8 JSON and write it to *path* atomically."""
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=indent))
