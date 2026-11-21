from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.database import AliasRepository, VideoRepository, init_db
from core.database.video import Video
from core.path_utils import to_file_uri
from web.routers import showcase, similar


@pytest.fixture
def library(tmp_path, monkeypatch):
    gallery = tmp_path / 'library'
    db_path = tmp_path / 'showcase.db'
    init_db(db_path)
    repo = VideoRepository(db_path)
    config = {'gallery': {'directories': [{'path': str(gallery)}]}}
    monkeypatch.setattr(showcase, 'get_db_path', lambda: db_path)
    monkeypatch.setattr(showcase, 'load_config', lambda: config)

    def add(name, *, outside=False, user_rating=0, **fields):
        parent = tmp_path / 'library-backup' if outside else gallery
        path = to_file_uri(str(parent / name))
        repo.upsert(Video(path=path, **fields))
        if user_rating:
            assert repo.set_user_rating(path, user_rating)
        return path

    return db_path, add


def _browse(headers=None, **query):
    params = dict(page=1, per_page=1, sort='title', order='asc', paged=True)
    params.update(query)
    return showcase.get_videos(SimpleNamespace(headers=headers or {}), **params)


def _data(response):
    assert response.status_code == 200, response.body
    return json.loads(response.body)


def test_filters_count_and_sort_logical_titles_before_slicing(library):
    db_path, add = library
    AliasRepository(db_path).add('Current Name', ['Old Name'])
    add('outside.mp4', outside=True, title='000 Café', tags=['ÉTÉ'],
        actresses=['Old Name'], user_rating=1)
    part2 = add('edition/film-cd2.mp4', title='Hidden clue', tags=['other'],
                actresses=['Old Name'], size_bytes=70)
    part1 = add('edition/film-cd1.mp4', title='a Café', tags=['  ÉTÉ, bonus  '],
                actresses=['Old Name'], size_bytes=30, user_rating=2)
    second = add('second.mp4', title='Z CAFÉ', user_tags=['Été'], actresses=['Current Name'],
                 user_rating=1)
    add('other_actor.mp4', title='b Café', tags=['été'], actresses=['Another'], user_rating=1)
    add('whole_tag.mp4', title='b Café', tags=['été extra'], actresses=['Old Name'], user_rating=1)
    add('unpicked.mp4', title='b Café', tags=['été'], actresses=['Old Name'])

    filters = dict(q='  CAFÉ ', tag='éTé', favorites_only=True, actress='Current Name')
    response = _browse(**filters)
    first = _data(response)
    assert (first['total'], first['total_pages'], first['page'], first['paged']) == (2, 2, 1, True)
    assert first['videos'][0]['path'] == part1
    assert first['videos'][0]['part_paths'] == [part1, part2]
    assert first['videos'][0]['size'] == 100
    next_page = _data(_browse(page=99, **filters))
    assert (next_page['page'], next_page['total']) == (2, 2)
    assert [item['path'] for item in next_page['videos']] == [second]
    assert _data(_browse(q='Hidden clue'))['total'] == 0
    assert _browse({'if-none-match': response.headers['etag']}, **filters).status_code == 304
    assert _browse({'if-none-match': response.headers['etag']}, **{**filters, 'tag': 'bonus'}).status_code == 200


@pytest.mark.parametrize('field', ['number', 'title', 'maker', 'director', 'series', 'label',
                                   'actresses', 'tags', 'user_tags'])
def test_keyword_matches_each_mobile_field(library, field):
    _, add = library
    value = 'Aßéア%_z'
    if field in {'actresses', 'tags', 'user_tags'}:
        value = [value]
    wanted = add('match.mp4', **{field: value})
    add('nonmatch.mp4', title='Aßéアxxz')
    assert [item['path'] for item in _data(_browse(q='Éア%_'))['videos']] == [wanted]


def test_browse_matches_dart_simple_unicode_casing(library):
    _, add = library
    wanted = add('greek.mp4', title='İ ΟΣ', tags=['ΟΣ'])
    add('final-sigma.mp4', title='i ος', tags=['ος'])
    assert [item['path'] for item in _data(_browse(q='i οσ', tag='οσ'))['videos']] == [wanted]


def test_seeded_random_pages_are_repeatable_and_legacy_random_is_unpaged(library):
    _, add = library
    paths = [add(f'film-{n}.mp4', title='match') for n in range(10)]
    add('exclude.mp4', title='other')

    def pages(seed):
        ordered = []
        for page in (1, 2, 3, 4):
            response = _browse(page=page, per_page=3, sort='random', random_seed=seed, q='match')
            data = _data(response)
            assert (data['paged'], data['total'], data['total_pages']) == (True, 10, 4)
            assert 'etag' not in response.headers
            ordered.extend(item['path'] for item in data['videos'])
        return ordered

    ordered = pages(0)
    assert sorted(ordered) == sorted(paths)
    assert ordered == pages(0)
    assert ordered != pages(1)
    classic = _data(_browse(sort='random'))
    assert classic['paged'] is False
    assert [item['path'] for item in classic['videos']][:10] == paths


def test_lookup_uses_exact_identity_scope_fallback_and_multipart(library, monkeypatch):
    _, add = library
    outside = add('outside.mp4', outside=True, title='Outside', number='ÄBX-001')
    first = add('first.mp4', number='äbx-001', title='First')
    part2 = add('other/edition-pt2.mp4', number='ÄBX-001', title='Part two')
    part1 = add('other/edition-pt1.mp4', number='ÄBX-001', title='Exact Title')
    add('eszett.mp4', number='Nß-001')
    ascii_number = add('ascii-number.mp4', number='NSS-001')

    def forbid_full_list(*args, **kwargs):
        pytest.fail('direct lookup must not load the Showcase list')

    monkeypatch.setattr(VideoRepository, 'get_showcase_rows', forbid_full_list)
    video = _data(showcase.lookup_video(path=part2, number='ÄBX-001'))['video']
    assert video['path'] == part1
    assert video['part_paths'] == [part1, part2]
    assert video['part_tokens'] == ['pt1', 'pt2']
    assert _data(showcase.lookup_video(path=outside, number='Äbx-001'))['video']['path'] == first
    assert _data(showcase.lookup_video(number='nss-001'))['video']['path'] == ascii_number
    assert _data(showcase.lookup_video(number='missing', title='Exact Title'))['video']['path'] == part1
    assert showcase.lookup_video(path=outside, title='Outside').status_code == 404
    assert showcase.lookup_video(number='BX-001', title='Exact').status_code == 404
    assert showcase.lookup_video(title='exact title').status_code == 404


def test_similar_results_include_the_identity_path(library, monkeypatch):
    db_path, add = library
    source = add('source.mp4', number='SRC-001')
    target = add('target.mp4', number='TGT-002', title='Target')
    repo = VideoRepository(db_path)
    ranker = SimpleNamespace(
        rank=lambda *args, **kwargs: [repo.get_by_path(target)],
        _score=lambda *_: 0.5,
    )
    monkeypatch.setattr(similar, 'VideoRepository', lambda: repo)
    monkeypatch.setattr(similar, 'load_config', lambda: {})
    monkeypatch.setattr(similar, 'fusion_vectors', lambda _: None)
    monkeypatch.setattr(similar.SimilarRankerCache, 'get', lambda: ranker)
    result, = similar._compute_similar_covers(repo.get_by_path(source).id, 1)['results']
    assert (result['path'], result['number'], result['title']) == (target, 'TGT-002', 'Target')
