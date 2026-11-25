"""Replace selected fields of one video, staging each field before publication."""
import os
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory

from core import android_storage, enricher, thumbnail_cache
from core.cover_layout import resolve_cover_target
from core.element_backfill import _Movie, _FieldError, _card_value, _FIELD_VALUES, _WRITE_LOCK, logger
from core.media_io import delete_file, ensure_directory, write_bytes
from core.nfo_locator import locate_nfo_for_video
from core.nfo_read import nfo_merged_tags
from core.nfo_updater import parse_nfo, replace_nfo_tags
from core.path_utils import to_file_uri, uri_to_local_fs_path
from core.plot_writeback import rewrite_nfo_plot
from core.readonly_source import is_path_readonly, readonly_source_prefixes, writable_source_prefixes
from core.video_extensions import get_video_extensions


def _publish(files, temp, cancel, commit):
    """Publish one field's files and index. Undo published files on failure."""
    backups = {}
    changed = []
    new_dirs = set()
    for target in files:
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise _FieldError('scanner.generate_failed')
        if target.exists():
            backup = temp / f'backup-{len(backups)}'
            copy2(target, backup)
            backups[target] = backup
    try:
        for target, staged in files.items():
            enricher._raise_if_cancelled(cancel)
            if staged is not None:
                for directory in target.parents:
                    if directory.exists():
                        break
                    new_dirs.add(directory)
                ensure_directory(target.parent)
                changed.append(target)
                write_bytes(target, staged.read_bytes())
            else:
                changed.append(target)
                delete_file(target)
        enricher._raise_if_cancelled(cancel)
        commit()
    except Exception:
        for target in reversed(changed):
            try:
                if target not in backups:
                    delete_file(target)
                else:
                    backup = backups[target]
                    write_bytes(target, backup.read_bytes())
                    stat = backup.stat()
                    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            except OSError:
                logger.exception('Could not restore rescrape backup for %s', target)
        for directory in sorted(new_dirs, key=lambda path: len(path.parts), reverse=True):
            try:
                if directory.is_dir() and not any(directory.iterdir()):
                    try:
                        directory.rmdir()
                    except OSError as exc:
                        if not android_storage.is_access_error(exc):
                            raise
                        android_storage.delete(str(directory))
            except OSError:
                logger.warning('Could not remove empty rescrape directory %s', directory, exc_info=True)
        raise


class DetailMovie(_Movie):
    def _fs(self, uri):
        return Path(uri_to_local_fs_path(uri, self.mappings))

    def _uri(self, file):
        return to_file_uri(str(file), self.mappings)

    def _check_ownership(self, row, element, nfo, readonly):
        video = self._fs(row.path)
        if not video.is_file():
            raise _FieldError('samples.error_file_not_found')
        gallery = self.config.get('gallery', {})
        if is_path_readonly(self._uri(nfo.resolve()), readonly_source_prefixes(gallery, self.mappings),
                            writable_source_prefixes(gallery, self.mappings)):
            raise _FieldError('samples.error_output_root_missing')
        if readonly and row.output_dir:
            other_paths = [p for p in self.repo.paths_in_managed_output(row.output_dir) if p != row.path]
            if element == 'samples' and other_paths:
                raise _FieldError('scanner.shared_detail_asset')
            for other in self.repo.get_by_paths(other_paths).values():
                located, error = locate_nfo_for_video(other, self.config, self.mappings)
                if error or Path(located) == nfo:
                    raise _FieldError('scanner.shared_detail_asset')

        # NFOs/canonical covers are stem-scoped; extrafanart is folder-scoped.
        # Include unindexed physical neighbors and indexed same-stem versions.
        extensions = get_video_extensions(self.config)
        if not readonly:
            aliases = [self._uri(video.with_suffix(ext)) for ext in extensions]
            if any(p != row.path for p in self.repo.get_by_paths(aliases)):
                raise _FieldError('scanner.shared_detail_asset')
        cover = self._cover_target(nfo) if element == 'cover' else None
        if cover and self.repo.other_video_uses_cover(row.path, self._uri(cover), str(cover)):
            raise _FieldError('scanner.shared_detail_asset')
        if not nfo.parent.is_dir():
            return
        for neighbor in nfo.parent.iterdir():
            if neighbor == video or neighbor.suffix.lower() not in extensions or not neighbor.is_file():
                continue
            if element == 'samples' or neighbor.stem.casefold() == nfo.stem.casefold():
                raise _FieldError('scanner.shared_detail_asset')
            if cover:
                stem = neighbor.stem.casefold()
                if cover.stem.casefold() in {stem, stem + '-poster', stem + '-fanart', 'cover', 'folder', 'fanart', 'poster'}:
                    raise _FieldError('scanner.shared_detail_asset')

    def _text(self, row, element, value, nfo, temp):
        staged = temp / nfo.name
        if nfo.exists():
            copy2(nfo, staged)
        else:
            self.ensure_nfo(row, staged, asset_path=nfo)
        if element == 'plot':
            rewrite_nfo_plot(staged, new_plot=value, new_original=value, allow_empty_existing=True)
        else:
            if not replace_nfo_tags(str(staged), value):
                raise _FieldError('scanner.tag_source_nfo_failed')
            _, root = parse_nfo(str(staged))
            value = nfo_merged_tags(root)
        return {nfo: staged}, value

    def _cover(self, value, card, nfo, temp):
        staged = temp / 'cover.jpg'
        if not enricher._write_cover(str(temp / 'cover.nfo'), value, True, True,
                                     preview_cover_url=card.get('preview_cover_url', '')):
            raise _FieldError('api.cover_not_found')
        if not enricher._is_valid_sample_file(str(staged)):
            raise _FieldError('api.cover_not_found')
        target = self._cover_target(nfo)
        return {target: staged}, self._uri(target)

    def _cover_target(self, nfo):
        target = Path(resolve_cover_target(str(nfo.with_suffix('')), self.manager))
        # A same-stem PNG/WEBP is preferred over a new manager-style fanart JPEG.
        # The canonical .jpg has priority on the next physical library scan.
        existing = self.scanner.find_cover_image(str(nfo))
        if existing and Path(existing).stem == nfo.stem:
            target = nfo.with_suffix('.jpg')
        return target

    def _samples(self, value, card, nfo, temp):
        folder = nfo.parent / 'extrafanart'
        if folder.is_symlink():
            raise _FieldError('samples.error_sample_write_failed')
        result = enricher._write_extrafanart(str(temp / 'video'), value, True, {},
            preview_sample_images=card.get('preview_sample_images'), base_url=card.get('url', ''),
            cancel_event=self.cancel)
        if not result.uris or result.failed:
            raise _FieldError('samples.error_sample_download_failed')
        images = [Path(uri_to_local_fs_path(uri, {})) for uri in result.uris]
        files = {folder / image.name: image for image in images}
        uris = [self._uri(path) for path in files]
        if folder.exists():
            for old in self.scanner._iter_extrafanart_images(folder):
                files.setdefault(old, None)
        return files, uris

    def apply(self, element, path, card):
        value = _card_value(card, *_FIELD_VALUES[element])
        with _WRITE_LOCK, TemporaryDirectory() as tempdir:
            enricher._raise_if_cancelled(self.cancel)
            row = self.repo.get_by_path(path)
            if not row:
                raise _FieldError('samples.error_file_not_found')
            nfo, readonly = self.paths(row, element, card, defer_output=True)
            self._check_ownership(row, element, nfo, readonly)
            temp = Path(tempdir)
            if element in ('plot', 'tags'):
                files, value = self._text(row, element, value, nfo, temp)
            elif element == 'cover':
                files, value = self._cover(value, card, nfo, temp)
            else:
                files, value = self._samples(value, card, nfo, temp)
            new_output = self._uri(nfo.parent) if readonly and not row.output_dir else None
            def commit():
                mtime = nfo.stat().st_mtime if element in ('plot', 'tags') else None
                self.repo.replace_detail_element(row.path, element, value, mtime, new_output)
            _publish(files, temp, self.cancel, commit)
            if element == 'plot':
                self.source_plot = value
                self.plot_targets[str(nfo)] = [row.path]
            if element == 'cover':
                try:
                    thumbnail_cache.invalidate(row.path)
                except OSError:
                    logger.warning('Thumbnail cache invalidation failed for %s', row.path, exc_info=True)
            return True
