"""Fill explicitly selected library fields from a single source per field."""
from collections import Counter
from pathlib import Path
from threading import RLock

from core import enricher
from core.android_storage import AndroidStoragePermissionError
from core.config import get_configured_gallery_dirs
from core.cover_layout import resolve_cover_target
from core.database import VideoRepository
from core.element_sources import ELEMENTS
from core.gallery_scanner import VideoScanner
from core.i18n import get_config_locale, t
from core.library_titles import rows_in_library_dirs
from core.media_io import ensure_directory
from core.logger import get_logger
from core.multipart_group import VideoGroup, logical_video_groups
from core.nfo_locator import locate_nfo_for_video
from core.nfo_read import nfo_merged_tags
from core.nfo_updater import parse_nfo, replace_nfo_tags
from core.path_utils import is_path_under_dir, to_file_uri, uri_to_local_fs_path
from core.plot_backfill import PlotBackfillCandidate, PlotTranslationBatch, candidate_number, clean_summary_text
from core.plot_writeback import fill_empty_nfo_plot
from core.readonly_paths import _build_old_base, _resolve_movie_dir, _format_data, resolve_owning_output_root
from core.video_extensions import get_video_extensions
from core.scraper import search_jav_single_source
from core.title_language import plot_needs_translation
from core.title_writeback import strip_illegal_xml_chars

logger = get_logger(__name__)
# Two simultaneous fill requests may choose different sources. Recheck the
# live row and filesystem under this lock before committing either result.
_WRITE_LOCK = RLock()


_FIELD_VALUES = {
    'cover': ('cover', 'api.cover_not_found'),
    'plot': ('_summary', 'plots.error_no_summary'),
    'samples': ('sample_images', 'samples.error_no_sample_images'),
    'tags': ('tags', 'scanner.tag_source_no_tags'),
}


class _NeedCard(Exception):
    pass


class _FieldError(Exception):
    """A localization key suitable for showing in a field result."""


def _strings(values):
    if not isinstance(values, list):
        return []
    cleaned = (strip_illegal_xml_chars(value).strip() for value in values if isinstance(value, str))
    return list(dict.fromkeys(filter(None, cleaned)))


def _card_value(card, key, error):
    if card is None:
        raise _NeedCard
    value = card.get(key)
    if key in ('tags', 'sample_images'):
        value = _strings(value)
    elif key == '_summary':
        value = strip_illegal_xml_chars(clean_summary_text(value))
    if not value:
        raise _FieldError(error)
    return value


def _lookup(number, source):
    if not number:
        raise _FieldError('scanner.source_rename_missing_number')
    try:
        card = search_jav_single_source(number, source=source, surface_access_errors=True)
    except Exception as exc:
        logger.warning('Element lookup failed for %s at %s (%s)', number, source, type(exc).__name__)
        raise _FieldError('plots.error_search_failed') from exc
    if not card:
        raise _FieldError('plots.error_not_found')
    ids = {card[key] for key in ('source', '_source') if card.get(key)}
    if ids != {source}:
        raise _FieldError('scanner.batch_unknown_source')
    return card


class _Movie:
    def __init__(self, repo, config, group, shared_folder, cancel, scanner):
        self.repo = repo
        self.config = config
        self.group = group
        self.number = next(filter(None, map(candidate_number, group.members)), '')
        self.mappings = config.get('gallery', {}).get('path_mappings', {})
        self.manager = config.get('scraper', {}).get('external_manager', 'off')
        self.shared_folder = shared_folder
        self.scanner = scanner
        self.cancel = cancel
        self.cards = {}
        self.plot_targets = {}
        self.source_plot = ''

    def require_value(self, row, element, card):
        if element == 'tags' and _strings(row.tags):
            return
        key, error = _FIELD_VALUES[element]
        _card_value(card, key, error)

    def paths(self, row, element, card, *, defer_output=False):
        video = Path(uri_to_local_fs_path(row.path, self.mappings))
        owning = resolve_owning_output_root(row.path, self.config)
        stem = video.stem
        if owning:
            _, output_root, output_uri = owning
            if not output_uri or (row.output_dir and not is_path_under_dir(row.output_dir, output_uri)):
                raise _FieldError('samples.error_output_root_missing')
            scraper = self.config.get('scraper', {})
            stem = _build_old_base(row, str(video), scraper) or video.stem
            if row.output_dir:
                folder = Path(uri_to_local_fs_path(row.output_dir, self.mappings))
            else:
                self.require_value(row, element, card)
                meta = dict(number=self.number, title=row.title, actors=row.actresses,
                            maker=row.maker, date=row.release_date)
                folder, uri = _resolve_movie_dir(
                    self.repo, row.path, row, output_root, output_uri,
                    _format_data(meta, str(video), scraper), scraper, set(), self.mappings,
                )
            if not folder.resolve().is_relative_to(Path(output_root).resolve()):
                raise _FieldError('samples.error_output_root_missing')
            if not defer_output and not folder.is_dir():
                self.require_value(row, element, card)
                ensure_directory(folder)
            if not defer_output and not row.output_dir:
                if not self.repo.set_output_dir_if_empty(row.path, uri):
                    raise _FieldError('samples.error_db_write_failed')
                row.output_dir = uri
        else:
            if not video.is_file():
                raise _FieldError('samples.error_file_not_found')
            folder = video.parent
        nfo = folder / (stem + '.nfo')
        if element != 'samples':
            located, error = locate_nfo_for_video(row, self.config, self.mappings)
            if error and error != 'no_nfo' and (defer_output or element != 'cover'):
                raise _FieldError('plots.error_nfo_unreadable')
            if located:
                nfo = Path(located)
        if (element != 'samples' and nfo.is_symlink()) or nfo.parent.resolve() != folder.resolve():
            raise _FieldError('plots.error_nfo_unreadable')
        return nfo, bool(owning)

    def ensure_nfo(self, row, nfo, asset_path=None):
        if nfo.exists():
            return
        # A new sidecar must survive a rescan without erasing cached metadata.
        # Seed solely from this row; never serialize the whole scraper card.
        asset_path = asset_path or nfo
        created = enricher._write_nfo(
            str(nfo), self.number, enricher._video_to_meta(row), write_nfo=True,
            overwrite_existing=False, has_subtitle=False, user_tags=row.user_tags or [],
            external_manager=self.manager, has_poster=asset_path.with_name(asset_path.stem + '-poster.jpg').is_file(),
            has_fanart=asset_path.with_name(asset_path.stem + '-fanart.jpg').is_file(),
            nfo_title_format=self.config.get('scraper', {}).get('nfo_title_format', '[{num}]{title}'),
        )
        if not created:
            raise _FieldError('plots.error_nfo_write_failed')

    def sync_mtime(self, row, nfo):
        mtime = nfo.stat().st_mtime
        if row.nfo_mtime != mtime and not self.repo.update_nfo_mtime(row.path, mtime):
            raise _FieldError('plots.error_db_write_failed')

    def fill_text(self, element, row, nfo, card):
        root = None
        if nfo.is_file():
            _, root = parse_nfo(str(nfo))
            if root is None:
                raise _FieldError('plots.error_nfo_unreadable')
        if element == 'plot':
            if root is not None and (root.findtext('plot') or '').strip():
                if str(nfo) in self.plot_targets:
                    self.plot_targets[str(nfo)].append(row.path)
                    self.sync_mtime(row, nfo)
                return False
            plot = _card_value(card, '_summary', 'plots.error_no_summary')
            original = (root.findtext('originalplot') or '').strip() if root is not None else ''
            self.ensure_nfo(row, nfo)
            changed = fill_empty_nfo_plot(nfo, new_plot=plot, new_original=original or plot)
            if changed and (not original or original == plot):
                self.source_plot = plot
                self.plot_targets[str(nfo)] = [row.path]
            self.sync_mtime(row, nfo)
            return changed

        disk_tags = nfo_merged_tags(root) if root is not None else []
        cached = _strings(row.tags)
        if disk_tags and cached:
            return False
        tags = disk_tags or cached or _card_value(card, 'tags', 'scanner.tag_source_no_tags')
        if not disk_tags:
            self.ensure_nfo(row, nfo)
            if not replace_nfo_tags(str(nfo), tags):
                raise _FieldError('scanner.tag_source_nfo_failed')
        if not cached and not self.repo.update_tags_if_changed(row.path, tags):
            raise _FieldError('scanner.tag_source_db_failed')
        self.sync_mtime(row, nfo)
        return True

    def has_other_movies(self, folder):
        if self.shared_folder:
            return True
        members = {Path(uri_to_local_fs_path(r.path, self.mappings)) for r in self.group.members}
        extensions = get_video_extensions(self.config)
        return any(p.suffix.lower() in extensions and p not in members and p.is_file()
                   for p in folder.iterdir())

    def fill_cover(self, row, nfo, readonly, card):
        thumb = None
        if nfo.is_file():
            _, root = parse_nfo(str(nfo))
            if root is not None:
                thumb = root.findtext('thumb')
        cover = self.scanner.find_cover_image(str(nfo), thumb)
        if cover and not readonly and self.has_other_movies(nfo.parent):
            if Path(cover).stem.casefold() not in {
                nfo.stem.casefold(), (nfo.stem + '-poster').casefold(), (nfo.stem + '-fanart').casefold(),
            }:
                cover = self.scanner._resolve_thumb_path(thumb, nfo.parent) if thumb else ''
        if not cover:
            url = _card_value(card, 'cover', 'api.cover_not_found')
            cover = resolve_cover_target(str(nfo.with_suffix('')), self.manager)
            if Path(cover).is_symlink() or not enricher._write_cover(str(nfo), url, True, False,
                    external_manager=self.manager, preview_cover_url=card.get('preview_cover_url', '')):
                raise _FieldError('api.cover_not_found')
        uri = to_file_uri(cover, self.mappings)
        if not self.repo.update_cover_path_preserve_focal(row.path, uri, row.cover_path):
            raise _FieldError('plots.error_db_write_failed')
        return True

    def fill_samples(self, row, nfo, readonly, card):
        if not readonly and self.has_other_movies(nfo.parent):
            raise _FieldError('samples.error_multi_video_folder')
        folder = nfo.parent / 'extrafanart'
        if folder.is_symlink():
            raise _FieldError('samples.error_sample_write_failed')
        def disk_images():
            if not folder.is_dir():
                return []
            if any(p.is_symlink() for p in folder.iterdir()):
                raise _FieldError('samples.error_sample_write_failed')
            return [to_file_uri(str(p), self.mappings)
                    for p in sorted(VideoScanner._iter_extrafanart_images(folder))
                    if enricher._is_valid_sample_file(str(p))]

        uris = disk_images()
        failed = 0
        if not uris:
            urls = _card_value(card, 'sample_images', 'samples.error_no_sample_images')
            try:
                result = enricher._write_extrafanart(str(nfo), urls, True, self.mappings,
                    preview_sample_images=card.get('preview_sample_images'), base_url=card.get('url', ''),
                    cancel_event=self.cancel)
                uris, failed = result.uris, result.failed
            except enricher.SampleBackfillCancelled:
                # The downloader may already have committed an image when the
                # cancellation arrived. Make those images visible to the DB.
                uris = disk_images()
                if not uris:
                    raise
        if not uris:
            raise _FieldError('samples.error_sample_download_failed')
        if not self.repo.update_sample_images(row.path, uris):
            raise _FieldError('samples.error_db_write_failed')
        if failed:
            raise _PartialSamples(failed)
        return True

    def apply(self, element, path, card):
        with _WRITE_LOCK:
            if self.cancel.is_set():
                raise enricher.SampleBackfillCancelled()
            row = self.repo.get_by_path(path)
            if row is None:
                raise _FieldError('samples.error_file_not_found')
            if element == 'cover' and row.cover_path:
                if Path(uri_to_local_fs_path(row.cover_path, self.mappings)).is_file():
                    return False
            if element == 'samples':
                base = Path(uri_to_local_fs_path(row.path, self.mappings)).parent
                for uri in _strings(row.sample_images):
                    if uri.startswith(('https://', 'http://')):
                        continue
                    sample = Path(uri_to_local_fs_path(uri, self.mappings))
                    if (base / sample).is_file():
                        return False
            nfo, readonly = self.paths(row, element, card)
            if element == 'cover':
                return self.fill_cover(row, nfo, readonly, card)
            if element == 'samples':
                return self.fill_samples(row, nfo, readonly, card)
            return self.fill_text(element, row, nfo, card)

    def fill_member(self, element, source, path):
        try:
            return self.apply(element, path, None)
        except _NeedCard:
            pass
        if self.cancel.is_set():
            raise enricher.SampleBackfillCancelled()
        if source not in self.cards:
            try:
                self.cards[source] = _lookup(self.number, source)
            except _FieldError as exc:
                self.cards[source] = exc
        card = self.cards[source]
        if isinstance(card, _FieldError):
            raise card
        return self.apply(element, path, card)

    def save_translation_scope(self, batch, locale):
        row = self.group.members[0]
        if not self.plot_targets or not plot_needs_translation(self.source_plot, locale, proper_terms=row.actresses or []):
            return
        targets = tuple(self.plot_targets.items())
        candidate = PlotBackfillCandidate(row.path, self.number, row.title,
            tuple(member.path for member in self.group.members), targets, tuple(row.actresses or []))
        batch.add(candidate, targets, self.source_plot)


class _PartialSamples(Exception):
    pass


def backfill_events(db_path, config, sources, cancel, *, file_path=None):
    locale = get_config_locale(config)
    summary = {'success': 0, 'failed': 0, 'skipped': 0, 'total': 0, 'failed_items': [],
               'fields_filled': dict.fromkeys(ELEMENTS, 0), 'translation_batch': '', 'translation_count': 0}
    batch = PlotTranslationBatch(db_path)
    groups = []
    if not db_path.exists() and not cancel.is_set():
        yield {'type': 'error', 'message': t('runtime.plots.db_missing', locale)}
        return
    if not cancel.is_set():
        repo = VideoRepository(db_path)
        directories, mappings = get_configured_gallery_dirs(config)
        movie_type = _Movie
        if file_path is None:
            groups = logical_video_groups(rows_in_library_dirs(repo.get_all(), directories), mappings)
        else:
            from core.element_rescrape import DetailMovie
            row = repo.get_by_path(file_path)
            if not row or not rows_in_library_dirs([row], directories):
                yield {'type': 'error', 'message': t('runtime.samples.error_file_not_found', locale)}
                return
            groups = [VideoGroup([row], [])]
            movie_type = DetailMovie
        scanner = VideoScanner(mappings)
    folders = Counter(group.members[0].path.rsplit('/', 1)[0] for group in groups)
    total = len(groups)
    for index, group in enumerate(groups, 1):
        if cancel.is_set():
            break
        path = group.members[0].path
        movie = movie_type(repo, config, group, folders[path.rsplit('/', 1)[0]] > 1, cancel, scanner)
        identity = {'number': movie.number, 'file_path': path}
        label = movie.number or path.rsplit('/', 1)[-1]
        yield {'type': 'progress', 'current': index - 1, 'total': total, **identity, 'message': label}
        for element, source in sources.items():
            changed = False
            failures = []
            for row in group.members:
                if cancel.is_set():
                    break
                try:
                    changed |= movie.fill_member(element, source, row.path)
                except enricher.SampleBackfillCancelled:
                    break
                except _PartialSamples as exc:
                    changed = True
                    failures.append(f'{row.path}: {exc} × ' + t('runtime.samples.error_sample_write_failed', locale))
                except (OSError, _FieldError) as exc:
                    key = str(exc) if isinstance(exc, _FieldError) else 'scanner.generate_failed'
                    if isinstance(exc, AndroidStoragePermissionError):
                        key = 'samples.error_storage_permission_required'
                    failures.append(t('runtime.' + key, locale, number=movie.number))
                except Exception:
                    logger.exception('Failed to fill %s for %s', element, row.path)
                    failures.append(t('runtime.scanner.generate_failed', locale))
            if element == 'plot':
                previous_batch_size = len(batch.items)
                try:
                    movie.save_translation_scope(batch, locale)
                except OSError:
                    del batch.items[previous_batch_size:]
                    failures.append(t('runtime.plots.error_db_write_failed', locale))
            if cancel.is_set() and not (changed or failures):
                break
            item = {**identity, 'element': element, 'source': source}
            error = ' / '.join(dict.fromkeys(failures))
            if changed:
                summary['success'] += int(not error)
                summary['fields_filled'][element] += 1
            if error:
                summary['failed'] += 1
                summary['failed_items'].append({**item, 'error': error})
            skipped = not (changed or error)
            summary['skipped'] += int(skipped)
            yield {'type': 'result-item', **item, 'current': index, 'total': total,
                   'success': changed and not error, 'partial': bool(changed and error),
                   'skipped': skipped, 'error': error, 'message': error or label}
    summary.update(total=summary['success'] + summary['skipped'] + summary['failed'],
                   translation_batch=batch.id if batch.items else '', translation_count=len(batch.items))
    yield {'type': 'done', 'cancelled': cancel.is_set(), 'summary': summary,
           'message': t('runtime.scanner.done', locale)}
