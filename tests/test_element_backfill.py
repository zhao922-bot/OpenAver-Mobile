"""Offline coverage of source selection, narrow writes and scanner job semantics."""
import json
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import element_backfill as fill, element_sources as catalog
from core.database import Video, VideoRepository, init_db
from core.path_utils import to_file_uri, uri_to_local_fs_path
from core.plot_backfill import PlotTranslationBatch
from web.routers import scanner


PLOT = 'これは最初の段落です。これは二番目の段落で、作品の内容を詳しく説明します。'
JPEG = b'\xff\xd8\xff\xe0' + bytes(100)


@pytest.fixture
def library(tmp_path, monkeypatch):
    media = tmp_path / 'media'
    media.mkdir()
    db = tmp_path / 'library.db'
    init_db(db)
    config = {'general': {'locale': 'zh-CN'}, 'gallery': {'directories': [str(media)]},
              'sources': [{'id': s, 'enabled': True} for s in ('dmm', 'jav321', 'javbus', 'fc2')]}
    repo = VideoRepository(db)
    calls, downloads = [], []

    def add(name='ABC-123', directory=media, number='ABC-123', **kwargs):
        directory.mkdir(parents=True, exist_ok=True)
        file = directory / (name + '.mp4')
        file.write_bytes(b'video')
        row = Video(path=to_file_uri(str(file)), number=number, title='Stored title',
                    user_tags=['Personal'], actresses=['Stored actor'], **kwargs)
        repo.upsert(row)
        return file, row.path

    def search(number, source, **kwargs):
        calls.append((number, source))
        return {'number': number, 'source': source, '_source': source, '_summary': PLOT if source == 'jav321' else 'Other plot',
                'tags': [source + '-tag'], 'cover': 'https://fixture/' + source + '-cover',
                'sample_images': ['https://fixture/' + source + '-sample'], 'title': 'Unwanted title'}

    def download(url, dest, **kwargs):
        downloads.append(url)
        Path(dest).write_bytes(JPEG)
        return True

    def run(sources, cancel=None):
        return list(fill.backfill_events(db, config, sources, cancel or threading.Event()))

    monkeypatch.setattr(fill, 'search_jav_single_source', search)
    monkeypatch.setattr(fill.enricher, 'download_image', download)
    return SimpleNamespace(media=media, db=db, repo=repo, config=config, calls=calls,
                           downloads=downloads, search=search, add=add, run=run)


def test_four_choices_write_only_their_own_values_and_rerun_is_idle(library):
    file, uri = library.add()
    selected = dict(cover='javbus', plot='jav321', samples='fc2', tags='dmm')
    events = library.run(selected)
    summary = events[-1]['summary']
    assert summary['failed_items'] == []
    assert summary['total'] == summary['success'] == 4
    assert len(library.calls) == 4
    assert library.downloads == ['https://fixture/javbus-cover', 'https://fixture/fc2-sample']
    row = library.repo.get_by_path(uri)
    assert (row.title, row.actresses, row.user_tags, row.tags) == ('Stored title', ['Stored actor'], ['Personal'], ['dmm-tag'])
    assert Path(uri_to_local_fs_path(row.cover_path, {})).read_bytes() == JPEG
    assert Path(uri_to_local_fs_path(row.sample_images[0], {})).read_bytes() == JPEG
    nfo = file.with_suffix('.nfo')
    root = ET.parse(nfo).getroot()
    assert root.findtext('plot') == root.findtext('originalplot') == PLOT
    assert 'Stored title' in root.findtext('title')
    assert 'Personal' in [node.text for node in root.iter()]
    assert root.findtext('genre') == 'dmm-tag'
    assert row.nfo_mtime == pytest.approx(nfo.stat().st_mtime)
    batch = PlotTranslationBatch(library.db, summary['translation_batch'])
    assert batch.pending()[1] == {uri: PLOT}
    assert summary['translation_count'] == 1
    before = nfo.read_bytes()
    assert library.run(selected)[-1]['summary']['skipped'] == 4
    assert len(library.calls) == 4 and nfo.read_bytes() == before


def test_does_not_overwrite_present_unselected_or_user_fields(library):
    file, uri = library.add(tags=['Cached'])
    nfo = file.with_suffix('.nfo')
    nfo.write_text('<movie><title>My title</title><originalplot>Keep</originalplot><custom>Mine</custom><genre>Local</genre></movie>')
    result = library.run({'plot': 'jav321', 'tags': 'dmm'})[-1]['summary']
    assert (result['success'], result['skipped'], result['translation_count']) == (1, 1, 0)
    assert library.calls == [('ABC-123', 'jav321')]
    root = ET.parse(nfo).getroot()
    assert [root.findtext(e) for e in ('plot', 'originalplot', 'title', 'custom', 'genre')] == [PLOT, 'Keep', 'My title', 'Mine', 'Local']
    assert library.repo.get_by_path(uri).tags == ['Cached']
    assert list(file.parent.glob('*.jpg')) == [] and library.downloads == []


@pytest.mark.parametrize('mismatch', [False, True])
def test_missing_data_and_mismatched_provenance_never_fall_back(library, monkeypatch, mismatch):
    file, uri = library.add()
    def search(number, source, **kwargs):
        library.calls.append(source)
        if source == 'jav321':
            return {'source': 'dmm' if mismatch else source, '_summary': PLOT if mismatch else ''}
        return {'source': source, '_summary': 'Wrong source plot', 'tags': ['Correct']}
    monkeypatch.setattr(fill, 'search_jav_single_source', search)
    summary = library.run(dict(plot='jav321', tags='dmm'))[-1]['summary']
    assert library.calls == ['jav321', 'dmm']
    assert (summary['success'], summary['failed'], summary['total']) == (1, 1, 2)
    failure, = summary['failed_items']
    assert failure['source'] == 'jav321' and failure['element'] == 'plot' and failure['error']
    assert not ET.parse(file.with_suffix('.nfo')).getroot().findtext('plot')
    assert library.repo.get_by_path(uri).tags == ['Correct']


def test_multipart_shares_one_card_and_physical_sample_set(library):
    parts = [library.add(name='ABC-123-cd' + str(i)) for i in (1, 2)]
    events = library.run(dict(plot='jav321', samples='jav321', tags='jav321'))
    assert events[-1]['summary']['failed_items'] == []
    assert events[-1]['summary']['success'] == 3
    assert library.calls == [('ABC-123', 'jav321')]
    assert library.downloads == ['https://fixture/jav321-sample']
    for path, uri in parts:
        assert ET.parse(path.with_suffix('.nfo')).getroot().findtext('plot') == PLOT
        assert len(library.repo.get_by_path(uri).sample_images) == 1


def test_unindexed_neighbor_blocks_shared_samples(library):
    file, uri = library.add()
    file.with_name('Other.mkv').write_bytes(b'other')
    folder = file.parent / 'extrafanart'
    folder.mkdir()
    (folder / 'fanart1.jpg').write_bytes(JPEG)
    summary = library.run({'samples': 'fc2'})[-1]['summary']
    assert (summary['failed'], summary['total']) == (1, 1)
    assert library.calls == [] and library.repo.get_by_path(uri).sample_images == []


@pytest.mark.parametrize('existing_output', [False, True])
def test_readonly_scope_writes_only_managed_output(library, tmp_path, existing_output):
    output = tmp_path / 'output'
    output.mkdir()
    target = output / 'Already allocated'
    data = {}
    if existing_output:
        target.mkdir()
        data['output_dir'] = to_file_uri(str(target))
    library.config['scraper'] = {'external_manager': 'jellyfin'}
    library.config['gallery']['directories'] = [{'path': str(library.media), 'readonly': True, 'output_path': str(output)}]
    file, uri = library.add(**data)
    file.with_suffix('.nfo').write_text('<movie><plot>Original source</plot></movie>')
    summary = library.run(dict(plot='jav321', samples='jav321', cover='javbus'))[-1]['summary']
    assert summary['failed_items'] == []
    assert summary['success'] == 3 and len(list(library.media.iterdir())) == 2
    assert file.with_suffix('.nfo').read_text() == '<movie><plot>Original source</plot></movie>'
    row = library.repo.get_by_path(uri)
    managed = Path(uri_to_local_fs_path(row.output_dir, {}))
    assert managed.is_relative_to(output) and len(list(managed.glob('*.nfo'))) == 1
    assert ET.parse(next(managed.glob('*.nfo'))).getroot().findtext('plot') == PLOT
    assert Path(uri_to_local_fs_path(row.cover_path, {})).parent == managed
    assert Path(uri_to_local_fs_path(row.sample_images[0], {})).parent.parent == managed


def test_stale_and_unconfigured_library_rows_are_excluded(library, tmp_path):
    removed = tmp_path / 'removed'
    file, _ = library.add(directory=removed, output_dir=to_file_uri(str(tmp_path / 'old-output')))
    assert library.run({'plot': 'jav321'})[-1]['summary']['total'] == 0
    assert not file.with_suffix('.nfo').exists() and library.calls == []
    library.config['gallery']['directories'] = []
    library.add()
    assert library.run({'plot': 'jav321'})[-1]['summary']['total'] == 0


def test_cancellation_after_lookup_leaves_original_files(library, monkeypatch):
    file, _ = library.add()
    cancel = threading.Event()
    def search(*args, **kwargs):
        cancel.set()
        return library.search(*args, **kwargs)
    monkeypatch.setattr(fill, 'search_jav_single_source', search)
    events = library.run(dict(plot='jav321', tags='jav321'), cancel)
    assert events[-1]['cancelled'] and events[-1]['summary']['total'] == 0
    assert [e['type'] for e in events].count('done') == 1
    assert not file.with_suffix('.nfo').exists()


def test_concurrent_requests_recheck_before_writing(library, monkeypatch):
    file, _ = library.add()
    barrier = threading.Barrier(2)
    def search(*args, **kwargs):
        card = library.search(*args, **kwargs)
        barrier.wait(timeout=10)
        return card
    monkeypatch.setattr(fill, 'search_jav_single_source', search)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(library.run, {'plot': source}) for source in ('jav321', 'dmm')]
        summaries = [job.result(timeout=15)[-1]['summary'] for job in jobs]
    assert sum(s['success'] for s in summaries) == sum(s['skipped'] for s in summaries) == 1
    assert sum(s['failed'] for s in summaries) == 0
    winner = next(i for i, s in enumerate(summaries) if s['success'])
    assert ET.parse(file.with_suffix('.nfo')).getroot().findtext('plot') == [PLOT, 'Other plot'][winner]


def test_partial_samples_count_once_and_keep_downloaded_file(library, monkeypatch):
    _, uri = library.add()
    def search(*args, **kwargs):
        card = library.search(*args, **kwargs)
        card['sample_images'].append('invalid')
        return card
    monkeypatch.setattr(fill, 'search_jav_single_source', search)
    events = library.run({'samples': 'fc2'})
    item = next(e for e in events if e['type'] == 'result-item')
    assert item['partial'] and not item['success'] and item['error']
    summary = events[-1]['summary']
    assert (summary['total'], summary['success'], summary['failed'], summary['fields_filled']['samples']) == (1, 0, 1, 1)
    assert len(library.repo.get_by_path(uri).sample_images) == 1


def test_catalog_filters_capabilities_disabled_and_unavailable_sources(library, monkeypatch):
    library.config['sources'].extend([{'id': 'avsox', 'enabled': True}, {'id': 'heyzo', 'enabled': False},
                                      {'id': 'metatube:local', 'enabled': True}, {'id': 'metatube:offline', 'enabled': True}])
    monkeypatch.setattr(catalog.metatube_state, 'availability_map', lambda: {'metatube:local': True})
    spec = SimpleNamespace(name='Tags only', fetch='http', fields=[SimpleNamespace(name='tags')])
    view = SimpleNamespace(routable=True, loaded=SimpleNamespace(spec=spec), config=SimpleNamespace(id='custom:test'))
    monkeypatch.setattr(catalog, 'custom_source_views', lambda: [view])
    options = catalog.element_sources(library.config, {'available': True, 'sites': ['javlibrary']})
    ids = {e: [option['id'] for option in choices] for e, choices in options.items()}
    assert {'dmm', 'jav321', 'metatube:local'} == set(ids['plot'])
    assert {'avsox', 'javlibrary', 'custom:test'} <= set(ids['tags'])
    assert 'custom:test' not in ids['cover'] and 'avsox' not in ids['samples']
    assert not any(s in ids['tags'] for s in ('auto', 'jable', 'heyzo', 'metatube:offline'))
    assert all(set(item) == {'id', 'label'} and item['label'] for group in options.values() for item in group)


@pytest.mark.parametrize('selection', [{}, {'tags': 'dmm', 'plot': 'javbus'}, {'cover': 'auto'}, {'title': 'jav321'}])
def test_router_rejects_entire_invalid_selection_before_any_write(library, monkeypatch, selection):
    file, _ = library.add()
    monkeypatch.setattr(scanner, 'load_config', lambda: library.config)
    monkeypatch.setattr(scanner, 'get_db_path', lambda: library.db)
    events = [json.loads(line.removeprefix('data: ')) for line in scanner._element_backfill_generator(threading.Event(), selection, {})]
    assert [e['type'] for e in events] == ['error']
    assert library.calls == [] and not file.with_suffix('.nfo').exists()


def test_unrelated_generic_cover_is_preserved_and_null_db_path_is_repaired(library):
    import sqlite3
    file, uri = library.add()
    file.with_name('Other.mkv').write_bytes(b'other')
    generic = file.with_name('cover.jpg')
    generic.write_bytes(b'other cover')
    with sqlite3.connect(library.db) as conn:
        conn.execute('UPDATE videos SET cover_path = NULL WHERE path = ?', (uri,))
    summary = library.run({'cover': 'javbus'})[-1]['summary']
    assert summary['failed_items'] == [] and summary['success'] == 1
    assert generic.read_bytes() == b'other cover' and file.with_suffix('.jpg').read_bytes() == JPEG
    assert library.repo.get_by_path(uri).cover_path == to_file_uri(str(file.with_suffix('.jpg')))


def test_malformed_nfo_leaves_text_and_still_allows_samples(library):
    file, _ = library.add()
    nfo = file.with_suffix('.nfo')
    nfo.write_bytes(b'<movie><unfinished')
    summary = library.run(dict(plot='jav321', tags='dmm', samples='fc2'))[-1]['summary']
    assert (summary['success'], summary['failed'], summary['total']) == (1, 2, 3)
    assert library.calls == [('ABC-123', 'fc2')] and nfo.read_bytes() == b'<movie><unfinished'


def test_readonly_without_output_root_is_reported_without_source_writes(library):
    file, _ = library.add()
    library.config['gallery']['directories'] = [{'path': str(library.media), 'readonly': True}]
    library.config['scraper'] = {'external_manager': 'jellyfin'}
    events = library.run(dict(plot='jav321', cover='javbus'))
    assert events[-1]['summary']['failed'] == 2 and library.calls == []
    assert list(library.media.iterdir()) == [file]


def test_missing_db_emits_one_error(tmp_path):
    events = list(fill.backfill_events(tmp_path / 'missing.db', {}, {'tags': 'dmm'}, threading.Event()))
    assert [e['type'] for e in events] == ['error'] and events[0]['message']


def detail(library, uri, sources, cancel=None):
    return list(fill.backfill_events(library.db, library.config, sources, cancel or threading.Event(), file_path=uri))


def test_detail_rescrapes_populated_fields_of_exact_video(library, monkeypatch):
    from core import thumbnail_cache
    evicted = []
    monkeypatch.setattr(thumbnail_cache, 'invalidate', evicted.append)
    file, uri = library.add(tags=['Old tag'], auto_focal='0.5,0.5', crop_mode='manual')
    other_file, other = library.add(name='Other', directory=library.media / 'other', tags=['Other'])
    other_nfo = other_file.with_suffix('.nfo')
    other_nfo.write_text('<movie><tag>Other</tag></movie>')
    nfo = file.with_suffix('.nfo')
    nfo.write_text('<movie><title>Hand title</title><plot>Old</plot><originalplot>Old original</originalplot>'
                   '<genre>Old tag</genre><user_tag>My tag</user_tag><custom>Kept</custom></movie>')
    cover = file.with_suffix('.jpg')
    cover.write_bytes(b'old cover')
    library.repo.update_cover_path_preserve_focal(uri, to_file_uri(str(cover)), library.repo.get_by_path(uri).cover_path)
    samples = file.parent / 'extrafanart'
    samples.mkdir()
    stale = samples / 'extra.png'
    stale.write_bytes(b'old sample')
    (samples / 'notes.txt').write_text('kept')
    library.repo.update_sample_images(uri, [to_file_uri(str(stale))])
    monkeypatch.setattr(VideoRepository, 'get_all', lambda *a: pytest.fail('detail enumerated library'))
    events = detail(library, uri, dict(plot='jav321', tags='dmm', cover='javbus', samples='fc2'))
    summary = events[-1]['summary']
    assert summary['failed_items'] == [] and summary['total'] == summary['success'] == 4
    assert summary['translation_count'] == 1
    assert [e['file_path'] for e in events if e['type'] == 'result-item'] == [uri]*4
    row = library.repo.get_by_path(uri)
    assert row.tags == ['dmm-tag'] and row.user_tags == ['Personal'] and row.title == 'Stored title'
    root = ET.parse(nfo).getroot()
    assert [root.findtext(k) for k in ('title','plot','originalplot','genre','user_tag','custom')] == [
        'Hand title', PLOT, PLOT, 'dmm-tag', 'My tag', 'Kept']
    assert row.crop_mode == 'auto' and row.auto_focal == '' and cover.read_bytes() == JPEG
    assert evicted == [uri] and not stale.exists() and (samples/'notes.txt').read_text() == 'kept'
    assert [Path(uri_to_local_fs_path(s, {})).read_bytes() for s in row.sample_images] == [JPEG]
    assert (library.repo.get_by_path(other).tags, other_nfo.read_text()) == (['Other'], '<movie><tag>Other</tag></movie>')


@pytest.mark.parametrize('failure', ['missing', 'wrong_source', 'partial_download', 'cancel', 'db', 'disk'])
def test_detail_failed_replacement_preserves_previous_assets(library, monkeypatch, failure):
    from core import element_rescrape as replacement
    file, uri = library.add()
    folder = file.parent / 'extrafanart'
    folder.mkdir()
    first, extra = folder / 'fanart1.jpg', folder / 'extra.jpg'
    first.write_bytes(b'first'); extra.write_bytes(b'extra')
    old = [to_file_uri(str(p)) for p in (first, extra)]
    library.repo.update_sample_images(uri, old)
    cancel = threading.Event()
    def search(*args, **kwargs):
        card = library.search(*args, **kwargs)
        if failure == 'missing':
            card['sample_images'] = []
        if failure == 'wrong_source':
            card['_source'] = 'javbus'
        if failure == 'partial_download':
            card['sample_images'].append('invalid')
        return card
    def fail(*args):
        raise OSError('fixture failure')
    monkeypatch.setattr(fill, 'search_jav_single_source', search)
    if failure == 'db':
        monkeypatch.setattr(VideoRepository, 'replace_detail_element', fail)
    if failure == 'disk':
        monkeypatch.setattr(replacement, 'delete_file', fail)
    if failure == 'cancel':
        write = replacement.write_bytes
        def interrupted(target, data):
            write(target, data)
            cancel.set()
        monkeypatch.setattr(replacement, 'write_bytes', interrupted)
    events = detail(library, uri, {'samples': 'fc2'}, cancel)
    assert (first.read_bytes(), extra.read_bytes()) == (b'first', b'extra')
    assert sorted(folder.iterdir()) == sorted([first, extra])
    assert library.repo.get_by_path(uri).sample_images == old
    assert len(library.calls) == 1
    if failure == 'cancel':
        assert events[-1]['cancelled'] and events[-1]['summary']['total'] == 0
    else:
        assert events[-1]['summary']['failed_items'][0]['element'] == 'samples'


def test_detail_multipart_targets_one_sidecar_refuses_shared_samples(library):
    first, uri1 = library.add(name='ABC-123-cd1', tags=['one'])
    second, uri2 = library.add(name='ABC-123-cd2', tags=['two'])
    nfo1 = first.with_suffix('.nfo')
    nfo1.write_text('<movie><plot>first</plot><genre>one</genre></movie>')
    summary = detail(library, uri2, dict(tags='dmm', samples='dmm'))[-1]['summary']
    assert summary['success'] == summary['failed'] == 1 and summary['failed_items'][0]['element'] == 'samples'
    assert library.calls == [('ABC-123','dmm')]
    row1, row2 = library.repo.get_by_path(uri1), library.repo.get_by_path(uri2)
    assert row1.tags == ['one'] and row2.tags == ['dmm-tag']
    assert row1.sample_images == row2.sample_images == [] and not (first.parent / "extrafanart").exists()
    assert nfo1.read_text() == '<movie><plot>first</plot><genre>one</genre></movie>'
    assert ET.parse(second.with_suffix('.nfo')).getroot().findtext('genre') == 'dmm-tag'


def test_detail_mixed_folder_only_allows_owned_assets(library):
    file, uri = library.add()
    other, other_uri = library.add(name='Other', number='XYZ-111')
    summary = detail(library, uri, dict(samples='fc2', tags='dmm'))[-1]['summary']
    assert summary['success'] == summary['failed'] == 1 and summary['failed_items'][0]['element'] == 'samples'
    assert not (file.parent/'extrafanart').exists() and not other.with_suffix('.nfo').exists()
    assert library.repo.get_by_path(other_uri).tags == []
    file.with_suffix('.mkv').write_bytes(b'same stem')
    nfo = file.with_suffix('.nfo')
    before = nfo.read_bytes()
    assert detail(library, uri, dict(plot='jav321', cover='javbus'))[-1]['summary']['failed'] == 2
    assert nfo.read_bytes() == before and not file.with_suffix('.jpg').exists()


def test_detail_readonly_failed_first_write_keeps_binding_and_source(library, tmp_path, monkeypatch):
    file, uri = library.add()
    managed = tmp_path / 'managed'
    managed.mkdir()
    library.config['gallery']['directories'] = [{'path': str(library.media), 'readonly':True, 'output_path':str(managed)}]
    library.config['scraper'] = {'external_manager':'jellyfin'}
    original = file.with_suffix('.nfo')
    original.write_bytes(b'<movie><genre>Source</genre></movie>')
    with monkeypatch.context() as patch:
        patch.setattr(fill.enricher, 'download_image', lambda *a, **kw: False)
        assert detail(library, uri, {'cover':'javbus'})[-1]['summary']['failed'] == 1
    assert not library.repo.get_by_path(uri).output_dir and list(managed.iterdir()) == []
    with monkeypatch.context() as patch:
        def fail_commit(*args):
            raise OSError('fixture failed to update DB')
        patch.setattr(VideoRepository, 'replace_detail_element', fail_commit)
        assert detail(library, uri, {'samples':'fc2'})[-1]['summary']['failed'] == 1
    assert not library.repo.get_by_path(uri).output_dir and list(managed.iterdir()) == []
    summary = detail(library, uri, dict(tags='dmm', plot='jav321'))[-1]['summary']
    assert summary['failed_items'] == [] and summary['success'] == 2
    directory = Path(uri_to_local_fs_path(library.repo.get_by_path(uri).output_dir, {}))
    assert directory.is_relative_to(managed) and ET.parse(next(directory.glob('*.nfo'))).getroot().findtext('plot') == PLOT
    assert original.read_bytes() == b'<movie><genre>Source</genre></movie>'


def test_detail_rejects_unresolved_scope_without_fetching(library, tmp_path, monkeypatch):
    file, uri = library.add(directory=tmp_path/'removed')
    monkeypatch.setattr(VideoRepository, 'get_all', lambda *a: pytest.fail('detail enumerated library'))
    for target in (uri, uri + 'wrong', ''):
        assert [e['type'] for e in detail(library, target, {'tags':'dmm'})] == ['error']
    assert not file.with_suffix('.nfo').exists() and not library.calls


def test_detail_legacy_managed_shared_sidecar_and_samples_preserve_both_rows(library, tmp_path):
    output = tmp_path / 'output'
    managed = output / 'Shared'
    managed.mkdir(parents=True)
    library.config['gallery']['directories'] = [{'path':str(library.media), 'readonly':True, 'output_path':str(output)}]
    library.config['scraper'] = {'external_manager':'jellyfin'}
    store = to_file_uri(str(managed))
    _, first = library.add(name='ABC-123-cd1', output_dir=store, tags=['one'])
    _, second = library.add(name='ABC-123-cd2', output_dir=store, tags=['two'])
    nfo = managed / 'shared.nfo'
    old = b'<movie><plot>Shared</plot><genre>Old</genre></movie>'
    nfo.write_bytes(old)
    summary = detail(library, second, dict(plot='jav321',tags='dmm',samples='fc2',cover='javbus'))[-1]['summary']
    assert summary['failed'] == 4 and summary['success'] == 0
    assert nfo.read_bytes() == old and list(managed.iterdir()) == [nfo]
    assert library.repo.get_by_path(first).tags == ['one'] and library.repo.get_by_path(second).tags == ['two']


def test_detail_rejects_shared_cover_reference(library):
    file, uri = library.add()
    cover = file.with_suffix('.jpg')
    cover.write_bytes(b'legacy shared cover')
    library.add(name='Other', directory=library.media / 'Other', cover_path=to_file_uri(str(cover)))
    assert detail(library, uri, {'cover':'javbus'})[-1]['summary']['failed'] == 1
    assert cover.read_bytes() == b'legacy shared cover'
