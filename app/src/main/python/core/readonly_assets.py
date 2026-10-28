"""readonly_assets — per-movie asset writers for readonly gallery sources
(TASK-151a-T2).

Pure backend module. NO API, NO UI, NO frontend.

Split out of core/readonly_producer.py (TASK-151a-T2): the 10 functions below
decide "how does a readonly source's NFO/cover/poster/fanart/.strm/sample
images land on disk, and how is the previous run's stale output cleaned up" —
stale-asset cleanup, the .strm playback-path mapping/write, curator sidecar
ingest copies, cover/poster/fanart writes, sample-image downloads, and the
top-level _write_movie_assets orchestrator. Zero behaviour change versus
their previous home; depends on core.readonly_paths (TASK-151a-T1) for
basename construction.
"""

from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core import readonly_paths
from core.atomic_write import atomic_move
from core.config import STEM_IMAGE_MODES, normalize_external_manager
from core.cover_attributes import effective_tags
from core.cover_layout import (
    nfo_image_flag,
    resolve_cover_target,
    same_target_verdict,
)
from core.gallery_scanner import IMAGE_EXTENSIONS
from core.logger import get_logger
from core.nfo_stat import NFO_MTIME_REFRESH, nfo_mtime_or_none
from core.organizer import crop_to_poster, download_image, generate_jellyfin_images, generate_nfo
from core.path_utils import is_fs_path_under_dir, to_file_uri, uri_to_local_fs_path

logger = get_logger(__name__)

def _clean_stale_extrafanart(movie_dir: str) -> None:
    """Delete this movie's own previous-run extrafanart samples (`fanart*.jpg`).

    Called from `_write_movie_assets` BEFORE the extrafanart download loop,
    whenever old_base is non-empty (caller's responsibility to gate — first
    generation has nothing to clean). No old_base parameter is needed: the glob
    is scoped to the fixed `extrafanart/` subdir and the `fanart*.jpg` pattern,
    independent of basename. Safe to run pre-write because extrafanart is
    non-critical (a missing sample degrades silently) and each run rewrites the
    whole set from scratch — unlike the singleton assets below, there is no
    "old cover/NFO now missing" failure mode to worry about here.

    Never a bare `*.jpg`/`*.*` glob, never rmtree — both would delete files the
    user placed in the same directory themselves. Missing files are a no-op
    (unlink(missing_ok=True)); this must never raise.
    """
    ef_dir = Path(movie_dir) / 'extrafanart'
    if not ef_dir.is_dir():
        return
    for f in ef_dir.glob('fanart*.jpg'):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            logger.warning("[readonly_producer] stale extrafanart 清除失敗（略過）: %s", f)


def _clean_stale_singletons(
    movie_dir: str,
    old_base: str,
    new_base: str,
    has_cover: bool,
    has_poster: bool,
    has_fanart: bool,
    has_strm: bool = False,
) -> None:
    """Delete this movie's own previous-run singleton assets (nfo/cover/poster/
    fanart), anchored strictly on old_base.

    Called from `_write_movie_assets` AFTER `generate_nfo` has already returned
    True — i.e. only once the new NFO write actually succeeded. This is
    deliberately post-write, not pre-write (T5 follow-up, Codex PR review P2):
    cleaning before writing would delete the OLD assets even when the new write
    fails partway (cover download false, or generate_nfo raising), leaving
    neither the old nor the new assets on disk. Running it after means a failed
    write always leaves the previous run's assets intact.

    No-op when old_base is '' (first generation — nothing to clean) or
    old_base == new_base (title unchanged — the new write already overwrote the
    same-named file in place; deleting here would clobber what generate_nfo /
    download_image / generate_jellyfin_images just wrote, since this runs after
    the write completes).

    Each asset is deleted only when this run's corresponding write actually
    succeeded: `<old_base>.jpg` only when has_cover, `<old_base>-poster.*` only
    when has_poster, `<old_base>-fanart.*` only when has_fanart, `<old_base>.strm`
    only when has_strm (TASK-90a-T3, media-server flavour). A transient
    download/generation failure this run keeps the matching old file on disk
    rather than leaving a hole. `<old_base>.nfo` is unconditional — this
    function is only ever called once nfo_ok is already True.

    Deliberately narrow: exact filenames for the singletons (extension glob
    only for poster/fanart, defensive against a future non-.jpg format). Never
    a bare `*.jpg`/`*.*` glob, never rmtree — both would delete files the user
    placed in the same directory themselves. Missing files are a no-op
    (unlink(missing_ok=True)); this must never raise.
    """
    if not old_base or old_base == new_base:
        return
    d = Path(movie_dir)
    # old_base comes from the scraped title and can legally contain glob
    # metacharacters (sanitize_filename keeps '[' ']' — common in language/sub
    # tags like "[Chinese Sub]"). Escape before globbing the poster/fanart
    # extension patterns, else Path.glob treats '[...]' as a char class and
    # silently misses the file (residual junk survives — a narrow Codex #3
    # recurrence). The nfo/cover singletons use literal joins, no escape needed.
    esc = glob.escape(old_base)
    targets = [d / f"{old_base}.nfo"]
    if has_cover:
        targets.append(d / f"{old_base}.jpg")
    # strm is a media-server flavour extra (TASK-90a-T3): exact filename, no glob
    # (literal join like nfo/cover, no glob.escape needed). Only cleaned when this
    # run actually re-wrote the strm (has_strm) — a transient strm write failure
    # keeps the old <old_base>.strm rather than orphaning it, symmetric with
    # has_cover/has_poster/has_fanart gating. Prevents a title-drift double
    # library entry in Emby/Jellyfin (<old>.strm + <new>.strm side by side).
    if has_strm:
        targets.append(d / f"{old_base}.strm")
    if has_poster:
        targets.extend(d.glob(f"{esc}-poster.*"))
    if has_fanart:
        targets.extend(d.glob(f"{esc}-fanart.*"))
    for target in targets:
        try:
            Path(target).unlink(missing_ok=True)
        except OSError:
            logger.warning("[readonly_producer] stale asset 清除失敗（略過）: %s", target)


# ---------------------------------------------------------------------------
# TASK-90a-T3: media-server .strm sidecar (CD-90a-2 / CD-90a-6)
# ---------------------------------------------------------------------------

def _apply_path_mapping(source_fs_path: str, mappings: dict) -> str:
    """Rewrite a source FS-path prefix to the playback-side namespace.

    strm files are consumed by an external media server (Emby/Jellyfin/Kodi) that
    may see the same physical storage under a DIFFERENT mount path than OpenAver's
    host (e.g. OpenAver on Windows sees ``Z:\\115\\x.mp4`` while the media server
    on the NAS sees ``/volume1/movie/x.mp4``). mappings maps ``local_prefix ->
    remote_prefix``; the matched prefix is swapped and the remainder appended.

    Matching is done in ``file:///`` URI space: both source and each local_prefix
    are converged via ``to_file_uri`` (host-independent, never raises, no
    percent-encoding in this codebase). This fixes two Codex findings:

    - P1 (cross-namespace silent miss): a Windows-display prefix ``C:\\115`` in
      config now matches a WSL-native source ``/mnt/c/115/x.mp4`` (both converge
      to ``file:///C:/115``). Raw-string compare would have silently missed and
      emitted the un-mapped source path.
    - P2 (trailing separator): a local_prefix with a trailing separator
      (``/mnt/z/115/``) no longer misses — the URI form is rstrip'd of ``/``.

    A rule matches when the source URI equals the (trailing-slash-stripped) local
    URI OR the char immediately after it is ``/`` (URIs always use forward-slash,
    so no OS branch). This stops ``file:///Z:/1150/a`` from wrongly matching a
    ``file:///Z:/115`` rule. When several rules match, the LONGEST local URI wins
    (deterministic, independent of dict insertion order). Empty mappings or no
    match returns source_fs_path unchanged (v1 backward compat).

    CD-90a-6: only source/local_prefix are converged (for MATCHING). The remote
    result is written VERBATIM and is NEVER normalized — it is a foreign playback
    namespace (a bare Unix ``/volume1/...`` fed to to_windows_path on a Windows
    host raises). We only rstrip trailing separators off remote_prefix for join
    hygiene; the appended remainder is taken from the URI (always forward-slash).
    """
    if not mappings:
        return source_fs_path
    su = to_file_uri(source_fs_path)  # converge source → file:/// URI (host-independent, no raise)
    matched = []
    for local_prefix, remote_prefix in mappings.items():
        # remote 空的半填規則 skip（PR #93 P2 縱深防禦）：remote='' 會讓下方
        # `remote.rstrip() + su[len(lu):]` 把 local 前綴剝掉只剩後綴（如 /movie.mp4）、
        # 破壞 strm 內容。前端已過濾不存半填規則，此處防手改 config.json。只擋空字串；
        # 非字串 remote 仍照舊流到 rstrip 拋 TypeError → _write_strm best-effort 接（契約不變）。
        if isinstance(remote_prefix, str) and not remote_prefix.strip():
            continue
        lu = to_file_uri(local_prefix).rstrip('/')  # converge + strip trailing sep (P2); URI is always '/'
        if su == lu or (su.startswith(lu) and su[len(lu):len(lu) + 1] == '/'):
            matched.append((lu, remote_prefix))
    if not matched:
        return source_fs_path
    lu, remote_prefix = max(matched, key=lambda kv: len(kv[0]))
    # path-contract-ok: remote 為播放端命名空間、verbatim 寫入不 normalize；僅去尾分隔符做
    # join 衛生（remainder 由 URI 取、恆前導 '/'）。source/local 收斂到 file:/// URI 供比對修
    # Codex P1（跨命名空間 C:\ ↔ /mnt/c/ 靜默失效）+ P2（尾分隔符）。
    return remote_prefix.rstrip('/\\') + su[len(lu):]


def _write_strm(base_stem: str, source_fs_path: str, config: dict, strm_mappings: dict = None) -> bool:
    """Write a single-line ``<base_stem>.strm`` pointing at the source video (best-effort).

    Content = _apply_path_mapping(source_fs_path, mappings) written as one UTF-8
    line, no BOM. The REMOTE side is written verbatim / never normalized; matching
    converges source+local_prefix to file:/// URI space (see _apply_path_mapping /
    CD-90a-6).

    config is the scraper section (produce_source passes scraper_cfg at call site);
    the mapping table defaults to a SAME-LEVEL read — ``config.get('strm_path_mappings', {})``,
    NOT via a nested ``config.get('scraper', ...)`` (that would always yield {} and
    silently disable mappings). This mirrors line ~580's same-level
    ``config.get('external_manager', 'off')`` read.

    strm_mappings (PR #93 五審四次 P2, option C): when provided (not None), it OVERRIDES
    ``config['strm_path_mappings']`` — produce_source passes a FRESH per-file read so the
    generate path uses the current mapping, not the run-start frozen snapshot. This closes
    the disconnect-tail residual: the SSE watcher clears the generate token the instant it
    detects a disconnect, but the producer thread only checks should_abort at each per-file
    checkpoint, so it can finish ONE more file's _write_strm after the token is gone → in that
    window another tab's settings save could land a new mapping (the strm-mapping gate no
    longer sees an in-flight generate) and that last file would otherwise write with the STALE
    frozen mapping and never self-heal. A fresh read makes even that last file use the current
    mapping. None preserves the legacy read (rewrite_strm + unit tests pass config verbatim).

    Best-effort (spec-90 §90a.2.2): strm is an EXTRA product for external media
    servers, not an OpenAver-required asset. A write failure logs a warning and
    returns False — it never raises, never marks the whole movie failed (unlike
    NFO, which is OpenAver's own required metadata). Returns True on success; the
    bool also feeds _clean_stale_singletons' has_strm gating.
    """
    strm_fs = base_stem + '.strm'
    try:
        # mapping + write both inside try: raw config is NOT model_validated on the
        # read path (_load_config_unlocked returns raw dict), so a hand-edited
        # config.json with non-str mapping values could make _apply_path_mapping
        # TypeError. best-effort's promise (§90a.2.2: strm never fails the movie)
        # must hold even then — catch broadly, warn, return False. Any masked bug
        # still surfaces via the warning log.
        mappings = strm_mappings if strm_mappings is not None else config.get('strm_path_mappings', {})
        mapped = _apply_path_mapping(source_fs_path, mappings)
        with open(strm_fs, 'w', encoding='utf-8') as f:
            f.write(mapped)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort auxiliary artifact, must never propagate
        logger.warning("[readonly_producer] strm 寫入失敗（略過，best-effort）: %s (%s)", strm_fs, e)
        return False


# ---------------------------------------------------------------------------
# T-3: write off-flavor assets + DB upsert (plan §5.2 / §6)
# ---------------------------------------------------------------------------

def _copy_curator_sidecar(src: str, dst: str, slot: str) -> Optional[bool]:
    """Curator ``-poster``/``-fanart`` sidecar → the matching output slot,
    VERBATIM. The single preflight-owning choke point for that copy — both
    slots in ``_write_media_images`` go through here, neither calls
    ``shutil.copy2`` on a sidecar itself.

    Tri-state return (there are genuinely three outcomes, and collapsing any
    two of them is what produced the bug below):

    | 回傳 | 意思 | 呼叫端 |
    |---|---|---|
    | ``True``  | ``dst`` 現在持有 curator 原檔的內容 | 記 has_*=True，**不 generate** |
    | ``False`` | 同一檔但無法確認（未知 ``OSError``）| 記 has_*=False，**不 generate**（fail-closed）|
    | ``None``  | 沒複製成功、也沒有 curator 原檔會被蓋掉 | **落回 generate 分支** |

    Codex PR#125 round-2 P1 (2026-08-05) — why the preflight is here at all:
    when the readonly source's output root resolves back onto the source movie
    directory AND the basename lands on the source stem, ``src`` and ``dst``
    are the SAME file (the curator's own sidecar IS the output slot). The old
    code copied first and asked later: ``shutil.copy2`` raised
    ``SameFileError``, the broad ``except`` swallowed it into "copy failed",
    and the slot fell through to the generate branch — whose own
    ``same_target_verdict`` preflight compares ``cover_fs`` vs ``dst``, a
    DIFFERENT pair that is legitimately "not the same file". So
    ``crop_to_poster(cover_fs, poster_path)`` cropped the machine cover
    straight over the curator's hand-picked portrait poster (reproduced:
    379×538 blue → a crop of the 800×538 red cover, md5 changed). OpenAver's
    own UI cannot show this — ``find_cover_image``'s L1.5 prefers ``-fanart``
    — so the damage lands entirely on the Jellyfin/Emby/Kodi side, i.e. the
    exact surface AC5's curator boundary ("**逐位元組保留 curator 原檔**") and
    prd.md 技術決策 #6 ("衍生產物不回寫原檔") exist to protect. It is also a
    REGRESSION of this branch, not a pre-existing bug: before ``_write_cover_copy``
    learned the same-target case (commit 2338c62d/a552f674) the cover step
    itself returned ``has_cover=False`` here and ``_write_media_images`` was
    never reached.

    Why the sidecar copy needs the preflight and not just a ``SameFileError``
    catch: ``shutil.copyfile``'s internal ``_samefile`` swallows ``OSError``
    and returns ``False``, so on a filesystem where ``os.path.samefile`` raises
    (permission denied / some network shares — the case ``same_target_verdict``
    was built for) ``copy2`` proceeds to open the destination ``'wb'`` and
    truncates the very file it is reading from. That is the identical
    corruption CD-112-8 already fenced off at the six ``cover → dst`` write
    sites; the sidecar copies are ``sidecar → dst`` and were therefore
    invisible to that inventory's own ``copy2(cover, *)`` grep (see
    ``core.cover_layout``'s 交棒清單, rows ⑨/⑩).

    ``is_same and certain`` still re-confirms ``dst`` on disk for the same
    reason ``_write_cover_copy`` does (Codex PR#125 round-1 P2): the
    ``src == dst`` cell of ``same_target_verdict`` answers by string comparison
    with zero I/O, and ``src`` here comes from ``resolve_ingest_plan``'s
    ``.exists()`` several I/O hops away. A sidecar that vanished in between is
    NOT a passthrough to report as success — but there is also no curator file
    left to clobber, so that case returns ``None`` (regenerate) rather than
    ``False``.
    """
    is_same, certain = same_target_verdict(src, dst)
    if is_same:
        if not certain:
            logger.warning(
                f"[!] ingest {slot} 無法確認是否為同一檔（fail-closed，不覆寫、不宣稱成功）: {dst}"
            )
            return False
        # 同一檔＝curator 原檔已經就在輸出位置上，本身就是 verbatim passthrough。
        return True if os.path.exists(dst) else None
    try:
        shutil.copy2(src, dst)
        return True
    except shutil.SameFileError:
        # preflight 之後、copy 之前才變成同一檔（別名 race）的 backstop；必須排在
        # 下面的寬 except 之前（SameFileError 是 OSError 子類）。
        return True
    except Exception as e:  # noqa: BLE001 — mirror the generate path's broad catch; any copy failure falls through to generate
        logger.warning(f"[!] ingest {slot} 原樣複製失敗，改由封面重建: {e}")
        return None


def _write_media_images(
    cover_fs: str, base_stem: str, meta: dict, source_media: Optional[dict]
) -> tuple[bool, bool]:
    """Write ``-poster``/``-fanart`` images for one movie. Returns
    ``(has_poster, has_fanart)``.

    ``source_media is None`` (scrape/rescrape, or ingest with no detected
    curator sidecars): delegates to ``generate_jellyfin_images`` EXACTLY as
    before this fix — the ONE source of truth for the "generate from cover"
    path (fanart = copy2(cover); poster = crop_to_poster(cover)) — byte-
    identical for every caller that doesn't carry a 3rd cover_strategy
    element (CD scrape/rescrape byte-identity guarantee).

    ``source_media`` is a dict (ingest, curator sidecars detected — see
    ``resolve_ingest_plan``'s cover-axis docstring): each slot is handled
    independently.
      - A detected sidecar (``source_media['poster']`` / ``['fanart']`` not
        None) is copied VERBATIM via ``_copy_curator_sidecar`` (preflight +
        ``shutil.copy2``) — byte-identical to the source, no crop/focal. An
        ``OSError`` (source vanished mid-run) falls back to the SAME generate
        step the slot would have used had no sidecar been detected at all.
        When the sidecar IS the output slot (collocated curator library — see
        ``_copy_curator_sidecar``'s Codex round-2 P1 note) the copy is a no-op
        that reports success: it must NOT fall through to generate, because
        the generate branch's own preflight compares ``cover_fs`` vs the slot
        — a different pair — and would crop the cover over the curator's file.
      - A missing slot (``None``) always falls back to that generate step —
        this is the pre-fix behaviour for that slot, unchanged.
    """
    number = meta['number']
    maker = meta.get('maker', '')

    if source_media is None:
        imgs = generate_jellyfin_images(cover_fs, base_stem, number=number, maker=maker)
        return imgs.get('poster', False), imgs.get('fanart', False)

    fanart_path = base_stem + '-fanart.jpg'
    poster_path = base_stem + '-poster.jpg'

    # fanart: verbatim copy of curator sidecar, else generate (copy2 of cover
    # — matches generate_jellyfin_images's own fanart step byte-for-byte).
    src_fanart = source_media.get('fanart')
    has_fanart = _copy_curator_sidecar(src_fanart, fanart_path, 'fanart') if src_fanart else None
    if has_fanart is None:
        is_same, certain = same_target_verdict(cover_fs, fanart_path)
        if is_same:
            has_fanart = certain
        else:
            try:
                shutil.copy2(cover_fs, fanart_path)
                has_fanart = True
            except shutil.SameFileError:
                has_fanart = True
            except Exception as e:
                logger.warning(f"[!] generate_jellyfin_images fanart 複製失敗: {e}")
                has_fanart = False

    # poster: verbatim copy of curator sidecar, else generate (crop_to_poster
    # of cover — matches generate_jellyfin_images's own poster step).
    src_poster = source_media.get('poster')
    has_poster = _copy_curator_sidecar(src_poster, poster_path, 'poster') if src_poster else None
    if has_poster is None:
        is_same, certain = same_target_verdict(cover_fs, poster_path)
        if is_same:
            has_poster = certain
        else:
            has_poster = crop_to_poster(cover_fs, poster_path, number=number, maker=maker)

    return has_poster, has_fanart


def _write_cover_copy(src: str, dst: str) -> bool:
    """``cover_strategy == ('copy', src)`` cover write. Returns whether ``dst``
    now holds a valid cover.

    Pre-existing bug found by red-team during 112b pre-merge (2026-08-04):
    when the readonly source's output root sits inside the source tree AND
    ``movie_dir``/``base`` land back on the source directory/stem, ``src``
    and ``dst`` (``resolve_cover_target``'s canonical position) can be the
    SAME file. This was already reachable pre-112; CD-112-7 (curator
    ``-fanart`` promoted to cover source when no same-stem cover exists)
    opened a second path into it. Bare ``shutil.copyfile`` raises
    ``SameFileError`` (an ``OSError`` subclass) in that case, which the old
    bare ``except OSError:`` swallowed into ``has_cover=False`` — skipping
    ALL of poster/fanart generation and writing an empty DB ``cover_path``
    even though the cover is sitting right there on disk, intact (violates
    AC5b). Same ``same_target_verdict`` preflight shape as
    ``generate_jellyfin_images`` (CD-112b-1): ``certain`` — not a bare
    ``True`` — drives the return value (CD-112-8 safety/honesty split);
    ``SameFileError`` is a race backstop for "still-distinct-at-preflight,
    same-by-copy-time" and MUST stay ahead of ``except OSError`` since it
    subclasses it.

    Codex PR#125 P2 (2026-08-05): the ``is_same`` branch additionally requires
    ``dst`` to still be on disk. ``same_target_verdict``'s ``src == dst`` cell
    answers by string comparison alone with zero I/O — it is the ONE cell of the
    five that can return ``(True, True)`` for a path that does not exist (its own
    docstring names this residual and says it "**必須重新評估**" once T3 makes
    string equality the readonly hot path — this is that re-evaluation). The
    other six ``same_target_verdict`` call sites re-confirm ``dst`` a few lines
    earlier; this one does not — ``src`` comes from ``cover_strategy[1]``, whose
    ``.exists()`` check happened back in ``resolve_ingest_plan`` several I/O hops
    away, so an external delete in between lands here as a **false success**:
    ``has_cover=True`` → poster/fanart "generated" → NFO writes dangling
    ``<thumb>``/``<fanart>`` and the DB records a cover that is not there
    (AC5b/AC7 violation). Reported false success is the categorically worse
    outcome under CD-112-8, so this call site pays one ``os.path.exists``.
    The check is deliberately HERE and not inside ``same_target_verdict``:
    ``os.path.exists`` also returns False on permission errors, which would flip
    a legitimately-True verdict for the other six call sites (that argument is
    verbatim in ``cover_layout.same_target_verdict``'s residual note). It is a
    no-op for the ``samefile``-alias cell, which already proved both paths stat.
    """
    is_same, certain = same_target_verdict(src, dst)
    if is_same:
        return certain and os.path.exists(dst)
    if os.path.exists(dst):
        # Collision policy (Codex PR#125 round-3 P1, 2026-08-05): ``dst`` already
        # holds a cover, so NEVER overwrite it — report the existing file as the
        # cover and write nothing.
        #
        # Why this is required, not merely nice: in a collocated layout (output
        # root resolving back onto the source movie directory) a curator library
        # carrying BOTH ``{stem}.jpg`` and ``{stem}-fanart.jpg`` makes the two
        # halves of the flip disagree. ``find_cover_image``'s L1 picks the plain
        # same-stem cover, so CD-112-7 promotes the curator ``-fanart`` to the
        # copy SOURCE; meanwhile ``resolve_cover_target``'s step ① sees that same
        # ``{stem}.jpg`` already on disk and returns it as the TARGET. Result:
        # ``copyfile(curator -fanart → curator {stem}.jpg)`` permanently destroys
        # the second curator original (reproduced: 800×538 red → 1200×675 blue,
        # md5 becomes the fanart's). That is a straight breach of prd.md 技術決策
        # #6 承重牆「衍生產物不回寫原檔」, and it is a REGRESSION of this branch —
        # ``curator_cover_source`` (the promotion) landed in c4bb5508/T3; before
        # it, source and target were the same file and the copy was a no-op.
        #
        # Blast radius is confined to ingest: ``('copy', …)`` has exactly ONE
        # producer (the ingest branch of ``resolve_ingest_plan``), whose contract
        # is local-first / reuse-first — "有 .nfo／封面就地 ingest 零網路". A
        # deliberate overwrite still has its escape hatch: the gear re-scrape
        # emits ``('download', url)``, which goes through ``download_image`` and
        # never reaches this function.
        #
        # ``resolve_cover_target`` only ever returns an ALREADY-EXISTING path via
        # its steps ① / ② — i.e. exactly "a cover is already sitting at a
        # canonical position". Reusing it is the same 沿用 semantics those two
        # steps encode; overwriting it would contradict them.
        return True
    try:
        shutil.copyfile(src, dst)
        return True
    except shutil.SameFileError:
        return True
    except OSError:
        return False


def _reraise_nfo_stat_error(e: OSError) -> None:
    """S6's on_error callback (CD-113b-5, 不得變體): the `.nfo` just written by
    this same call must exist — a stat failure here means a real filesystem
    problem, not "no NFO". Re-raise so it propagates exactly like the
    unguarded `os.stat()` call it replaces (whole produce fails loudly,
    never gets silently recorded as nfo_mtime=0). Deliberately NOT shared
    with `core.database.migrate._reraise_stat_error` — same shape, different
    module, different caller intent (plan-113b CD-113b-5 / Opus 裁決 1).
    """
    raise e


def _download_sample(url: str, dest: str, previews: list, idx: int) -> bool:
    """逐張取劇照：原址優先，該格有代理才退代理（CD-126-3）。

    **用 index 取值，不用裸 `zip()`**——zip 在長度不等時會靜默截斷，等於少下載幾張圖；
    長度不等的正確語意是「那幾格沒有代理」，不是「少下載」。
    preview 為空時**連 kwarg 都不傳**（AC-5：非 metatube 來源逐字元相同）。
    """
    fallback = previews[idx] if idx < len(previews) else ''
    if fallback:
        return download_image(url, dest, fallback_url=fallback)
    return download_image(url, dest)


def _write_movie_assets(
    movie_dir: str,
    meta: dict,
    format_data: dict,
    source_fs_path: str,
    config: dict,
    cover_strategy,
    assets_mode: str = 'full',
    old_base: str = '',
    strm_mappings_getter=None,
    user_tags: Optional[list[str]] = None,
) -> dict:
    """Write nfo + cover + -poster/-fanart + extrafanart to movie_dir.

    full mode (default) returns {'cover_fs': str, 'sample_fs': list[str],
    'nfo_mtime': float}. cover_fs is '' when the cover step produces no file (see
    cover_strategy below). nfo_mtime (TASK-104-T1 / CD-104-4) is the real
    os.stat().st_mtime of the NFO just written — generate_nfo has already raised
    on failure by the time this is read, so the file is guaranteed to exist.

    Codex PR#113 round-3 (2026-07-21) added a `write_nfo` gate here that let a
    readonly produce skip the NFO write. REVERTED (owner-confirmed, round-3
    review): that gate was a P1 data-loss — a title-changing rescrape with
    write_nfo=False would skip writing `<new_base>.nfo` while
    `_clean_stale_singletons` still unlinked the OLD `<old_base>.nfo`, losing
    the NFO entirely while the DB kept a stale nfo_mtime claiming it exists.
    Readonly produce is a HOLISTIC operation (a library entry always has an
    NFO) — the router now rejects write_nfo=false for readonly up front (see
    `_READONLY_NO_NFO_ERROR_MSG` in web/routers/scraper.py) instead of
    threading a skip flag down here. The NFO is therefore always written,
    unconditionally, exactly like every other produce caller.

    samples_only mode (TASK-104-T1 / CD-104-1) returns ONLY {'sample_fs':
    list[str]} — downloads meta['sample_images'] into movie_dir/extrafanart
    UNCONDITIONALLY (NOT gated on config['download_sample_images']: an explicit
    supplemental-fetch call means "yes, get samples") and touches NOTHING else —
    no nfo/cover/poster/fanart/strm, no _clean_stale_extrafanart, no
    _clean_stale_singletons. Keeps a "fetch more samples" action from ever
    clobbering metadata/cover it wasn't asked to touch (Codex P1-c).

    cover_strategy (TASK-104-T1 / CD-104-2) replaces the old binary
    "None=download" rule with an explicit 3-state tuple:
      ('copy', local_fs_path) — copy a LOCAL file already on disk into cover_fs
        (ingest, T2: zero network). Copy failure (missing/unreadable source) →
        has_cover=False, same graceful-failure semantics as a failed download —
        never raises.
      ('none',) — do not write a cover at all (ingest has a .nfo but no cover
        image; must NOT silently fall back to downloading).
      ('download', remote_url) — has_cover = bool(remote_url) and
        download_image(remote_url, cover_fs); byte-identical to the pre-T1
        unconditional-download branch (scrape / gear rescrape, C6).
    poster/fanart: generate_jellyfin_images(...) runs whenever has_cover is
    True AND external_manager in STEM_IMAGE_MODES (CD-111-2) AND cover_strategy
    carries no 3rd element (scrape/rescrape, or ingest with no detected curator
    sidecars). When cover_strategy is the 3-tuple ingest-copy form (see
    resolve_ingest_plan docstring), each detected `{stem}-poster`/`{stem}-fanart`
    sidecar is copied VERBATIM into the output slot instead of being regenerated
    from the cover; a slot with no detected sidecar still falls back to the
    generate step. See `_write_media_images` below.

    old_base (TASK-89a-T4, Codex #3; T5 follow-up, Codex PR review P2): when
    non-empty, this movie's own stale assets from the PREVIOUS run (different
    title → different basename) are deleted — but only AFTER the corresponding
    new asset has been written successfully, and only when old_base differs
    from this run's basename. The singleton assets (nfo/cover/poster/fanart)
    are cleaned only once generate_nfo has already succeeded, and only the
    ones whose new write actually succeeded this run — so a write that fails
    partway (cover download false, generate_nfo raising) leaves the previous
    run's assets on disk instead of deleting them up front and then failing
    to produce replacements. (samples_only never reaches this cleanup — see
    above.)

    Extrafanart is now managed EXCLUSIVELY by the samples_only (補劇照) path
    (P1 grok-review, pre-merge 2026-07-21): full mode only cleans+rewrites the
    extrafanart dir when THIS run itself carries new sample_images to write
    (``old_base and meta.get('sample_images')``) — full-mode ingest/rescrape
    callers always pass ``meta['sample_images'] == []`` (CD-104-3), so on a
    FULL-mode re-entry of an already-produced video (gear rescrape / 放大鏡
    ingest / batch-enrich) this branch is skipped and previously-fetched
    samples on disk survive untouched. A bare ``if old_base:`` would delete
    the extrafanart dir on every full-mode re-entry even though full mode
    never repopulates it, silently wiping 補劇照 output for any video that
    gets re-produced. Any hypothetical future caller that DOES pass full-mode
    samples still gets correct clean+rewrite semantics.

    user_tags (TASK-143-T5, CD-143-5): forwarded verbatim to generate_nfo so a
    rescrape REGENERATES <user_tag> instead of dropping it (the DB row keeps them
    either way — what was lost is the copy a media server reads). _produce_one
    must read them BEFORE _upsert_db overwrites the row. None → [] → byte-identical
    to pre-T5, which is why the ~40 direct test call sites need no change.
    """
    os.makedirs(movie_dir, exist_ok=True)

    if assets_mode == 'samples_only':
        ef_dir = Path(movie_dir) / 'extrafanart'
        os.makedirs(ef_dir, exist_ok=True)
        sample_fs: list = []
        previews = meta.get('preview_sample_images') or []
        for i, url in enumerate(meta.get('sample_images', []), 1):
            dest = str(ef_dir / f'fanart{i}.jpg')
            if _download_sample(url, dest, previews, i - 1):
                sample_fs.append(dest)
        return {'sample_fs': sample_fs}

    new_base = base = readonly_paths._build_basename(format_data, source_fs_path, config)
    base_stem = str(Path(movie_dir) / base)

    # 1) Cover: 3-state strategy (CD-104-2) — see docstring above.
    external_manager = normalize_external_manager(config.get('external_manager', 'off'))
    cover_fs = resolve_cover_target(base_stem, external_manager)
    strategy_kind = cover_strategy[0]
    if strategy_kind == 'copy':
        has_cover = _write_cover_copy(cover_strategy[1], cover_fs)
    elif strategy_kind == 'none':
        has_cover = False
    else:  # 'download' — byte-identical to the pre-T1 unconditional branch (C6)
        remote_url = cover_strategy[1]
        # CD-126-9：fallback 從 `meta` 取，**不動 cover_strategy tuple 的形狀**——
        # `cover_strategy[2]` 在 'copy' 種類下已經是 raw_source_media，同一個索引在不同
        # kind 下代表不同東西，那正是本 branch 要消滅的形狀。
        #
        # ⚠️ 隱含耦合（Stage 2 review P3-5）：primary 來自 `cover_strategy[1]`、fallback
        # 來自 `meta['preview_cover_url']`，**兩個值住在不同容器**。今天成立是因為
        # `('download', ...)` 只在 `resolve_ingest_plan()` 的兩處產生，兩處都是
        # `('download', meta['cover'])`。若日後有人讓 'download' 的網址不再等於
        # `meta['cover']`（例如改吃 NFO 的 <thumb>），直連失敗時會拿**另一張圖**的
        # 代理網址存成封面——使用者拿到錯的封面且看不出來。下面的 assert 是那條的絆線。
        # 不加 runtime assert：它會在唯讀產出跑到一半時崩掉，而這條耦合的破裂後果
        # （封面錯一張）比崩掉輕。真正的防線是「動 resolve_ingest_plan 的人讀到這段」。
        preview_cover = meta.get('preview_cover_url') or ''
        has_cover = bool(remote_url) and (
            download_image(remote_url, cover_fs, fallback_url=preview_cover)
            if preview_cover
            else download_image(remote_url, cover_fs)
        )

    # 2) poster/fanart — media-server flavours only (CD-111-2 fail-closed whitelist); off produces none, matching non-readonly parity.
    if has_cover and external_manager in STEM_IMAGE_MODES:
        raw_source_media = (
            cover_strategy[2]
            if strategy_kind == 'copy' and len(cover_strategy) > 2
            else None
        )
        # An ingest source with neither a -poster nor a -fanart sidecar detected
        # (both slots None) is treated identically to "no 3rd element at all" —
        # falls through to the single generate_jellyfin_images source of truth
        # below, keeping that path (and every test that mocks
        # generate_jellyfin_images directly, e.g. TestIngestFourMatrix) byte-
        # /call-identical to before this fix.
        source_media = (
            raw_source_media
            if raw_source_media and (raw_source_media.get('poster') or raw_source_media.get('fanart'))
            else None
        )
        has_poster, has_fanart = _write_media_images(cover_fs, base_stem, meta, source_media)
    else:
        has_poster = has_fanart = False

    # 3) extrafanart — gated only on config key; per-movie dir already exists (no create_folder).
    # Stale samples from the previous run are cleaned first (whenever old_base is
    # non-empty) regardless of this run's download_sample_images setting, so a
    # re-scrape with samples toggled off still shrinks the old set to zero.
    # P1 grok-review (pre-merge 2026-07-21): gated additionally on
    # meta.get('sample_images') — see docstring's "Extrafanart is now managed
    # EXCLUSIVELY by samples_only" note. Without this, a full-mode RE-ENTRY of
    # an already-produced video (old_base non-empty) with meta['sample_images']
    # always [] (ingest/rescrape, CD-104-3) would delete extrafanart/ and never
    # repopulate it — destroying samples fetched by an earlier 補劇照 call.
    if old_base and meta.get('sample_images'):
        _clean_stale_extrafanart(movie_dir)
    sample_fs: list = []
    if config.get('download_sample_images'):
        ef_dir = Path(movie_dir) / 'extrafanart'
        os.makedirs(ef_dir, exist_ok=True)
        previews = meta.get('preview_sample_images') or []
        for i, url in enumerate(meta.get('sample_images', []), 1):
            dest = str(ef_dir / f'fanart{i}.jpg')
            if _download_sample(url, dest, previews, i - 1):
                sample_fs.append(dest)

    # 4) NFO — title/fields use full meta (not truncated format_data).
    # NFO is a REQUIRED off-complete output: a write failure must NOT be silently
    # treated as success (generate_nfo swallows its own I/O error and returns False).
    # Raise so produce_source counts the item as failed and skips _upsert_db — DB never
    # claims a movie was generated when the NFO is missing ("每片成功生成後寫一筆").
    # Cover/poster/fanart stay best-effort: a missing cover is acceptable per C6
    # (cold title with no image) and self-heals on the next incremental run.
    # Always written (P1 revert, round-3 review 2026-07-21) — see the
    # write_nfo paragraph in this function's docstring for why a skip-NFO
    # gate is never reintroduced here.
    meta['tags'] = effective_tags(os.path.basename(source_fs_path), meta.get('tags', []))
    nfo_fs = base_stem + '.nfo'
    nfo_ok = generate_nfo(
        number=meta['number'],
        title=meta['title'],
        original_title=meta.get('original_title', ''),
        actors=meta.get('actors', []),
        tags=meta.get('tags', []),
        date=meta.get('date', ''),
        maker=meta.get('maker', ''),
        url=meta.get('url', ''),
        output_path=nfo_fs,
        has_poster=nfo_image_flag(base_stem, '-poster', has_poster),
        has_fanart=nfo_image_flag(base_stem, '-fanart', has_fanart),
        director=meta.get('director', ''),
        duration=meta.get('duration'),
        series=meta.get('series', ''),
        label=meta.get('label', ''),
        summary=meta.get('_summary', ''), rating=meta.get('_rating'),
        external_manager=external_manager,
        user_tags=user_tags or [],
        nfo_title_format=config.get('nfo_title_format', '[{num}]{title}'),
    )
    if not nfo_ok:
        raise RuntimeError(f"NFO write failed: {nfo_fs}")
    # CD-104-4 (TASK-104-T1): real write mtime, not a hardcoded 0.0 — nfo_ok is
    # True here so the file is guaranteed to exist (generate_nfo already raised
    # above otherwise). MUTATION LOCK: replacing this stat with a hardcoded 0.0
    # is caught by test_readonly_producer.py::TestUpsertDbAssetsMode's
    # nfo_mtime-positive test (see that file for the mutation-lock comment).
    _NFO_MTIME_POLICY = NFO_MTIME_REFRESH
    nfo_mtime = nfo_mtime_or_none(Path(nfo_fs), on_error=_reraise_nfo_stat_error)

    # 5) strm sidecar — media-server flavours only (TASK-90a-T3). off / non
    # media-server → no strm. best-effort: a write failure returns False and
    # feeds has_strm gating below (transient failure keeps the old strm).
    # strm_mappings_getter 在此（_write_strm 前一刻、封面/NFO 都寫完後）才求值，讓斷線尾巴那片
    # 用「真正落 .strm 那一刻」的映射而非片處理開頭的 snapshot（五審五次 Codex）。短路：只在
    # media-server 分支求值（off 不寫 strm），getter=None → None → _write_strm 回退凍結 config。
    has_strm = (
        _write_strm(
            base_stem, source_fs_path, config,
            strm_mappings=(strm_mappings_getter() if strm_mappings_getter is not None else None),
        )
        if external_manager in STEM_IMAGE_MODES
        else False
    )

    # Singleton stale-cleanup runs LAST, only after the new NFO write is confirmed
    # (T5 follow-up, Codex PR review P2) — see docstring above for why this is
    # post-write rather than pre-write.
    _clean_stale_singletons(movie_dir, old_base, new_base, has_cover, has_poster, has_fanart, has_strm)
    return {'cover_fs': cover_fs if has_cover else '', 'sample_fs': sample_fs, 'nfo_mtime': nfo_mtime}


@dataclass(frozen=True)
class RenameOutcome:
    """`_rename_stale_cover_group` 的回傳型別（CD-151b-4）。

    - `new_cover_uri`：改名成功時的新封面 `file:///` URI；no-op／失敗一律 `None`。
      **不寫 DB**——落地到 `videos.cover_path` 是 T1 的 DB mutator + T4 接線的事。
    - `hard_failure`：`True` 僅代表「中途 I/O 失敗、已嘗試復原」；三種 no-op
      （C-10 真 no-op／C-8 錨點在 movie_dir 外／①b 錨點檔本身不存在）一律
      `False`——它們是安全的零寫入，不是失敗。
    - `moved_pairs`：正向搬移順序的 `(src, dst)` 絕對路徑 tuple；no-op／失敗
      一律 `()`。
    """
    new_cover_uri: Optional[str]
    hard_failure: bool
    moved_pairs: tuple


def _move_cover_slot(src: str, dst: str) -> None:
    """搬一個 slot（正向搬移或復原方向皆呼叫這裡）。src/dst 皆絕對路徑。

    唯一的 `atomic_move` 呼叫 leaf（CD-151b-4 設計決策）——正向搬移、
    `_revert_cover_rename` 的逐一復原，全部收斂到這一個 module-level 函式，
    讓 `tests/unit/test_cover_write_site_inventory.py` 的 AST 呼叫堆疊計數
    （`('core/readonly_assets.py', '_move_cover_slot', 'atomic_move'): 1`）
    不因為外部呼叫幾次而變動。
    """
    atomic_move(src, dst)


def _revert_cover_rename(moved_pairs: tuple) -> None:
    """把 `moved_pairs`（正向搬移順序的 `(src, dst)`）逆序搬回去。

    單一檔案復原失敗不中斷其餘檔案的復原嘗試——每個失敗各自 `logger.error`
    （非 warning：復原失敗代表半套狀態需要人工介入，不是可忽略的邊界情境）。
    """
    for src, dst in reversed(moved_pairs):
        try:
            _move_cover_slot(dst, src)
        except OSError:
            logger.error("改名復原失敗，人工介入: %s <- %s", src, dst)


def _list_dir_names_normcased(movie_dir: str) -> Optional[frozenset]:
    """`movie_dir` 底下所有項目名稱的一次性列舉，`os.path.normcase` 正規化過
    （Windows 大小寫不敏感，維持 `os.path.exists` 舊語意）。

    唯一呼叫端 `_resolve_cover_group_identity`（第五輪 review 效能修正）：
    取代舊版對兩套候選各探 `-poster`／`-fanart` × `IMAGE_EXTENSIONS`（最多
    24 次）的逐檔 `os.path.exists`——`movie_dir` 是單片資料夾、檔案數量有限，
    一次 `os.scandir` 取全部檔名比逐檔 `stat` 便宜得多，尤其是 NAS／SMB
    掛載下每次 `stat` 都是一趟網路來回的場景。

    **回傳型別是 `Optional[frozenset]`，兩種結果不可混淆（Codex 第五輪
    review P2，修正第九輪自己引入的洞）**：
    - **`frozenset()`（可能是空的）＝掃描成功**：目錄讀得到，「裡面確實
      沒有 sibling」是已知事實，兩套候選可以合法地被判定成「都沒有磁碟
      證據」，`old_base_hint` 這時才准補位（off 單封面那格就是靠這個）。
    - **`None` ＝掃描失敗**（目錄不存在／被刪除／權限被拒／NAS 連線中斷，
      皆為 `OSError` 子類）：**不知道**目錄裡有什麼，「沒有證據」與「有
      證據但看不到」無法區分——這不是「兩套都沒有證據」，不准讓
      `old_base_hint` 裁決。呼叫端看到 `None` 必須立刻整組回 `None`，
      不進證據比較、不進提示補位（第九輪把這兩種狀態錯誤地壓成同一個，
      讓失憶的提示在 NAS 暫時性失敗時搶到裁決權，見呼叫端 docstring）。

    **本函式自己不往外拋 `OSError`**——把「失敗」表達成回傳值（`None`）
    而不是例外，呼叫端才能用一個 `is None` 分支處理，不必包 `try/except`。
    """
    try:
        with os.scandir(movie_dir) as it:
            return frozenset(os.path.normcase(entry.name) for entry in it)
    except OSError:
        return None


def _resolve_cover_group_identity(
    old_cover_fs: str, movie_dir: str, old_base_hint: str
) -> Optional[tuple[str, str]]:
    """從錨點檔案路徑解析「片級 stem」與「錨點屬於哪個 slot」（Codex PR#197
    review P2，151b pre-merge 後的新洞）：`cover_base_stem()` 純字串剝一次
    `-poster`/`-fanart` 尾碼，分不出「衍生的 sidecar 尾碼」與「尾碼本來就是
    基底標題的一部分」——例如基底真的叫 `Movie-fanart`、旁邊還有衍生的
    `Movie-fanart-poster.jpg` / `Movie-fanart-fanart.jpg`：naive 剝法會把
    `Movie-fanart.jpg` 誤剝成 `Movie`，讓兩個真正的 sidecar 在被誤剝的 stem
    底下遍尋不著、永遠孤兒留在舊基底，而錯的 sidecar（若恰好存在）被誤當
    成錨點搬進錯的 slot。`_rename_stale_cover_group` 是把這個二義性變成
    實際搬檔案＋DB CAS＋NFO 寫入的第一個呼叫端——**分不出來就不要動**，
    這是本函式存在的唯一理由。

    純函式、唯讀：只呼叫 `os.path.splitext` / `os.path.join` /
    `os.scandir`，**不搬檔、不寫任何東西**。**不呼叫 `cover_base_stem()`
    ——本函式就是要取代那個判斷**，兩者並存會製造第二份可能漂移的推導。

    **第五輪 review 效能修正：證據判定一次性列舉目錄，不逐檔 `os.path.exists`**
    ——舊版對兩套候選各探 `-poster`／`-fanart` × `IMAGE_EXTENSIONS`（6 個），
    最多 24 次 `os.path.exists`；`movie_dir` 是單片資料夾、檔案數量有限，
    `os.scandir(movie_dir)` 一次取得全部檔名，剩下全部是記憶體字串比對。
    這支函式是 `produce_source` 掃全庫的熱路徑——本機是微秒級無感，但在
    NAS／SMB 掛載下每次 `stat`（`os.path.exists` 底層）都是一趟網路來回，
    6000 部片規模會是十幾萬次。詳見 `_list_dir_names_normcased` 的實作。

    回傳 `(old_stem_abs, anchor_stem_suffix)`；`anchor_stem_suffix` 是
    `''`／`'-poster'`／`'-fanart'` 之一，對應 `old_cover_fs` 落在哪個 slot。
    **無法判定回 `None`**——呼叫端必須整組 no-op，不得猜。

    演算法：
    1. **`literal`**：`os.path.splitext(old_cover_fs)[0]`，視為 `''` slot。
    2. **`stripped`**：**只有** `literal` 以 `-poster`／`-fanart` 結尾才成立，
       剝掉該尾碼、視為對應的 sidecar slot。`literal` 不以那兩者結尾時
       只有一套候選，**直接採用 `literal`、立即返回、零磁碟 I/O（連
       `os.scandir` 都不呼叫）、也不看 `old_base_hint`**，不進下面的選擇
       規則——這是絕大多數呼叫（無 `-poster`/`-fanart` 尾碼疑慮的正常片）
       的路徑，效能不能被下面的證據蒐集拖慢。
    3. 選擇規則，依序（**磁碟證據優先於提示**，見下方⚠️為什麼）：
       a. **列一次目錄取證**（不論有沒有給提示都先算）：`_list_dir_names_
          normcased` 回傳 `None` ⇒ **掃描失敗**（目錄不在／被刪除／權限被
          拒／NAS 暫時性失敗，皆為 `OSError` 子類）——**不知道**目錄裡有
          什麼，不是「沒有證據」，**立刻整組回 `None`，跳過下面 b/c/d
          全部**，不准讓 `old_base_hint` 裁決（Codex 第五輪 review P2，
          修正第九輪把「掃描失敗」與「掃描成功但空」錯誤壓成同一個狀態的
          洞）。掃描成功（回傳一個 `frozenset`，可能是空的）才繼續：目錄裡
          有 `{literal_basename}-poster{ext}` 或 `{literal_basename}-fanart{ext}`
          ⇒ 支持 `literal`；目錄裡有 `{stripped_basename}{ext}`（同名封面）
          或 `{stripped_basename}{other_suffix}{ext}`（另一個 sidecar）
          ⇒ 支持 `stripped`。副檔名逐一試 `IMAGE_EXTENSIONS`，**仍然禁止
          glob**（現在是字串比對，本來就用不到）；比對前雙邊都過
          `os.path.normcase`（Windows 大小寫不敏感，維持既有語意）。
       b. **恰好一套有證據 → 採它，即使 `old_base_hint` 指向另一套**——
          證據裁決，提示不得覆蓋。
       c. **兩套都有證據 → 回 `None`**（歧義；提示不得裁決哪一套對）。
       d. **掃描成功、兩套都沒有證據 → `old_base_hint` 才准補位**：
          `os.path.join(movie_dir, old_base_hint)` 精確匹配某個候選的
          stem 就採它；不匹配（或未給提示）⇒ 回 `None`。這是 off 單封面
          （零 sibling 可證）那類佈局唯一能消歧的手段。

    ⚠️ **為什麼提示不能優先於磁碟證據（Codex 第四輪 review P2，修正上一輪
    的錯誤推理）**：上一版本這裡寫的是「提示精確匹配某候選就代表 `old_base`
    尚未失憶」——**這個推理是錯的**。精確匹配只證明兩個字串相等，不證明
    `old_base` 本身仍是權威值。反例：舊基底真的叫 `Movie-fanart`（plain
    `Movie-fanart.jpg` ＋ nested `-poster`／`-fanart` 兩個真 sidecar），
    使用者把標題改成 `Movie`，**上一輪已經把 DB title 更新成 `Movie`**、
    但圖還沒跟上（例如上一輪 `_write_movie_assets` 失敗後只有 DB 收斂，
    圖的改名沒有；或任何其他讓 DB 先行一步的時序）。這一輪 `old_base_hint`
    == `"Movie"`，**恰好精確匹配 `stripped` 候選的 stem**——但這不是因為
    `old_base` 是本輪的權威值，是因為它**已經失憶成新標題本身**、而新標題
    剛好又跟 `stripped` 候選字面相同（`Movie-fanart` 剝掉 `-fanart` 也是
    `Movie`）。若提示在此優先於證據，會選錯 `stripped`，兩個真正的 nested
    sidecar 永遠留在舊基底孤兒（`old_stem_abs == new_stem_abs` 觸發 C-10
    no-op，函式甚至不會嘗試搬移）。**磁碟證據不會說謊**（`literal` 旁真的
    躺著兩個 nested sidecar），因此證據必須優先；提示只在磁碟上完全沒有
    任何一套的佐證時，才允許補位猜一個答案——這仍然不違反 D-151b-9（見
    `_rename_stale_cover_group` docstring 的說明：錨點的權威來源永遠是
    `existing.cover_path`，`old_base` 從頭到尾只是輔助信號，不曾是唯一
    依據）。
    """
    literal_stem = os.path.splitext(old_cover_fs)[0]

    stripped_stem = None
    stripped_anchor = ''
    for suffix in ('-poster', '-fanart'):
        if literal_stem.endswith(suffix):
            stripped_stem = literal_stem[: -len(suffix)]
            stripped_anchor = suffix
            break

    if stripped_stem is None:
        return literal_stem, ''

    other_suffix = '-poster' if stripped_anchor == '-fanart' else '-fanart'
    dir_names = _list_dir_names_normcased(movie_dir)
    if dir_names is None:
        # 掃描失敗（NAS 暫時性失敗／權限被拒／目錄消失）——不知道目錄裡有
        # 什麼，不是「兩套都沒有證據」。立刻整組安全 no-op，不准讓
        # old_base_hint 裁決（見 _list_dir_names_normcased docstring）。
        return None
    literal_basename = os.path.basename(literal_stem)
    stripped_basename = os.path.basename(stripped_stem)
    literal_evidence = any(
        os.path.normcase(literal_basename + sidecar_suffix + ext) in dir_names
        for sidecar_suffix in ('-poster', '-fanart')
        for ext in IMAGE_EXTENSIONS
    )
    stripped_evidence = any(
        os.path.normcase(stripped_basename + ext) in dir_names for ext in IMAGE_EXTENSIONS
    ) or any(
        os.path.normcase(stripped_basename + other_suffix + ext) in dir_names
        for ext in IMAGE_EXTENSIONS
    )

    if literal_evidence and not stripped_evidence:
        return literal_stem, ''
    if stripped_evidence and not literal_evidence:
        return stripped_stem, stripped_anchor
    if literal_evidence and stripped_evidence:
        return None

    # 兩套都沒有磁碟證據——只有這裡才准讓提示補位（見上方⚠️：提示不能證明
    # 自己沒失憶，只能在完全沒有磁碟證據時當最後手段）。
    if old_base_hint:
        hint_stem = os.path.join(movie_dir, old_base_hint)
        if hint_stem == literal_stem:
            return literal_stem, ''
        if hint_stem == stripped_stem:
            return stripped_stem, stripped_anchor
    return None


def _rename_stale_cover_group(
    movie_dir: str,
    existing,
    new_base_name: str,
    path_mappings: dict,
    old_base: str = '',
) -> RenameOutcome:
    """洞一改名機制（CD-151b-4）：標題漂移時把舊基底的封面／poster／fanart 搬到
    `new_base_name`。純函式，不寫 DB、不呼叫 `_produce_one`（接線是 T4 的事）。

    三個固定 slot（`''`／`'-poster'`／`'-fanart'`）逐一列舉，每個 slot 各自逐一
    試 `IMAGE_EXTENSIONS` 的候選副檔名——**禁止 glob**，避免把使用者自己放在
    同資料夾、剛好同前綴的檔案一起改名。

    `old_base`（Codex PR#197 review P2，151b pre-merge 後新洞；第四輪 review
    再次修正優先序）：非權威提示，餵給 `_resolve_cover_group_identity`
    消解「錨點 stem 是否包含衍生尾碼」的二義性（`cover_base_stem()` 的
    naive 剝法分不出來，見該函式 docstring）。預設 `''`（無提示，只看磁碟
    證據）。**磁碟證據優先於提示，提示只在磁碟上兩套解釋都沒有證據時才
    補位**——精確字串匹配不能證明 `old_base` 沒有失憶（見該函式 docstring
    的反例：舊基底 `Movie-fanart` 在 DB title 已先行改成 `Movie` 之後，
    提示會「精確匹配」到錯的 `stripped` 候選）。**不違反 D-151b-9**：錨點
    仍然是 `existing.cover_path`（下面第一步就換算出 `old_cover_fs`），
    `old_base` 從頭到尾只是輔助信號，從來不是「找到舊圖的唯一依據」。

    四種 no-op（皆回傳 `RenameOutcome(None, False, ())`）語意不同：
    - C-10（`old_stem_abs == new_stem_abs`）：完全不碰檔案系統。
    - C-8/AC-12（錨點在 `movie_dir` 之外）：安全 no-op ＋ warning，
      本輪其餘流程照常（不是失敗）。
    - ①b（錨點檔本身不存在）：整組 no-op，連 sibling 的存在性檢查都不做，
      不挑替代 slot 頂替。
    - **二義性無法判定**（`_resolve_cover_group_identity` 回 `None`）：整組
      no-op ＋ warning——literal／stripped 兩套解釋都有磁碟證據、或都沒有，
      分不出「衍生的 sidecar 尾碼」與「尾碼本來就是基底一部分」，這是破壞性
      搬檔操作，分不出來就不要動。

    ⚠️ `os.path.exists(old_cover_fs)`（①b 早退）必須在
    `_resolve_cover_group_identity()` 呼叫之前——錨點檔已被刪除時，識別仍可能
    透過磁碟證據算出一個看似合理的 stem，若不先擋，會誤把 sibling 當成錨點去
    改名（見卡片 DoD⑨／mutation 點 4）。
    """
    _NOOP = RenameOutcome(None, False, ())
    if not existing or not getattr(existing, 'cover_path', None):
        return _NOOP

    old_cover_fs = uri_to_local_fs_path(existing.cover_path, path_mappings)

    if not is_fs_path_under_dir(old_cover_fs, movie_dir):
        logger.warning("[readonly_assets] 舊封面指到 movie_dir 以外，安全 no-op: %s", old_cover_fs)
        return _NOOP

    if not os.path.exists(old_cover_fs):
        logger.warning("[readonly_assets] 舊封面錨點檔已不在磁碟上，安全 no-op: %s", old_cover_fs)
        return _NOOP

    identity = _resolve_cover_group_identity(old_cover_fs, movie_dir, old_base)
    if identity is None:
        logger.warning(
            "[readonly_assets] 無法判定舊封面基底（-poster/-fanart 尾碼是衍生或本身一部分二義），安全 no-op: %s",
            old_cover_fs,
        )
        return _NOOP
    old_stem_abs, anchor_stem_suffix = identity
    new_stem_abs = os.path.join(movie_dir, new_base_name)
    if old_stem_abs == new_stem_abs:
        return _NOOP
    old_suffix = old_cover_fs[len(old_stem_abs):]
    # 窮舉盤點後的重新設計（Codex PR#197 review 第 6 輪的後續，151b-T5 pre-merge
    # 停損規則觸發：`prefer` 那條縫連三輪各補掉上一輪的洞、又開一個新的——見
    # `_rename_stale_cover_group` 呼叫端 commit message 的窮舉表）。
    #
    # 核心洞見：錨點那一個 slot 要搬的檔案，我們**已經知道**——就是 `old_cover_fs`
    # 本身，函式開頭的 `os.path.exists(old_cover_fs)` 已經驗過它存在。它完全不需要
    # 被 `_resolve_slot` 的 `IMAGE_EXTENSIONS` 列舉「找出來」，用列舉去找一個已知
    # 答案，正是前三輪各種洞的共同根：
    #   ① 原始版：`new_cover_fs = new_stem_abs + old_suffix` 與 `group` 的實際搬移
    #     結果脫鉤——若 `_resolve_slot` 選到的候選副檔名跟 `old_suffix` 不同，回傳
    #     的 URI 指向一個從未被搬到的路徑。
    #   ② 修法一：改用 `group` 裡錨點 slot 實際選中的 `dst`——但 `_resolve_slot`
    #     不知道哪個候選才是 DB 真正指的那個，同 slot 多副檔名時可能選到 sibling，
    #     DB 換指到另一張圖的內容。
    #   ③ 修法二（`prefer` 參數）：只在 `len(hits) > 1` 時才生效——
    #     (a) 錨點副檔名不在 `IMAGE_EXTENSIONS`（如 `.tiff`）且同 slot 無其他候選時，
    #         `hits == []`，`prefer` 派不上用場，slot 整個沒進 `group`，`anchor_dst`
    #         留 `None`，最終 `to_file_uri(None, ...)` 崩潰、已搬的其餘 slot 不復原。
    #     (b) 更隱蔽：錨點副檔名不在白名單、但同 slot 恰有一個白名單 sibling時，
    #         `hits` 長度剛好是 1（只有 sibling 命中，錨點本身的副檔名根本不在
    #         `IMAGE_EXTENSIONS` 迴圈裡，永遠不會被列進 `hits`），`len(hits) > 1`
    #         為假，`prefer` 分支完全不會被檢查——直接回傳 `hits[0]`（sibling），
    #         真正的錨點檔案被整個忽略、永遠留在舊基底孤兒，DB 卻悄悄換指到 sibling
    #         的內容。這格窮舉盤點才第一次抓到，比 ③(a) 的崩潰更隱蔽（沒有任何
    #         例外、沒有任何 warning，看起來完全正常）。
    #
    # 新設計：錨點 slot 直接、無條件用 `(old_cover_fs, new_stem_abs + old_suffix)`
    # 這一組 pair——不經過 `_resolve_slot`，因此也不受 `IMAGE_EXTENSIONS` 白名單
    # 限制、不受同 slot sibling 干擾。`anchor_dst` 因此是一個常數運算式，永遠非
    # `None`，永遠等於實際搬移的目的地。`_resolve_slot` 縮回只服務另外兩個非錨點
    # slot 的單純形狀，`prefer` 參數整個消失——減碼優於加碼。
    #
    # sibling 處理：不論錨點副檔名在不在白名單，同一 slot 若還有其他副檔名的檔案，
    # 一律不搬、留在舊基底原地——這不再是「多個候選選一個」的判斷，是「錨點 slot
    # 根本不看候選列表」的必然結果，因此也不再需要單獨的「同一 slot 多個副檔名」
    # warning（那個 warning 描述的是選擇邏輯，新設計沒有選擇可言）。
    #
    # `anchor_stem_suffix`（Codex PR#197 review P2）現在直接來自
    # `_resolve_cover_group_identity` 的回傳值，不再用 `old_suffix.startswith(...)`
    # 對映——那個字串前綴比對與這裡的 `old_suffix` 定義同構，換一個地方猜答案不會
    # 比較準；identity 解析階段已經是唯一真理來源，這裡只單純消費它的結果。
    anchor_dst = new_stem_abs + old_suffix

    def _resolve_slot(stem_suffix):
        hits = [
            old_stem_abs + stem_suffix + ext
            for ext in IMAGE_EXTENSIONS
            if os.path.exists(old_stem_abs + stem_suffix + ext)
        ]
        if len(hits) > 1:
            logger.warning("[readonly_assets] 同一 slot 多個副檔名同時存在，取第一個、其餘不動: %s", hits)
        return hits[0] if hits else None

    group = []
    for stem_suffix in ('', '-poster', '-fanart'):
        if stem_suffix == anchor_stem_suffix:
            # 錨點 slot：已知答案，不列舉、不受 IMAGE_EXTENSIONS 白名單限制。
            group.append((old_cover_fs, anchor_dst))
            continue
        src = _resolve_slot(stem_suffix)
        if src is not None:
            ext = src[len(old_stem_abs) + len(stem_suffix):]
            group.append((src, new_stem_abs + stem_suffix + ext))

    for _src, dst in group:
        if os.path.exists(dst):
            logger.warning("[readonly_assets] 改名撞名，整組放棄: %s", dst)
            return _NOOP

    moved = []
    try:
        for src, dst in group:
            _move_cover_slot(src, dst)
            moved.append((src, dst))
    except OSError:
        _revert_cover_rename(tuple(moved))
        return RenameOutcome(None, True, ())

    # anchor_dst 是常數運算式（new_stem_abs + old_suffix），與錨點 slot 在 group
    # 裡實際搬移的目的地逐字相同、永遠非 None——不再需要事後從 group 反查。
    return RenameOutcome(to_file_uri(anchor_dst, path_mappings), False, tuple(moved))
