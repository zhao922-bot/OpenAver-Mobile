"""Fallback writes through the Android Storage Access Framework.

Android 10 can read a removable SD card with legacy storage permissions but
does not grant arbitrary writes to files below it. The Java StorageBridge
writes through a persisted user-selected document tree in that case.
"""

from __future__ import annotations

import errno
import os

from core.logger import get_logger

logger = get_logger(__name__)

BRIDGE_CLASS = "dev.openaver.mobile.StorageBridge"


class AndroidStorageError(OSError):
    """Base error for SAF fallback failures."""


class AndroidStoragePermissionError(AndroidStorageError):
    """No persisted SAF tree can write the requested path."""


class AndroidStorageWriteError(AndroidStorageError):
    """The SAF bridge rejected a write or failed verification."""


def is_access_error(error: OSError) -> bool:
    """Return whether a filesystem error can reasonably be solved by SAF."""
    return isinstance(error, PermissionError) or error.errno in {
        errno.EACCES,
        errno.EPERM,
        errno.EROFS,
    }


def _bridge():
    if os.environ.get("OPENAVER_MOBILE") != "1":
        return None
    try:
        from java import jclass

        return jclass(BRIDGE_CLASS)
    except Exception:
        logger.debug("Android StorageBridge is unavailable", exc_info=True)
        return None


def has_access(path: str) -> bool:
    bridge = _bridge()
    if bridge is None:
        return False
    try:
        return bool(bridge.hasAccessForPath(str(path)))
    except Exception:
        logger.warning("SAF access probe failed for %s", path, exc_info=True)
        return False


def write_bytes(path: str, data: bytes, *, create_parents: bool = True) -> None:
    if not has_access(path):
        raise AndroidStoragePermissionError(
            "storage_tree_not_authorized"
        )
    bridge = _bridge()
    try:
        error = bridge.writeBytes(
            str(path), bytes(data), bool(create_parents)
        )
    except Exception as exc:
        raise AndroidStorageWriteError(str(exc)) from exc
    if error:
        raise AndroidStorageWriteError(str(error))


def mkdirs(path: str) -> None:
    if not has_access(path):
        raise AndroidStoragePermissionError(
            "storage_tree_not_authorized"
        )
    bridge = _bridge()
    try:
        error = bridge.mkdirs(str(path))
    except Exception as exc:
        raise AndroidStorageWriteError(str(exc)) from exc
    if error:
        raise AndroidStorageWriteError(str(error))


def delete(path: str) -> None:
    if not has_access(path):
        raise AndroidStoragePermissionError(
            "storage_tree_not_authorized"
        )
    bridge = _bridge()
    try:
        error = bridge.delete(str(path))
    except Exception as exc:
        raise AndroidStorageWriteError(str(exc)) from exc
    if error:
        raise AndroidStorageWriteError(str(error))


def rename(source: str, target: str) -> None:
    """Rename within one directory, using SAF only after a direct rename fails."""
    try:
        os.rename(source, target)
        return
    except OSError as exc:
        direct_error = exc

    if not is_access_error(direct_error):
        raise direct_error
    if not has_access(source):
        raise AndroidStoragePermissionError(
            "storage_tree_not_authorized"
        ) from direct_error
    bridge = _bridge()
    try:
        error = bridge.rename(str(source), str(target))
    except Exception as exc:
        raise AndroidStorageWriteError(str(exc)) from exc
    if error:
        raise AndroidStorageWriteError(str(error))
