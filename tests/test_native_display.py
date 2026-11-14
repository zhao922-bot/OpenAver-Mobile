import copy

import pytest
from pydantic import ValidationError

from core import config as config_core
from web.routers import config as config_router


def _model():
    model = getattr(config_core, 'ShowcaseDisplayConfig', None)
    assert model is not None, 'live browsing preferences need their own validated schema'
    return model


@pytest.mark.parametrize('columns', [2, 3, 5])
def test_native_display_exact_columns_and_independent_page_size(columns):
    result = _model()(presentation='poster', columns=columns, items_per_page=120)
    assert result.model_dump() == dict(presentation='poster', columns=columns, items_per_page=120)


@pytest.mark.parametrize('field,value', [('columns', 4), ('columns', True), ('columns', 2.0),
                                       ('items_per_page', 0), ('items_per_page', 501),
                                       ('items_per_page', True), ('presentation', 'unknown')])
def test_native_display_rejects_invalid_preferences(field, value):
    with pytest.raises(ValidationError):
        _model()(**{field: value})


def test_native_display_save_changes_only_its_own_section(monkeypatch):
    original = {'showcase': {'player': 'custom'}, 'gallery': {'items_per_page': 90},
                'ai_services': {'tags': {'api_key': 'preserve'}}, 'general': {'theme': 'dim'}}
    disk = copy.deepcopy(original)
    monkeypatch.setattr(config_router, 'mutate_config', lambda fn: fn(disk))
    handler = getattr(config_router, 'update_showcase_display', None)
    assert handler is not None, 'display updates must not submit the entire configuration'
    result = handler(_model()(columns=5, items_per_page=120))
    assert result['success'] is True
    assert disk['showcase'].pop('display') == result['data']
    assert disk == original


@pytest.mark.parametrize('existing', [None, {'presentation': 'list', 'columns': 5, 'items_per_page': 120}])
def test_unrelated_full_settings_save_cannot_overwrite_live_display(monkeypatch, existing):
    disk = {'showcase': {'player': 'custom'}}
    if existing is not None:
        disk['showcase']['display'] = copy.deepcopy(existing)
    monkeypatch.setattr(config_router, 'load_config', lambda: copy.deepcopy(disk))
    monkeypatch.setattr(config_router, 'mutate_config', lambda fn: fn(disk))
    monkeypatch.setattr(config_router, '_after_faces_saved', lambda *args: None)
    monkeypatch.setattr(config_router, '_reset_translate_service', lambda: None)
    monkeypatch.setattr(config_router, 'cf_window_proxy_restart_needed', lambda: False)
    monkeypatch.setattr(config_router, 'current_settings', lambda: None)
    monkeypatch.setattr(config_router.cf_handoff, 'restart_needed_here', lambda _: False)
    result = config_router.update_config(config_core.AppConfig(sources=[]))
    assert result['success'] is True
    assert disk['showcase'].get('display') == existing
