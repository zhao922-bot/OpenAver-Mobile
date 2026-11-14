from __future__ import annotations

from types import SimpleNamespace
import asyncio
import pytest

from core.ai_services import faces, samples, similar_index, similar_state, faces_detect, faces_recompute
from core.ai_services.cloud_protocols import embedding_connection_id
from core.database import EmbeddingRepository, connection
from core.database import Video, VideoRepository
from core.database.embeddings import pack_vector
from web.routers import ai_services, config as config_router


def test_all_background_config_paths_keep_provider():
    raw = {"provider": "qwen", "url": "https://qwen.test", "model": "image"}
    assert similar_index._endpoint_cfg(raw).provider == "qwen"
    config = {"ai_services": {"faces": {**raw, "provider": "openai"}}}
    assert faces_recompute._faces_cfg_object(config).provider == "openai"
    assert faces_detect._faces_cfg_object(config).provider == "openai"


def test_test_overrides_and_stored_target_include_provider():
    config = {"ai_services": {"image_similar": {"provider": "qwen", "url": "https://qwen.test", "model": "image"},
                              "faces": {"provider": "openai", "url": "https://face.test/v1", "model": "vision"}}}
    cfg = ai_services._resolve_similar_cfg(ai_services.SimilarTestRequest(), config)
    assert cfg.provider == "qwen"
    cfg.provider = "endpoint"
    assert not ai_services._is_stored_target(cfg, config)
    cfg = ai_services._resolve_faces_cfg(ai_services.FacesTestRequest(), config)
    assert cfg.provider == "openai"
    cfg.provider = "endpoint"
    assert not ai_services._is_stored_faces_target(cfg, config)


def test_cloud_face_test_accepts_valid_empty_faces_without_fake_detection(monkeypatch):
    monkeypatch.setattr(samples, "detect", lambda *a, **k: faces.FacesResult([], "vision"))
    cfg = SimpleNamespace(provider="openai", url="https://face.test", model="vision")
    result = samples.run_faces_test(cfg)
    assert result.ok
    assert not result.detection_verified
    result = samples.run_faces_test(cfg, image_data_uri="data:image/jpeg;base64,aA==")
    assert result.ok
    assert not result.detection_verified


def test_face_cloud_save_does_not_launch_automatic_recompute(monkeypatch):
    monkeypatch.setattr(faces_recompute, "on_settings_saved", lambda: (_ for _ in ()).throw(AssertionError("auto task")))
    assert config_router._after_faces_saved({}, {"enabled": True, "provider": "openai", "url": "https://face.test"}) is None


def test_persisted_embedding_connection_blocks_fusion_after_restart(tmp_path, monkeypatch):
    db = tmp_path / "library.db"
    connection.init_db(db)
    repo = EmbeddingRepository(db)
    cfg = {"ai_services": {"image_similar": {"enabled": True, "provider": "endpoint", "url": "https://one.test", "model": "same"}}}
    repo.begin_index("same", 256)
    repo.mark_complete()
    repo.set_connection_id(embedding_connection_id(SimpleNamespace(**cfg["ai_services"]["image_similar"])))
    state = repo.get_index_state()
    monkeypatch.setattr(similar_state, "observed_model", None)
    assert similar_state.fusion_gate_from_state(cfg, state, db_path=db)
    cfg["ai_services"]["image_similar"]["url"] = "https://two.test"
    assert not similar_state.fusion_gate_from_state(cfg, state, db_path=db)


def test_cloud_detection_test_returns_user_image_and_boxes(monkeypatch):
    cfg = {"ai_services": {"faces": {"provider": "openai", "url": "https://face.test", "model": "vision"}}}
    monkeypatch.setattr(ai_services, "load_config", lambda: cfg)
    seen = []
    def run(config, **kwargs):
        seen.append(kwargs)
        return samples.FacesTestResult(ok=True, model="vision", boxes=[faces.Box(.1,.2,.3,.4,.9)], detection_verified=True)
    monkeypatch.setattr(ai_services, "run_faces_test", run)
    monkeypatch.setattr(ai_services, "_observe_faces_test_result", lambda result: None)
    result = asyncio.run(ai_services.faces_test(ai_services.FacesTestRequest(image_data_uri="data:image/jpeg;base64,aA==")))
    assert seen[0]["image_data_uri"].startswith("data:image/")
    assert result["boxes"] == [[.1,.2,.3,.4,.9]]
    assert result["detection_verified"]


def test_repairing_invalid_legacy_address_does_not_block_settings(monkeypatch):
    bound = []
    repo = SimpleNamespace(get_index_state=lambda: {"model": "legacy"},
        get_connection_id=lambda: None, set_connection_id=bound.append)
    monkeypatch.setattr(similar_state, "EmbeddingRepository", lambda: repo)
    similar_state.preserve_legacy_connection({"url": "https://[broken"},
        {"provider": "qwen", "url": "https://dashscope.aliyuncs.com", "model": "image"})
    assert bound  # The old unusable index must remain isolated after the repair.


def test_face_model_query_uses_own_masked_key_and_full_endpoint(monkeypatch):
    from core.ai_services import connections
    from core.secret_fields import mask_secret
    cfg = {"ai_services": {"faces": {"provider": "openai", "url": "https://face.test/proxy/v1/chat/completions", "api_key": "face-test-key"}},
           "translate": {"openai": {"api_key": "unrelated-key"}}}
    monkeypatch.setattr(ai_services, "load_config", lambda: cfg)
    seen = []
    async def query(provider, base, key):
        seen.append((provider, base, key))
        return ["vision-model"]
    monkeypatch.setattr(connections, "fetch_provider_models", query)
    result = asyncio.run(ai_services.faces_models(ai_services.FacesTestRequest(api_key=mask_secret("face-test-key"))))
    assert result == {"success": True, "models": ["vision-model"]}
    assert seen == [("openai", "https://face.test/proxy/v1", "face-test-key")]


@pytest.mark.parametrize("unreadable", [False, True])
def test_inflight_old_index_write_cannot_overwrite_rebuilt_connection(tmp_path, monkeypatch, unreadable):
    db = tmp_path / 'race.db'
    connection.init_db(db)
    video_id = VideoRepository(db).upsert(Video(path='/test.mp4', cover_path='/cover.jpg'))
    repo = EmbeddingRepository(db)
    repo.begin_index('same-model', 256)
    repo.set_connection_id('connection-A')
    old = similar_index._Ctx('incremental', repo, SimpleNamespace(), {}, 'same-model', 256)
    new_vector = pack_vector([0., 1.] + [0.] * 254)
    def rebuild():
        repo.reset_index('same-model', 256)
        repo.set_connection_id('connection-B')
        repo.write_vector(video_id, 'same-model', 256, new_vector, '/cover.jpg')
        repo.mark_complete()
    if unreadable:
        def cover(*_):
            rebuild()
            return None
        monkeypatch.setattr(similar_index, '_cover_data_uri', cover)
    else:
        monkeypatch.setattr(similar_index, '_cover_data_uri', lambda *_: 'image-A')
        def embed(*_, **kwargs):
            rebuild()
            return SimpleNamespace(model='same-model', dim=256, vector=[1.] + [0.] * 255)
        monkeypatch.setattr(similar_index.embeddings, 'embed', embed)
    assert similar_index._embed_and_store(old, video_id, '/cover.jpg') == 'model_changed'
    assert repo.get_row(video_id)['vec'] == new_vector
    assert repo.get_row(video_id)['dim'] == 256


def test_delayed_legacy_faces_save_hook_does_not_call_cloud(monkeypatch):
    cloud = {'ai_services': {'faces': {'enabled': True, 'provider': 'openai', 'url': 'https://cloud.test/v1', 'model': 'vision'}}}
    monkeypatch.setattr(faces_recompute, 'load_config', lambda: cloud)
    monkeypatch.setattr(samples, 'run_faces_test', lambda *_: pytest.fail('unrequested cloud call'))
    assert not faces_recompute.on_settings_saved()


def test_old_face_job_stops_before_detecting_with_changed_connection(tmp_path, monkeypatch):
    image = tmp_path / 'cover.jpg'
    image.write_bytes(b'test')
    old = {'ai_services': {'faces': {'enabled': True, 'provider': 'endpoint', 'url': 'https://old.test', 'model': 'local'}}}
    cloud = {'ai_services': {'faces': {'enabled': True, 'provider': 'openai', 'url': 'https://cloud.test/v1', 'model': 'vision'}}}
    monkeypatch.setattr(faces_recompute, 'load_config', lambda: old)
    faces_recompute._begin_job('model_change')
    monkeypatch.setattr(faces_recompute, 'load_config', lambda: cloud)
    monkeypatch.setattr(faces_detect, 'detect', lambda *_, **kw: pytest.fail('legacy job used new cloud connection'))
    try:
        result = faces_recompute._process_one(SimpleNamespace(), ('/test.mp4', 'FC2', '', str(image), '', False), {})
        assert result == 'connection_changed'
    finally:
        faces_recompute._release_job('stopped')


def test_old_config_context_cannot_capture_new_connection_identity(tmp_path, monkeypatch):
    db = tmp_path / 'late-context.db'
    connection.init_db(db)
    video_id = VideoRepository(db).upsert(Video(path='/test.mp4', cover_path='/cover.jpg'))
    repo = EmbeddingRepository(db)
    repo.begin_index('same', 256)
    cfg_a = SimpleNamespace(provider='endpoint', url='https://a.test', model='same')
    cfg_b = SimpleNamespace(provider='endpoint', url='https://b.test', model='same')
    repo.set_connection_id(embedding_connection_id(cfg_b))
    new_vector = pack_vector([0., 1.] + [0.] * 254)
    repo.write_vector(video_id, 'same', 256, new_vector, '/cover.jpg')
    old = similar_index._Ctx('incremental', repo, cfg_a, {}, 'same', 256)
    monkeypatch.setattr(similar_index, '_cover_data_uri', lambda *_: 'image')
    monkeypatch.setattr(similar_index.embeddings, 'embed', lambda *_, **kw:
        SimpleNamespace(model='same', dim=256, vector=[1.] + [0.] * 255))
    assert similar_index._embed_and_store(old, video_id, '/cover.jpg') == 'model_changed'
    assert repo.get_row(video_id)['vec'] == new_vector


def test_faces_background_detection_uses_authorized_snapshot(monkeypatch):
    old = {'ai_services': {'faces': {'enabled': True, 'provider': 'endpoint', 'url': 'https://old.test'}}}
    monkeypatch.setattr(faces_detect, 'load_config', lambda: pytest.fail('reread current connection'))
    monkeypatch.setattr(faces_detect, 'cover_to_faces_data_uri', lambda _: ('image', (100, 100)))
    assert faces_detect._prepare('/cover.jpg', old)[0] == old


def test_cloud_automatic_ensure_and_disabled_jobs_do_not_make_requests(monkeypatch):
    cloud = {'ai_services': {'faces': {'enabled': True, 'provider': 'openai', 'url': 'https://cloud.test'}}}
    monkeypatch.setattr(faces_recompute, 'load_config', lambda: cloud)
    monkeypatch.setattr(faces_recompute.faces_state, 'meta_set', lambda *_: pytest.fail('automatic target update'))
    monkeypatch.setattr(samples, 'run_faces_test', lambda *_: pytest.fail('unrequested request'))
    assert not faces_recompute.ensure('vision:old')
    cloud['ai_services']['faces']['enabled'] = False
    assert faces_recompute.resume()['reason'] == 'disabled'
    assert faces_recompute.start_rebuild()['reason'] == 'disabled'
