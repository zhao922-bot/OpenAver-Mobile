"""nfo_stat.py — shared, stateless `.nfo` filesystem-metadata primitive (CD-113b-1/2).

Companion to `core.nfo_read` — the two modules are named symmetrically
(`nfo_read` = content, `nfo_stat` = filesystem metadata) but are deliberately
NOT merged: `nfo_read` extracts fields from an already-parsed
`xml.etree.ElementTree` `<movie>` root (F-1, its failure domain is
`ET.ParseError`), while this module stats the `.nfo` file itself and returns
its `st_mtime` (F-5, its failure domain is `OSError`). Mixing filesystem
access into `nfo_read` would break the content/metadata boundary it already
declares in its own docstring.

This module owns exactly one mechanism: "already-selected sidecar → safe
`stat()` → `Optional[float]`". Everything else — how the sidecar path is
located, whether an existing value should be overwritten, and how the
result gets written to the DB — stays with each caller (spec §2.5).
"""

from pathlib import Path
from typing import Callable, Optional, Union
import os

NFO_MTIME_REFRESH = "refresh"
NFO_MTIME_ON_UPSERT = "on_upsert"
NFO_MTIME_FILL_MISSING = "fill_missing"


def nfo_mtime_or_none(
    target: Union[Path, "os.DirEntry"],
    *,
    on_error: Optional[Callable[[OSError], None]] = None,
) -> Optional[float]:
    """Stat `target` and return its `st_mtime`, or `None` on `OSError`.

    `target` is duck-typed to anything with a `.stat()` method (`Path` or
    `os.DirEntry`) — accepting `os.DirEntry` directly lets callers that
    already hold one from `os.scandir()` avoid re-stat-ing via a fresh
    `Path` (CD-113b-2).

    Only `OSError` (and its subclasses, e.g. `PermissionError`,
    `FileNotFoundError`) is caught. Any other exception is a caller bug and
    must not be swallowed here.

    If `on_error` is given, it receives the original `OSError` instance
    when `.stat()` fails. If `on_error` itself raises, that exception
    propagates out of this function unchanged (this is how callers opt
    into "re-raise" semantics instead of "swallow and return None").
    """
    try:
        return target.stat().st_mtime
    except OSError as e:
        if on_error is not None:
            on_error(e)
        return None
