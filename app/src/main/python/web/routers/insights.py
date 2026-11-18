"""
Insights API 路由 — 片庫分析快照端點

端點：
- GET /api/insights/snapshot — 聚合所需的最小逐部影片欄位＋收藏女優表（CD-156-1）
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from core.database import (
    VideoRepository,
    ActressRepository,
    AliasRepository,
    TagAliasRepository,
    get_db_path,
    init_db,
)
from core.database import version_tracker
from core.database.version_tracker import (
    compute_db_fingerprint,
    compute_etag,
    etag_matches,
    get_showcase_revision,
)
from core.library_titles import (
    first_members,
    release_parts as _release_parts,
    rows_in_library_dirs,
)
from core.actress_photo import get_local_photo_path
from core.logger import get_logger
from core.config import (
    load_config,
    get_gallery_source_paths,
    get_configured_gallery_dirs,
)
from core.cover_attributes import manifest_payload

logger = get_logger(__name__)

router = APIRouter(prefix="/api/insights", tags=["insights"])

_etag_matches = etag_matches
_DEFAULT_VIDEO_REPOSITORY = VideoRepository
_DEFAULT_GET_INSIGHTS_ROWS = VideoRepository.get_insights_rows

_insights_snapshot_cache_lock = threading.Lock()
_insights_snapshot_cache: tuple[tuple, dict] | None = None


def _clear_insights_snapshot_cache() -> None:
    """Clear cached insights snapshot payload (tests/maintenance)."""
    global _insights_snapshot_cache
    with _insights_snapshot_cache_lock:
        _insights_snapshot_cache = None


def _build_alias_lookup(records) -> dict[str, tuple[str, list[str]]]:
    """name.lower() -> (primary_name, names_list)；names_list = [primary] + aliases。

    key 一律小寫（`.lower()`，鏡射前端 `n.toLowerCase()`——
    `web/static/js/pages/showcase/state-base.js` `_loadAliasMap`/`_loadTagAliasMap`
    與 `web/static/js/shared/actress-release-age.js` `resolveFavoriteActressAge` 的
    `nameToGroup` 比對慣例），value 內的 primary/別名字面維持原樣（顯示用）。
    """
    lookup: dict[str, tuple[str, list[str]]] = {}
    for record in records:
        primary = str(record.primary_name or "").strip()
        if not primary:
            continue
        aliases = [
            str(a).strip() for a in (record.aliases or []) if str(a).strip()
        ]
        names_list = [primary, *aliases]
        pair = (primary, names_list)
        lookup[primary.lower()] = pair
        for alias in aliases:
            lookup[alias.lower()] = pair
    return lookup


def _merge_badge_alias_manifest(
    tag_lookup: dict[str, tuple[str, list[str]]],
) -> dict[str, tuple[str, list[str]]]:
    """將 cover-badge 的別名合併進 tag_lookup（CD-156-11 使用者別名群組優先權）。"""
    user_tag_lookup = dict(tag_lookup)
    merged: dict[str, tuple[str, list[str]]] = dict(tag_lookup)

    for rule in manifest_payload():
        canonical_tag = rule["canonical_tag"]
        match_aliases = rule.get("match_aliases", [])
        members = [canonical_tag] + list(match_aliases)

        hit_groups: list[tuple[str, list[str]]] = []
        seen_primaries: set[str] = set()
        for m in members:
            key = m.lower()
            if key in user_tag_lookup:
                primary, group = user_tag_lookup[key]
                if primary not in seen_primaries:
                    seen_primaries.add(primary)
                    hit_groups.append((primary, group))

        num_hits = len(hit_groups)
        if num_hits == 0:
            names_list: list[str] = []
            seen_lower: set[str] = set()
            for m in members:
                m_low = m.lower()
                if m_low not in seen_lower:
                    seen_lower.add(m_low)
                    names_list.append(m)
            pair = (canonical_tag, names_list)
            for m in members:
                merged[m.lower()] = pair

        elif num_hits == 1:
            primary, names_list = hit_groups[0]
            existing_lowers = {n.lower() for n in names_list}
            pair = (primary, names_list)
            for m in members:
                m_low = m.lower()
                if m_low not in existing_lowers:
                    existing_lowers.add(m_low)
                    names_list.append(m)
                merged[m_low] = pair

        else:
            host_primary, host_names_list = hit_groups[0]
            host_lowers = {n.lower() for n in host_names_list}
            pair = (host_primary, host_names_list)
            for m in members:
                m_low = m.lower()
                if m_low not in user_tag_lookup:
                    if m_low not in host_lowers:
                        host_lowers.add(m_low)
                        host_names_list.append(m)
                    merged[m_low] = pair

    return merged


def _canonical_list(values, lookup: dict[str, tuple[str, list[str]]]) -> list[str]:
    """別名合併後去重，保留首次出現的 primary 順序（比對小寫 key，顯示用原樣 primary）。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        name = str(raw).strip()
        if not name:
            continue
        primary, _ = lookup.get(name.lower(), (name, [name]))
        if primary in seen:
            continue
        seen.add(primary)
        result.append(primary)
    return result


def _serialize_record(v, actress_lookup, tag_lookup) -> dict:
    year, month, date = _release_parts(v.release_date)
    return {
        "year": year,
        "month": month,
        "date": date,
        "duration": v.duration,
        "actresses": _canonical_list(v.actresses, actress_lookup),
        "maker": (str(v.maker).strip() or None) if v.maker else None,
        "director": (str(v.director).strip() or None) if v.director else None,
        "series": (str(v.series).strip() or None) if v.series else None,
        "tags": _canonical_list(v.tags, tag_lookup),
    }


@router.get("/snapshot")
def get_insights_snapshot(request: Request):
    """取得片庫分析快照（聚合在瀏覽器；本端點只出匿名最小欄位，CD-156-1）。"""
    global _insights_snapshot_cache
    try:
        db_path = get_db_path()

        if not db_path.exists():
            return JSONResponse({
                "success": True,
                "logicalTitles": 0,
                "physicalRows": 0,
                "years": [],
                "records": [],
                "actressFavorites": {},
            })

        init_db(db_path)

        config = load_config()
        gallery_config = config.get("gallery", {})
        configured_dir_uris, path_mappings = get_configured_gallery_dirs(config)

        projection = {
            "directories": sorted(get_gallery_source_paths(gallery_config)),
            "path_mappings": path_mappings,
        }
        etag = compute_etag(
            get_showcase_revision(), compute_db_fingerprint(db_path), projection
        )

        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(
                status_code=304,
                headers={"ETag": etag, "Cache-Control": "no-cache"},
            )

        can_cache = (
            VideoRepository is _DEFAULT_VIDEO_REPOSITORY
            and VideoRepository.get_insights_rows is _DEFAULT_GET_INSIGHTS_ROWS
        )
        cache_key = None
        if can_cache:
            cache_key = (
                etag,
                str(db_path),
                version_tracker.get_showcase_revision(),
                version_tracker.compute_db_fingerprint(db_path),
            )
            with _insights_snapshot_cache_lock:
                if (
                    _insights_snapshot_cache is not None
                    and _insights_snapshot_cache[0] == cache_key
                ):
                    resp = JSONResponse(_insights_snapshot_cache[1])
                    resp.headers["ETag"] = etag
                    resp.headers["Cache-Control"] = "no-cache"
                    return resp

        repo = VideoRepository(db_path)
        raw_rows = (
            repo.get_insights_rows(configured_dir_uris)
            if hasattr(repo, "get_insights_rows")
            else repo.get_all()
        )
        all_videos = rows_in_library_dirs(raw_rows, configured_dir_uris)
        firsts = first_members(all_videos, path_mappings)

        actress_lookup = _build_alias_lookup(AliasRepository(db_path).get_all())
        tag_lookup = _build_alias_lookup(TagAliasRepository(db_path).get_all())
        tag_lookup = _merge_badge_alias_manifest(tag_lookup)

        records = [
            _serialize_record(v, actress_lookup, tag_lookup)
            for v in firsts
        ]
        years = sorted({r["year"] for r in records if r["year"] is not None})

        favorites_by_primary: dict[str, dict] = {}
        for a in ActressRepository(db_path).get_all():          # 已是 ORDER BY name
            primary, names_list = actress_lookup.get(a.name.lower(), (a.name, [a.name]))
            if a.name not in names_list:                   # 燈箱 group.indexOf(a.name) 是逐字比對，只差大小寫的收藏對不上組
                primary = a.name
            if primary in favorites_by_primary:            # 同組已有更早（字母序更前）的收藏命中，跳過
                continue
            favorites_by_primary[primary] = {
                "birth": a.birth or None,
                "photoName": a.name,
                "hasPhoto": get_local_photo_path(a.name) is not None,
                "auto_focal": a.auto_focal,
                "crop_mode": a.crop_mode,
            }

        payload = {
            "success": True,
            "logicalTitles": len(records),
            "physicalRows": len(all_videos),
            "years": years,
            "records": records,
            "actressFavorites": favorites_by_primary,
        }
        if can_cache and cache_key is not None:
            with _insights_snapshot_cache_lock:
                _insights_snapshot_cache = (cache_key, payload)

        resp = JSONResponse(payload)
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    except Exception as e:
        logger.error("取得片庫分析快照失敗: %s", e)
        return JSONResponse({
            "success": False,
            "error": "取得片庫分析快照失敗",
        }, status_code=500)
