"""Helpers shared by the missing-plot check and batch backfill."""

from __future__ import annotations

import html
import re
import json
import uuid
import threading
from pathlib import Path
from dataclasses import dataclass
from core.atomic_write import atomic_write

from core.nfo_locator import locate_nfo_for_video
from core.plot_writeback import read_nfo_plots
from core.scrapers.utils import extract_number


class PlotBackfillError(Exception):
    """Typed plot-backfill failure suitable for an SSE result."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class PlotBackfillCandidate:
    file_path: str
    number: str
    title: str
    member_paths: tuple[str, ...]
    nfo_targets: tuple[tuple[str, tuple[str, ...]], ...]
    actors: tuple[str, ...] = ()

    @property
    def nfo_paths(self) -> tuple[str, ...]:
        return tuple(nfo_path for nfo_path, _members in self.nfo_targets)


class PlotTranslationBatch:
    """Server-created scope for translating only plots saved by one search."""

    def __init__(self, db_path, batch_id: str | None = None):
        if batch_id is not None and not re.fullmatch(r'[0-9a-f]{32}', batch_id):
            raise PlotBackfillError('batch_missing')
        self.id = batch_id or uuid.uuid4().hex
        self.path = Path(db_path).parent / 'plot_translation_batches' / (self.id + '.json')
        self.lock = threading.Lock()
        self.items = []
        if batch_id is not None:
            try:
                self.items = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(self.items, list):
                    raise ValueError('invalid batch')
            except (OSError, ValueError):
                raise PlotBackfillError('batch_missing') from None

    def add(self, candidate, nfo_targets, source_plot):
        if not nfo_targets:
            return
        with self.lock:
            self.items.append({
                'file_path': candidate.file_path, 'number': candidate.number,
                'title': candidate.title, 'member_paths': candidate.member_paths,
                'actors': candidate.actors, 'nfo_targets': nfo_targets,
                'source_plot': source_plot,
            })
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with atomic_write(self.path, mode='w', encoding='utf-8', suffix='.json.tmp') as handle:
                json.dump(self.items, handle, ensure_ascii=False)

    def pending(self):
        result = []
        sources = {}
        for item in self.items:
            targets = []
            for path, owners in item['nfo_targets']:
                try:
                    plot, original = read_nfo_plots(path)
                    if plot != item['source_plot'] or original != item['source_plot']:
                        continue
                except Exception:
                    pass  # Let the task report the missing/unreadable NFO.
                targets.append((path, tuple(owners)))
            if targets:
                result.append(PlotBackfillCandidate(
                    file_path=item['file_path'], number=item['number'], title=item['title'],
                    member_paths=tuple(item['member_paths']), nfo_targets=tuple(targets),
                    actors=tuple(item['actors']),
                ))
                sources[item['file_path']] = item['source_plot']
        return result, sources


def clean_summary_text(value: object) -> str:
    """Normalize scraper summary text while preserving paragraph breaks."""
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def candidate_number(video) -> str:
    """Recover a number even when a cache row has a stale NULL value."""
    if video.number:
        return str(video.number).strip()
    filename = str(video.path or "").rstrip("/").rsplit("/", 1)[-1]
    return extract_number(filename) or extract_number(video.title or "") or ""


def find_missing_plot_candidates(
    groups,
    config: dict,
    path_mappings: dict,
) -> list[PlotBackfillCandidate]:
    """Return one item per logical video that has an empty existing NFO plot.

    No-NFO rows are deliberately excluded: they belong to the existing
    missing-NFO repair queue, which creates the sidecar with full metadata.
    """
    plot_cache: dict[str, bool] = {}
    candidates: list[PlotBackfillCandidate] = []

    for group in groups:
        missing_targets: dict[str, list[str]] = {}
        for member in group.members:
            try:
                nfo_path, _error = locate_nfo_for_video(
                    member,
                    config,
                    path_mappings,
                )
            except Exception:
                continue
            if not nfo_path:
                continue
            has_plot = plot_cache.get(nfo_path)
            if has_plot is None:
                try:
                    plot, _original = read_nfo_plots(nfo_path)
                except Exception:
                    # Unreadable/ambiguous sidecars must not produce a queue that
                    # can never succeed. The normal NFO maintenance surfaces them.
                    plot_cache[nfo_path] = True
                    continue
                has_plot = bool(plot.strip())
                plot_cache[nfo_path] = has_plot
            if not has_plot:
                owners = missing_targets.setdefault(nfo_path, [])
                if member.path not in owners:
                    owners.append(member.path)

        if not missing_targets:
            continue

        representative = next(
            (member for member in group.members if candidate_number(member)),
            group.members[0],
        )
        candidates.append(
            PlotBackfillCandidate(
                file_path=representative.path,
                number=candidate_number(representative),
                title=representative.title or "",
                member_paths=tuple(member.path for member in group.members),
                nfo_targets=tuple(
                    (nfo_path, tuple(owners))
                    for nfo_path, owners in missing_targets.items()
                ),
                actors=tuple(representative.actresses or ()),
            )
        )

    return candidates
