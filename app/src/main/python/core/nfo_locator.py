"""Locate the sidecar NFO used by a library video.

The lightbox plot API and maintenance backfills must agree on which NFO is
authoritative.  Keeping that decision here prevents one feature from reading a
file while another silently writes a different one.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.nfo_utils import find_sidecar_nfos
from core.path_utils import is_path_under_dir, uri_to_local_fs_path
from core.readonly_paths import resolve_owning_output_root


def _locate_output_nfo(video, output_uri: str, path_mappings: dict):
    if not video.output_dir or not output_uri:
        return None, "no_nfo"
    if not is_path_under_dir(video.output_dir, output_uri):
        return None, "no_nfo"

    output_dir = Path(uri_to_local_fs_path(video.output_dir, path_mappings))
    video_path = Path(uri_to_local_fs_path(video.path, path_mappings))
    try:
        exact = find_sidecar_nfos(output_dir / video_path.name)
        if exact:
            return str(exact[0]), None
        with os.scandir(output_dir) as entries:
            candidates = sorted(
                entry.path
                for entry in entries
                if entry.is_file() and entry.name.lower().endswith(".nfo")
            )
    except FileNotFoundError:
        return None, "no_nfo"
    except OSError:
        return None, "nfo_unreadable"
    if len(candidates) > 1:
        return None, "nfo_ambiguous"
    if not candidates:
        return None, "no_nfo"
    return candidates[0], None


def locate_nfo_for_video(video, config: dict, path_mappings: dict):
    """Return ``(nfo_path, error_code)`` for one database video row."""
    owning = resolve_owning_output_root(video.path, config)
    if owning is not None:
        return _locate_output_nfo(video, owning[2], path_mappings)

    video_path = Path(uri_to_local_fs_path(video.path, path_mappings))
    candidates = find_sidecar_nfos(video_path)
    if not candidates:
        return None, "no_nfo"
    if len(candidates) > 1:
        return None, "nfo_ambiguous"
    return str(candidates[0]), None
