"""readonly_paths — path/name resolution for readonly gallery sources (TASK-151a-T1).

Pure backend module. NO API, NO UI, NO frontend.

Split out of core/readonly_producer.py (TASK-151a-T1): the 8 functions below
decide "where does a readonly source's output live, and what does each movie's
folder/filename look like" — output-root resolution, basename/folder-part
construction, and movie-dir allocation. Zero behaviour change versus their
previous home; this module has no import of core.readonly_assets (CD-1).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from core.config import STEM_IMAGE_MODES, iter_gallery_sources
from core.database import get_db_path
from core.organizer import (
    _detect_suffixes,
    _detect_vr_cluster,
    _strip_num_prefixes,
    format_string,
    sanitize_filename,
    truncate_title,
    truncate_to_chars,
)
from core.path_utils import (
    CURRENT_ENV,
    is_path_under_dir,
    normalize_path,
    reverse_path_mapping,
    to_file_uri,
    uri_to_fs_path,
)
from core.readonly_source import _canonical_source_prefix

def _derive_source_name(source_path: str) -> str:
    """Derive an App-managed output-folder name for a readonly source (pure, no I/O).

    basename = sanitize_filename(Path(...).name) — folder-name semantics, `.name`
    not `.stem` (a source folder called "Movies.Archive" must not be truncated to
    "Movies").

    A deterministic short code (sha1[:6] of the canonicalized source path) is
    ALWAYS appended (CD-89a-7 — Opus-pinned Option B, 2026-07-03): the folder name
    depends ONLY on this source's own path, never on sibling sources, so adding or
    removing an unrelated source can never flip an existing source's effective
    output root (that flip would orphan every row already written under it — the
    exact churn 89a exists to eliminate). Two different sources sharing the same
    basename therefore never collide; the same source resolves to the same name on
    every call (stability lock).

    Falls back to ``src-<shortcode>`` when sanitize_filename strips the basename to
    an empty string (e.g. source path is a drive root ``D:\\`` or a UNC share root)
    so an empty folder name is never produced.
    """
    # uri_to_fs_path already normalizes internally (strip URI prefix → unquote →
    # normalize_path with a try/except fallback) — do NOT re-run normalize_path
    # again before handing the result to to_file_uri(). Stacking those two calls
    # is a banned lint idiom (see test_no_normalize_before_to_file_uri) because a
    # standalone normalize_path() raises ValueError on foreign-platform path
    # strings (e.g. a Windows path fed to a Linux CI run), which uri_to_fs_path
    # already guards against via its own try/except.
    fs_path = uri_to_fs_path(source_path)  # uri-no-reverse: native config path (DirectoryConfig.path), no DB-mapped namespace
    canonical = to_file_uri(fs_path)
    shortcode = hashlib.sha1(canonical.encode()).hexdigest()[:6]
    basename = sanitize_filename(Path(fs_path).name)
    if not basename:
        return f"src-{shortcode}"
    return f"{basename}-{shortcode}"


def resolve_output_root(source, config: dict) -> str:
    """Resolve the effective output root for a readonly source (CD-89a-7).

    Reads the GLOBAL flavour (config['scraper']['external_manager']), not a
    per-source field (CD-89a-2: flavour is global).

    - off (or any value not in STEM_IMAGE_MODES) → fixed App-managed folder
      ``output/lib/<derived-source-name>`` (native FS path string, NOT passed
      through to_file_uri — callers normalize_path()/to_file_uri() it themselves,
      matching the existing ``source.output_path`` convention so call sites need
      minimal changes). Structurally guarantees a non-empty output root so off
      sources never abort with zero videos produced.
    - jellyfin/emby/kodi → source.output_path verbatim (may be empty — media-server
      flavours still require the user to configure it; callers keep their existing
      empty-string guards unchanged).
    """
    external_manager = config.get("scraper", {}).get("external_manager", "off")
    if external_manager not in STEM_IMAGE_MODES:
        name = _derive_source_name(source.path)
        return str(get_db_path().parent / "lib" / name)
    return source.output_path


def resolve_owning_output_root(canonical_uri: str, config: dict) -> Optional[tuple]:
    """Find the innermost readonly gallery source that owns ``canonical_uri`` and
    resolve its effective output root (CD-104-5).

    Returns ``(source, output_root, output_uri)`` where ``source`` is the
    ``DirectoryConfig`` (needed downstream by ``_produce_one``), ``output_root``
    is a native FS path string (``normalize_path()``-d), and ``output_uri`` is
    its ``file:///`` form. Returns ``None`` when no readonly source owns the
    path — the router's signal to fall through to its existing (non-readonly)
    sidecar-write code path unchanged.

    Longest-canonical-prefix-wins, mirroring ``is_path_readonly``'s nested-
    source semantics (readonly_source.py) exactly — but resolving to the WHICH
    source (an object), not just a boolean:
    - Enumerate readonly sources (``iter_gallery_sources`` + ``.readonly``),
      canonicalize each with ``_canonical_source_prefix`` (same mapped
      namespace as DB rows), keep the longest prefix that contains
      ``canonical_uri``.
    - No readonly source contains it → ``None`` (not readonly at all).
    - A writable source's prefix ALSO contains it and is >= as long (ties go to
      writable, matching ``is_path_readonly``'s ``best_ro > best_wr`` — a
      strictly-longer readonly prefix wins) → ``None`` (a nested writable
      override; the file is actually writable, not readonly — do not route).
    - Otherwise resolve via ``resolve_output_root(source, config)``. An empty
      result (media-server flavour with no configured ``output_path``) is
      returned as ``(source, '', '')`` rather than ``None`` — the caller still
      knows WHICH source owns the file (for its own "未設定輸出路徑" error
      message) but has to reject the write itself, since an empty root cannot
      be normalize_path()'d/to_file_uri()'d meaningfully.

    Malformed source paths (``_canonical_source_prefix`` raising ``ValueError``,
    e.g. bad UNC forms) are skipped for that one source (mirrors
    ``readonly_source_prefixes``/``writable_source_prefixes``'s own per-entry
    ``except ValueError: continue`` — one dirty config entry must not sink the
    whole resolution).
    """
    gallery = config.get("gallery", {})
    path_mappings = gallery.get("path_mappings", {})

    best_source = None
    best_ro_len = -1
    for src in iter_gallery_sources(gallery):
        if not src.readonly or not src.path:
            continue
        try:
            prefix = _canonical_source_prefix(src.path, path_mappings)
        except ValueError:
            continue
        if is_path_under_dir(canonical_uri, prefix) and len(prefix) > best_ro_len:
            best_ro_len = len(prefix)
            best_source = src

    if best_source is None:
        return None

    best_wr_len = -1
    for src in iter_gallery_sources(gallery):
        if src.readonly or not src.path:
            continue
        try:
            prefix = _canonical_source_prefix(src.path, path_mappings)
        except ValueError:
            continue
        if is_path_under_dir(canonical_uri, prefix) and len(prefix) > best_wr_len:
            best_wr_len = len(prefix)

    if best_wr_len >= best_ro_len:
        return None  # writable override (or a tie — config self-contradiction, favor writable)

    effective = resolve_output_root(best_source, config)
    if not (effective or "").strip():
        return (best_source, '', '')

    output_root = normalize_path(effective)
    output_uri = to_file_uri(output_root, path_mappings)
    return (best_source, output_root, output_uri)


# ---------------------------------------------------------------------------
# T-2: naming helpers (pure functions). Movie-dir resolution itself
#       (_resolve_movie_dir, TASK-89a-T3) lives further below since it depends
#       on _folder_parts defined here.
# ---------------------------------------------------------------------------

def _format_data(meta: dict, source_fs_path: str, config: dict) -> dict:
    """Build format_data dict from scraped meta (off-mode flavour).

    Replicates organizer.py:859-877 (off branch):
    - strip number prefixes from title
    - truncate title to max_title_length
    - detect suffix once (off: unfiltered suffix_keywords)

    The same truncated title feeds both _folder_parts and _build_basename
    so the two never drift (CD-88b-3 / Codex P2).
    """
    number = meta['number']
    title = _strip_num_prefixes(meta.get('title', ''), number)
    title = truncate_title(title, config.get('max_title_length', 50))
    fd: dict = {
        'number': number,
        'title': title,
        'actors': meta.get('actors', []),
        'maker': meta.get('maker', ''),
        'date': meta.get('date', ''),
    }
    fd['suffix'] = _detect_suffixes(
        os.path.basename(source_fs_path),
        config.get('suffix_keywords', []),
    )
    return fd


def _folder_parts(format_data: dict, config: dict) -> list:
    """Return folder layer strings (max 3) replicating organizer.py:915-933."""
    layers = config.get('folder_layers') or [
        p.strip()
        for p in config.get('folder_format', '{num}').replace('\\', '/').split('/')
        if p.strip()
    ]
    max_chars = min(config.get('max_filename_length', 60), 120)
    parts = []
    for layer in layers[:3]:
        part = truncate_to_chars(format_string(layer, format_data, use_fallback=True), max_chars)
        if part:
            parts.append(part)
    return parts


def _build_basename(format_data: dict, source_fs_path: str, config: dict) -> str:
    """Build filename stem (no extension) replicating organizer off-mode filename block.

    Replicates organizer.py:936-971 (off branch):
    - suffix taken from format_data['suffix'] (not recomputed)
    - {suffix} two-pass protection when token present in template
    - vr_tail appended last
    - final cap to max_chars
    - NO multipart / part_tail (off is no-op, CD-88b-3)
    """
    original_filename = os.path.basename(source_fs_path)
    original_ext = os.path.splitext(source_fs_path)[1]

    vr_cluster = _detect_vr_cluster(original_filename)
    vr_tail = f'_{vr_cluster}' if vr_cluster else ''

    # off mode: part_tail always ''
    reserve = len(vr_tail)

    max_filename_chars = min(config.get('max_filename_length', 60), 120)
    max_chars = max_filename_chars - len(original_ext)

    filename_template = config.get('filename_format', '{num} {title}')
    suffix = format_data.get('suffix', '')

    if suffix and '{suffix}' in filename_template:
        no_suffix_data = dict(format_data, suffix='')
        base_without_suffix = format_string(filename_template, no_suffix_data)
        base_budget = max(0, max_chars - len(suffix) - reserve)
        if base_budget == 0:
            filename_base = truncate_to_chars(suffix, max(0, max_chars - reserve))
        else:
            base_without_suffix = truncate_to_chars(base_without_suffix, base_budget)
            filename_base = base_without_suffix + suffix
    else:
        filename_base = format_string(filename_template, format_data)
        filename_base = truncate_to_chars(filename_base, max(0, max_chars - reserve))

    filename_base = filename_base + vr_tail
    filename_base = truncate_to_chars(filename_base, max_chars)
    return filename_base


# ---------------------------------------------------------------------------
# TASK-89a-T3 (CD-89a-3): movie-dir resolution — read DB stored value & reuse
# in place when still valid, else allocate via sanitize_filename(number) +
# increment. Replaces the old owners/_movie_leaf_base/_movie_dir cover-index
# reconstruction model.
# ---------------------------------------------------------------------------

_MAX_INCREMENT = 1000  # guard against a theoretical infinite loop (TASK-89a-T3)


def _resolve_movie_dir(
    repo,
    source_uri: str,
    existing,                    # Optional[Video] — caller already ran repo.get_by_path(source_uri)
    output_root: str,            # fs path (produce_source's existing output_root)
    output_uri: str,             # to_file_uri(output_root, path_mappings)
    format_data: dict,           # feeds _folder_parts (parent layers) + format_data['number'] (leaf)
    config: dict,                # scraper_cfg
    allocated_this_run: set,     # URIs already handed out THIS produce_source call
    path_mappings: dict,
) -> tuple[Path, str]:
    """Resolve the per-movie directory: read-and-reuse, else allocate + increment.

    Returns (movie_dir_fs_path, output_dir_uri_to_store) (TASK-89a-T3 / CD-89a-3).

    Read-and-reuse: if the DB already has a row for this source whose stored
    output_dir still falls under the CURRENT output root, keep using that exact
    directory (idempotent re-scrape, no re-allocation, no orphaning).
    Otherwise (first time, or the effective output root moved) allocate a new
    slot: leaf = sanitize_filename(number), incrementing a numeric suffix until
    a candidate is free in the DB, on disk, and within this run's own
    allocations.
    """
    if existing and existing.output_dir and is_path_under_dir(existing.output_dir, output_uri):
        movie_dir_uri = existing.output_dir
        # TASK-89a-T5 (CD-89a-6): mapped-output 定位。uri_to_fs_path 本身不反解
        # path_mappings，WSL+UNC mapped 輸出根下會定位到錯誤的本機路徑，故在此
        # targeted 反解。只反解回傳給呼叫端的 fs Path，不反解存回 DB 的 URI
        # （movie_dir_uri 維持 existing.output_dir 原值），否則下一輪
        # is_path_under_dir(existing.output_dir, output_uri) 比對會失準。
        movie_dir_fs = uri_to_fs_path(movie_dir_uri)  # uri-no-reverse: already paired with reverse_path_mapping on next line
        if CURRENT_ENV == 'wsl' and path_mappings:
            movie_dir_fs = reverse_path_mapping(movie_dir_fs, path_mappings) or movie_dir_fs
        return Path(movie_dir_fs), movie_dir_uri

    parts = _folder_parts(format_data, config)
    base_leaf = sanitize_filename(format_data['number'])
    n = 1
    while True:
        leaf = base_leaf if n == 1 else f"{base_leaf}-{n}"
        candidate_fs = Path(output_root, *parts, leaf)
        candidate_uri = to_file_uri(str(candidate_fs), path_mappings)
        taken = (
            candidate_uri in allocated_this_run
            or repo.is_output_dir_taken(candidate_uri, exclude_path=source_uri)
            or candidate_fs.exists()
        )
        if not taken:
            break
        n += 1
        if n > _MAX_INCREMENT:
            raise RuntimeError(f"movie_dir increment 超過上限: {base_leaf}")

    allocated_this_run.add(candidate_uri)
    return candidate_fs, candidate_uri


# ---------------------------------------------------------------------------
# TASK-89a-T4 (Codex #3): stale-asset cleanup — reconstruct the previous run's
# basename from the DB row, then wipe that movie's own old singleton/extrafanart
# files, so re-scraping with a corrected title overwrites in place instead of
# piling up `<old>.* + <new>.*` side by side.
#
# T5 follow-up (Codex PR review P2): cleanup runs AFTER the corresponding new
# asset has been written successfully, not before. Singletons (nfo/cover/
# poster/fanart) are cleaned only once `generate_nfo` has already returned
# True, and only the assets whose new write actually succeeded (has_cover/
# has_poster/has_fanart) — so a partial failure (cover download false, or
# generate_nfo raising) leaves the OLD assets on disk instead of deleting them
# up front and then failing to produce replacements. Extrafanart is the
# exception: it's non-critical and each run rewrites the whole set, so it is
# still cleaned before its own download loop.
# ---------------------------------------------------------------------------

def _build_old_base(existing, source_fs_path: str, config: dict) -> str:
    """Reconstruct the basename `_write_movie_assets` used on the PREVIOUS run.

    existing is the Video row already read by produce_source (T3, repo.get_by_path).
    Returns '' (skip cleanup) when there is nothing to clean up:
      - existing is None (first generation for this source file)
      - existing.title is empty (defensive; T3/_upsert_db always writes meta['title'])
      - existing.number is empty (defensive; search_jav/_upsert_db always writes a
        non-empty number, but _format_data has no .get for 'number' — guard here
        rather than let a KeyError/empty leaf surface deep in _build_basename)

    Otherwise, maps the OLD DB fields back onto the same meta-dict shape
    `_format_data` expects (DB → meta key names differ: actresses→actors,
    release_date→date) and replays `_format_data` + `_build_basename` against the
    SAME source_fs_path/config used this run — source_fs_path is the same physical
    source file both times, so suffix/vr_tail/ext are identical across runs and
    only the meta-driven parts (title/number/actors/maker/date) can differ.

    existing.title is the RAW scraped title as stored by _upsert_db (meta['title'],
    not the already-truncated format_data['title']) — running it back through
    _format_data reapplies the same strip/truncate transform that produced the
    original basename, so old_base equals what was actually written last time.
    """
    if existing is None or not existing.title or not existing.number:
        return ''
    old_meta = {
        'number': existing.number,
        'title': existing.title,
        'actors': existing.actresses,
        'maker': existing.maker,
        'date': existing.release_date,
    }
    old_format_data = _format_data(old_meta, source_fs_path, config)
    return _build_basename(old_format_data, source_fs_path, config)
