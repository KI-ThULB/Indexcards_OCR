"""Strict JSON registries; callers hold the SAR-04a registry gate for RMW."""
import json
import os
import stat
import errno
from pathlib import Path
from typing import Any, Callable

from app.core.atomic_io import (atomic_write_json, DirectorySyncError, DirectoryCloseError, UnsafeFileTypeError, check_regular_target)
from app.core.transactions import TransactionError


class RegistryError(TransactionError):
    code = "registry_invalid"


class RegistryReadError(RegistryError):
    code = "registry_unreadable"


class RegistryWriteError(RegistryError):
    code = "registry_write_failed"


class RegistryDurabilityError(RegistryError):
    code = "registry_durability_uncertain"


class RegistryFileTypeError(RegistryError):
    code = "registry_file_type_invalid"


class RegistryCleanupError(RegistryError):
    code = "registry_directory_close_failed"


def _open_regular(path, flags):
    # NOFOLLOW covers an alias swap at open; NONBLOCK prevents FIFO stalls.
    try:
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise RegistryFileTypeError() from None
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RegistryFileTypeError()
    except BaseException:
        os.close(fd)
        raise
    return fd


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistryError()
        result[key] = value
    return result


def _constant(_value):
    raise RegistryError()


def read_registry(path: Path, validate: Callable[[Any], None]) -> list:
    try:
        check_regular_target(path)
        with open(path, encoding="utf-8", opener=_open_regular) as stream:
            data = json.load(stream, object_pairs_hook=_object, parse_constant=_constant)
    except UnsafeFileTypeError:
        raise RegistryFileTypeError() from None
    except FileNotFoundError:
        return []  # Both registries are initialised lazily on the first mutation.
    except (UnicodeError, json.JSONDecodeError):
        raise RegistryError() from None
    except OSError:
        raise RegistryReadError() from None
    validate(data)
    return data


def write_registry(path: Path, data: list, validate: Callable[[Any], None]) -> None:
    validate(data)
    try:
        atomic_write_json(path, data, durable=True, preserve_mode=True, allow_nan=False, require_regular=True)
    except UnsafeFileTypeError:
        raise RegistryFileTypeError() from None
    except DirectoryCloseError:
        raise RegistryCleanupError() from None
    except DirectorySyncError:
        raise RegistryDurabilityError() from None
    except Exception:
        raise RegistryWriteError() from None
