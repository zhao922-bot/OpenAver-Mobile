"""Best-effort AI post-processing after a video is written to the library.

The ingest path must never fail because an optional AI service is unavailable.
Each enabled feature runs in its own FIFO worker so a slow translation cannot
delay similarity indexing or tagging for the next video.
"""

from __future__ import annotations

import asyncio
import functools
import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from core.ai_services import similar_index, similar_state, tags_backfill_policy, tags_state
from core.ai_services.tagging import TaggingFailure, tag_video_sync
from core.config import load_config
from core.database import VideoRepository
from core.focal import requires_face_detection
from core.focal_trigger import maybe_submit_video_focal
from core.logger import get_logger
from core.multipart_group import resolve_group
from core.path_utils import uri_to_local_fs_path
from core.title_language import (
    title_needs_translation as _title_needs_translation,
    translation_result_issue,
)
from core.title_writeback import apply_title_writeback
from core.translate_service import create_translate_service
from core.user_tags_write import hold_nfo_write

logger = get_logger(__name__)

ITEMS = ("translate", "similar", "faces", "tags")
_TAGS_NOTIFY_KEY = "notif.ai_tags_unreachable"


@dataclass(frozen=True)
class Verdict:
    run: bool
    reason: str = ""


@dataclass(frozen=True)
class Plan:
    translate: Verdict
    similar: Verdict
    faces: Verdict
    tags: Verdict

    def items(self):
        return tuple((name, getattr(self, name)) for name in ITEMS)


@dataclass(frozen=True)
class IngestContext:
    video_uri: str
    route: str
    notify: bool
    cfg: dict
    row: object
    members: tuple


def _flag_on(cfg: dict, *keys) -> bool:
    current = cfg
    for key in keys:
        if not isinstance(current, dict):
            return False
        current = current.get(key)
        if current is None:
            return False
    return bool(current)


def video_label(row) -> str:
    if row.number:
        return str(row.number)
    return os.path.basename(row.path or "")


def format_log(route, row, plan: Plan) -> str:
    def one(verdict: Verdict) -> str:
        return "run" if verdict.run else f"skip({verdict.reason})"

    return (
        f"[post_ingest] route={route} video={video_label(row)} "
        f"translate={one(plan.translate)} similar={one(plan.similar)} "
        f"faces={one(plan.faces)} tags={one(plan.tags)}"
    )


def _decide_translate(cfg: dict, row, skip_translate: bool = False) -> Verdict:
    if not _flag_on(cfg, "translate", "enabled"):
        return Verdict(False, "off")
    if skip_translate:
        return Verdict(False, "preserve_title")
    locale = (cfg.get("general") or {}).get("locale") or "zh-CN"
    if not _title_needs_translation(
        row.title or "", locale, row.actresses or ()
    ):
        return Verdict(False, "title_in_target_language")
    return Verdict(True)


def _decide_similar(cfg: dict, row, index_ready: bool) -> Verdict:
    if not _flag_on(cfg, "ai_services", "image_similar", "enabled"):
        return Verdict(False, "off")
    if not row.cover_path:
        return Verdict(False, "no_cover")
    if not index_ready:
        return Verdict(False, "index_not_ready")
    return Verdict(True)


def _decide_faces(row, skip_faces: bool, cover_exists: bool) -> Verdict:
    if skip_faces:
        return Verdict(False, "own_trigger")
    if not requires_face_detection(row.number or "", row.maker or ""):
        return Verdict(False, "not_uncensored")
    if not row.cover_path or not cover_exists:
        return Verdict(False, "no_cover")
    return Verdict(True)


def _decide_tags(cfg: dict, row, already_tagged: bool = False) -> Verdict:
    if not _flag_on(cfg, "ai_services", "tags", "enabled"):
        return Verdict(False, "off")
    if not row.cover_path:
        return Verdict(False, "no_cover")
    if already_tagged:
        return Verdict(False, "already_tagged")
    return Verdict(True)


def decide(
    cfg: dict,
    row,
    *,
    skip_faces: bool,
    index_ready: bool,
    cover_exists: bool,
    skip_translate: bool = False,
    tags_already_processed: bool = False,
) -> Plan:
    return Plan(
        translate=_decide_translate(cfg, row, skip_translate),
        similar=_decide_similar(cfg, row, index_ready),
        faces=_decide_faces(row, skip_faces, cover_exists),
        tags=_decide_tags(cfg, row, tags_already_processed),
    )


def _index_ready() -> bool:
    from core.database import EmbeddingRepository

    return similar_index._incremental_allowed(
        EmbeddingRepository().get_index_state()
    )


def _path_mappings(cfg: dict) -> dict:
    return (cfg.get("gallery") or {}).get("path_mappings") or {}


def _cover_exists(row, cfg: dict) -> bool:
    if not row.cover_path:
        return False
    return os.path.exists(
        uri_to_local_fs_path(row.cover_path, _path_mappings(cfg))
    )


def _group_members(repo, row, cfg: dict) -> tuple:
    try:
        group = resolve_group(repo, row.path, _path_mappings(cfg))
    except Exception:
        logger.warning(
            "[post_ingest] multipart group lookup failed video=%s",
            video_label(row),
            exc_info=True,
        )
        group = None
    return tuple(group.members if group is not None else (row,))


def _tags_already_processed(repo, members: tuple) -> bool:
    if not members:
        return False
    try:
        return all(repo.get_ai_tagged_at(member.path) is not None for member in members)
    except Exception:
        logger.warning(
            "[post_ingest] AI tag state lookup failed",
            exc_info=True,
        )
        return False


class _Lane:
    def __init__(self, item: str):
        self.item = item
        self.queue: queue.Queue = queue.Queue()
        self.thread: Optional[threading.Thread] = None


_LANES: dict[str, _Lane] = {}
_LANES_LOCK = threading.Lock()


def _lane_main(lane: _Lane) -> None:
    while True:
        job = lane.queue.get()
        if job is None:
            return
        try:
            job()
        except Exception:
            logger.exception("[post_ingest] lane job crashed item=%s", lane.item)
        finally:
            lane.queue.task_done()


def _get_lane(item: str) -> _Lane:
    with _LANES_LOCK:
        lane = _LANES.get(item)
        if lane is None:
            lane = _LANES[item] = _Lane(item)
        if lane.thread is None:
            lane.thread = threading.Thread(
                target=_lane_main,
                args=(lane,),
                name=f"post-ingest-{item}",
                daemon=True,
            )
            lane.thread.start()
        return lane


def _submit(item: str, job: Callable[[], None]) -> None:
    _get_lane(item).queue.put(job)


def _row_stale(fresh, row) -> bool:
    if fresh is None:
        return True
    return any(
        getattr(fresh, field) != getattr(row, field)
        for field in ("title", "original_title", "nfo_mtime")
    )


def _job_translate(ctx: IngestContext) -> Optional[str]:
    locale = (ctx.cfg.get("general") or {}).get("locale") or "zh-CN"
    service = create_translate_service(ctx.cfg.get("translate") or {}, locale)
    translated = asyncio.run(
        service.translate_or_raise(
            ctx.row.title,
            {
                "actors": ctx.row.actresses or [],
                "number": ctx.row.number or "",
            },
        )
    )
    issue = translation_result_issue(
        ctx.row.title,
        translated,
        locale,
        proper_terms=ctx.row.actresses or (),
    )
    if issue is not None:
        return issue

    mappings = _path_mappings(ctx.cfg)
    with hold_nfo_write():
        repo = VideoRepository()
        fresh_group = _group_members(repo, ctx.row, ctx.cfg)
        if tuple(member.path for member in fresh_group) != tuple(
            member.path for member in ctx.members
        ):
            return "stale_group"
        for member in fresh_group:
            fresh = repo.get_by_path(member.path)
            if _row_stale(fresh, member):
                return "stale_row"
            result = apply_title_writeback(
                repo,
                fresh,
                translated,
                None,
                ctx.cfg,
                mappings,
            )
            if not result.get("success"):
                return result.get("error") or "write_failed"
    return None


def _job_similar(ctx: IngestContext) -> Optional[str]:
    outcome = similar_index.index_one(ctx.video_uri)
    if outcome == "indexed":
        return None
    if outcome == "unreachable" and ctx.notify:
        if similar_state.note_failure():
            similar_index._notify_unreachable()
    return outcome


def _is_unreachable_failure(exc: BaseException) -> bool:
    return tags_backfill_policy.stop_reason(exc) not in (None, "disabled")


def _job_tags(ctx: IngestContext) -> Optional[str]:
    try:
        tag_video_sync(ctx.video_uri, config=ctx.cfg)
    except TaggingFailure as exc:
        if ctx.notify and _is_unreachable_failure(exc):
            if tags_state.note_hook_failure():
                tags_state.emit(_TAGS_NOTIFY_KEY)
        return exc.reason
    return None


def _job_faces(ctx: IngestContext) -> Optional[str]:
    if not ctx.row.cover_path:
        return "no_cover"
    cover_fs = uri_to_local_fs_path(
        ctx.row.cover_path, _path_mappings(ctx.cfg)
    )
    maybe_submit_video_focal(
        ctx.row.number,
        ctx.row.maker,
        ctx.video_uri,
        cover_fs,
        cover_path_uri=ctx.row.cover_path,
    )
    return None


def _run_item(item: str, ctx: IngestContext) -> None:
    try:
        reason = None
        try:
            if item == "translate":
                reason = _job_translate(ctx)
            elif item == "similar":
                reason = _job_similar(ctx)
            elif item == "tags":
                reason = _job_tags(ctx)
            elif item == "faces":
                reason = _job_faces(ctx)
        except Exception as exc:
            reason = type(exc).__name__
        if reason is not None:
            logger.warning(
                "[post_ingest] %s failed reason=%s video=%s",
                item,
                reason,
                video_label(ctx.row),
            )
    except Exception:
        logger.exception("[post_ingest] run_item failed item=%s", item)


def begin_round() -> None:
    """Reset per-round notification suppression. Never raises."""
    try:
        tags_state.new_round()
        similar_state.new_round()
    except Exception:
        logger.exception("[post_ingest] begin_round failed")


def run_after_ingest(
    video_uri: str,
    *,
    route: str,
    skip_faces: bool = False,
    notify: bool = False,
    skip_translate: bool = False,
) -> None:
    try:
        _run_after_ingest(
            video_uri,
            route=route,
            skip_faces=skip_faces,
            notify=notify,
            skip_translate=skip_translate,
        )
    except Exception:
        logger.exception(
            "[post_ingest] run_after_ingest failed video=%s",
            video_uri,
        )


def _run_after_ingest(
    video_uri: str,
    *,
    route: str,
    skip_faces: bool,
    notify: bool,
    skip_translate: bool,
) -> None:
    cfg = load_config()
    translate_on = _flag_on(cfg, "translate", "enabled")
    similar_on = _flag_on(cfg, "ai_services", "image_similar", "enabled")
    tags_on = _flag_on(cfg, "ai_services", "tags", "enabled")
    if skip_faces and not (translate_on or similar_on or tags_on):
        return

    repo = VideoRepository()
    row = repo.get_by_path(video_uri)
    if row is None:
        logger.warning(
            "[post_ingest] route=%s video=%s skip(row_missing)",
            route,
            os.path.basename(video_uri),
        )
        return

    members = _group_members(repo, row, cfg)
    index_ready = _index_ready() if similar_on and row.cover_path else False
    cover_exists = (
        _cover_exists(row, cfg)
        if not skip_faces and row.cover_path
        else False
    )
    tags_done = tags_on and _tags_already_processed(repo, members)
    plan = decide(
        cfg,
        row,
        skip_faces=skip_faces,
        index_ready=index_ready,
        cover_exists=cover_exists,
        skip_translate=skip_translate,
        tags_already_processed=tags_done,
    )
    logger.info("%s", format_log(route, row, plan))
    ctx = IngestContext(
        video_uri=video_uri,
        route=route,
        notify=notify,
        cfg=cfg,
        row=row,
        members=members,
    )
    for name, verdict in plan.items():
        if not verdict.run:
            continue
        try:
            if name == "faces":
                _run_item("faces", ctx)
            else:
                _submit(name, functools.partial(_run_item, name, ctx))
        except Exception:
            logger.exception(
                "[post_ingest] item failed item=%s video=%s",
                name,
                video_uri,
            )
