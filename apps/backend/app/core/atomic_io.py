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
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable, Union


class DirectorySyncError(OSError):
    """Replace succeeded, but directory durability could not be confirmed."""


class DirectoryCloseError(OSError):
    """Replace and directory fsync succeeded; descriptor cleanup failed."""


class UnsafeFileTypeError(OSError):
    """A registry target must be a regular file, never a symlink or device."""


def check_regular_target(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISREG(mode):
        raise UnsafeFileTypeError("registry_file_type_invalid")


def atomic_write_chunks(path: Union[str, Path], chunks: Iterable[str], *, durable: bool = False, preserve_mode: bool = False, require_regular: bool = False) -> None:
    """Write an iterable of text *chunks* to *path* atomically.

    Streaming form of :func:`atomic_write_text`: chunks are written as they are
    produced, so a large generated file (a 14,000-row consolidated CSV, say) is
    never held in memory as one string.
    """
    target = Path(path)
    if require_regular:
        check_regular_target(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    owns_fd = True
    try:
        # newline="" disables newline translation, so content that deliberately
        # uses CRLF (the consolidated CSV, for Excel) is written byte-for-byte
        # rather than becoming "\r\r\n" on Windows.
        stream = os.fdopen(fd, "w", encoding="utf-8", newline="")
        owns_fd = False  # stream owns the descriptor, including on write failure.
        with stream as f:
            if preserve_mode:
                try:
                    mode = stat.S_IMODE(target.stat().st_mode) & 0o777
                except FileNotFoundError:
                    mode = 0o600
                os.fchmod(f.fileno(), mode)
            for chunk in chunks:
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        if require_regular:
            check_regular_target(target)
        os.replace(tmp_name, str(target))
        if durable:
            try:
                directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            except OSError:
                raise DirectorySyncError("directory_sync_failed") from None
            try:
                os.fsync(directory_fd)
            except OSError:
                try:
                    os.close(directory_fd)
                except OSError:
                    pass  # Keep the unconfirmed-sync error as the primary failure.
                raise DirectorySyncError("directory_sync_failed") from None
            try:
                os.close(directory_fd)
            except OSError:
                raise DirectoryCloseError("directory_close_failed") from None
    except BaseException:
        if owns_fd:
            try:
                os.close(fd)
            except OSError:
                pass  # Preserve the primary failure and still clean the tempfile.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Union[str, Path], text: str, *, durable: bool = False, preserve_mode: bool = False, require_regular: bool = False) -> None:
    """Write *text* to *path* atomically (temp file in the same dir + os.replace)."""
    atomic_write_chunks(path, (text,), durable=durable, preserve_mode=preserve_mode, require_regular=require_regular)


def atomic_write_json(path: Union[str, Path], payload: Any, *, indent: int = 2, durable: bool = False, preserve_mode: bool = False, allow_nan: bool = True, require_regular: bool = False) -> None:
    """Serialise *payload* as UTF-8 JSON and write it to *path* atomically."""
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=indent, allow_nan=allow_nan), durable=durable, preserve_mode=preserve_mode, require_regular=require_regular)
