import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.static_cache import NoCacheStaticFiles


def test_packaged_ui_code_changes_with_same_size_and_timestamp_are_served_fresh(tmp_path):
    script = tmp_path / 'app.js'
    script.write_text('const value = 1;', encoding='utf-8')
    app = FastAPI()
    app.mount('/static', NoCacheStaticFiles(directory=tmp_path))
    client = TestClient(app)
    first = client.get('/static/app.js')
    timestamp = script.stat().st_mtime_ns
    script.write_text('const value = 2;', encoding='utf-8')
    os.utime(script, ns=(timestamp, timestamp))
    second = client.get('/static/app.js', headers={
        'If-None-Match': first.headers['etag'],
        'If-Modified-Since': first.headers['last-modified'],
    })
    assert second.status_code == 200
    assert second.text == 'const value = 2;'
    assert second.headers['cache-control'] == 'no-store'


def test_non_code_static_files_keep_conditional_cache_validation(tmp_path):
    (tmp_path / 'icon.svg').write_text('<svg/>', encoding='utf-8')
    app = FastAPI()
    app.mount('/static', NoCacheStaticFiles(directory=tmp_path))
    client = TestClient(app)
    first = client.get('/static/icon.svg')
    second = client.get('/static/icon.svg', headers={'If-None-Match': first.headers['etag']})
    assert second.status_code == 304
    assert second.headers['cache-control'] == 'no-cache'
