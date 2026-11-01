"""Desktop-first media filesystem operations with Android SAF fallback."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Union

from core import android_storage
from core.atomic_write import atomic_write
from core.logger import get_logger

logger = get_logger(__name__)

PathLike = Union[str, Path]


def write_bytes(
    destination: PathLike,
    payload: bytes,
    *,
    suffix: str = ".media.tmp",
) -> None:
    """Atomically write bytes, falling back to the Android SAF bridge."""
    with atomic_write(
        destination,
        mode="wb",
        suffix=suffix,
        mobile_fallback=True,
    ) as handle:
        handle.write(payload)


def write_text(
    destination: PathLike,
    text: str,
    *,
    suffix: str = ".text.tmp",
) -> None:
    """Atomically write UTF-8 text, falling back to the Android SAF bridge."""
    with atomic_write(
        destination,
        mode="w",
        encoding="utf-8",
        suffix=suffix,
        mobile_fallback=True,
    ) as handle:
        handle.write(text)


def copy_file(source: PathLike, destination: PathLike) -> None:
    """Copy a sidecar verbatim, using SAF when the direct copy is denied."""
    try:
        shutil.copy2(source, destination)
        return
    except OSError as error:
        if not android_storage.is_access_error(error):
            raise
        payload = Path(source).read_bytes()
        write_bytes(destination, payload, suffix=".copy.tmp")
        logger.info("file copied through Android SAF: %s", destination)


def ensure_directory(path: PathLike) -> None:
    """Create a directory, using SAF when the direct operation is denied."""
    try:
        os.makedirs(path, exist_ok=True)
        return
    except OSError as error:
        if not android_storage.is_access_error(error):
            raise
        if not android_storage.has_access(str(path)):
            raise android_storage.AndroidStoragePermissionError(
                "storage_tree_not_authorized"
            ) from error
        android_storage.mkdirs(str(path))


def delete_file(path: PathLike) -> None:
    """Delete a file, treating a missing path as a successful no-op."""
    try:
        os.unlink(path)
        return
    except FileNotFoundError:
        return
    except OSError as error:
        if not android_storage.is_access_error(error):
            raise
        if not android_storage.has_access(str(path)):
            raise android_storage.AndroidStoragePermissionError(
                "storage_tree_not_authorized"
            ) from error
        android_storage.delete(str(path))
