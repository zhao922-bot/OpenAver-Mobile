from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from core.ai_services import embeddings, faces
from core.config import FacesConfig, ImageSimilarConfig


IMAGE = "data:image/jpeg;base64,aGVsbG8="


def wire(monkeypatch, module, reply):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply)
    monkeypatch.setattr(module, "_new_client", lambda timeout: httpx.Client(
        transport=httpx.MockTransport(handle), timeout=timeout))
    return calls


def test_old_configs_default_to_endpoint_and_new_providers_roundtrip():
    assert ImageSimilarConfig().provider == FacesConfig().provider == "endpoint"
    assert ImageSimilarConfig(provider="qwen").model_dump()["provider"] == "qwen"
    assert FacesConfig(provider="openai").model_dump()["provider"] == "openai"


@pytest.mark.parametrize("base", ["https://qwen.test", "https://qwen.test/api/v1",
    "https://qwen.test/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"])
def test_qwen_image_vector_request_and_normalization(monkeypatch, base):
    calls = wire(monkeypatch, embeddings, {"output": {"embeddings": [
        {"index": 0, "type": "image", "embedding": [1.] * 256}]}})
    cfg = SimpleNamespace(provider="qwen", url=base, model="qwen3-vl-embedding", api_key="image-key")
    result = embeddings.embed(cfg, IMAGE)
    request = calls[0]
    assert request.url.path == "/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
    assert request.headers["Authorization"] == "Bearer image-key"
    assert json.loads(request.content) == {"model": "qwen3-vl-embedding", "input": {"contents": [{"image": IMAGE}]}}
    assert result.dim == 256
    assert result.vector[0] == pytest.approx(1/16)
    assert "qwen3-vl-embedding" in result.model


@pytest.mark.parametrize("base,path", [
    ("https://api.deepseek.com", "/chat/completions"),
    ("https://api.b.ai/v1", "/v1/chat/completions"),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "/compatible-mode/v1/chat/completions"),
    ("https://gateway.test/prefix/v1/chat/completions", "/prefix/v1/chat/completions"),
])
def test_vision_faces_request_and_coordinates(monkeypatch, base, path):
    content = {"faces": [{"box": [.2, .1, .3, .4], "score": .9}]}
    calls = wire(monkeypatch, faces, {"model": "vision", "choices": [{"finish_reason": "stop",
        "message": {"content": json.dumps(content)}}]})
    cfg = SimpleNamespace(provider="openai", url=base, model="vision", api_key="face-key")
    result = faces.detect(cfg, IMAGE)
    assert calls[0].url.path == path
    assert calls[0].headers["Authorization"] == "Bearer face-key"
    payload = json.loads(calls[0].content)
    assert payload["model"] == "vision"
    assert payload["messages"][1]["content"][1]["image_url"]["url"] == IMAGE
    assert result.boxes == [faces.Box(.2, .1, .3, .4, .9)]


@pytest.mark.parametrize("choice", [
    {"finish_reason": "length", "message": {"content": '{"faces":[]}'}},
    {"finish_reason": "stop", "message": {"refusal": "no", "content": '{"faces":[]}'}},
    {"finish_reason": "stop", "message": {"content": "Sorry, cannot process"}},
    {"finish_reason": "stop", "message": {"content": '{"faces":[{"box":[0.8,0,0.5,1]}]}'}},
    {"finish_reason": "stop", "message": {"content": '{"faces":[{"box":[0,0,0,1]}]}'}},
])
def test_vision_rejects_refusals_truncation_and_invalid_boxes(monkeypatch, choice):
    wire(monkeypatch, faces, {"choices": [choice]})
    cfg = SimpleNamespace(provider="openai", url="https://face.test/v1", model="vision", api_key="k")
    with pytest.raises(embeddings.EndpointError):
        faces.detect(cfg, IMAGE)


def test_legitimate_no_face_is_success(monkeypatch):
    wire(monkeypatch, faces, {"choices": [{"finish_reason": "stop", "message": {"content": '{"faces":[]}'}}]})
    cfg = SimpleNamespace(provider="openai", url="https://face.test/v1", model="vision", api_key="")
    assert faces.detect(cfg, IMAGE).boxes == []


def test_cloud_vectors_from_different_connections_are_separated(monkeypatch):
    wire(monkeypatch, embeddings, {"output": {"embeddings": [{"embedding": [1.] * 256}]}})
    cfg = SimpleNamespace(provider="qwen", url="https://first.test", model="same", api_key="key")
    first = embeddings.embed(cfg, IMAGE).model
    cfg.api_key = "new-key"
    assert embeddings.embed(cfg, IMAGE).model == first
    cfg.url = "https://other.test"
    assert embeddings.embed(cfg, IMAGE).model != first
