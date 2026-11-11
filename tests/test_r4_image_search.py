from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.responses import JSONResponse
from PIL import Image
from starlette.datastructures import Headers, UploadFile

from core.avscan.client import AvscanRateLimited
from core.avscan.gate import AvscanGate
from core.avscan.image_prep import MAX_EDGE, prepare_image
from core.avscan.rules import is_clear_hit, map_code, parse_frame_name, safe_thumb_path
from web.routers import image_search as image_search_router


class FakeClock:
    def __init__(self, now: float = 0.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeRepository:
    found: dict[str, list[object]] = {}
    calls: list[list[str]] = []
    error: Exception | None = None

    def __init__(self, *_args, **_kwargs):
        pass

    def get_by_numbers(self, numbers: list[str]) -> dict[str, list[object]]:
        type(self).calls.append(list(numbers))
        if type(self).error is not None:
            raise type(self).error
        return type(self).found


def _jpeg(size: tuple[int, int] = (32, 32)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (180, 20, 20)).save(buffer, "JPEG")
    return buffer.getvalue()


def _upload(data: bytes, name: str = "query.jpg") -> UploadFile:
    return UploadFile(
        BytesIO(data),
        filename=name,
        headers=Headers({"content-type": "image/jpeg"}),
    )


def _raw_candidate(code: str, similarity: float) -> dict:
    return {
        "code": code,
        "similarity": similarity,
        "match": {
            "kind": "frame",
            "cover_part": None,
            "time_seconds": 2306,
            "time_text": "00:38:26",
            "thumb_url": None,
        },
    }


@pytest.fixture(autouse=True)
def reset_fake_repository():
    FakeRepository.found = {}
    FakeRepository.calls = []
    FakeRepository.error = None


def test_avscan_rules_cover_searchable_ids_and_clear_hits():
    assert map_code("MIMK-200") == ("MIMK-200", True)
    assert map_code("178X023") == ("178X023", False)
    assert is_clear_hit([90.0, 82.0]) == (True, 8.0)
    assert is_clear_hit([90.0, 85.0]) == (False, 5.0)
    assert is_clear_hit([90.0]) == (False, None)
    assert parse_frame_name("MIMK-200_00-38-26.jpg") == (
        "frame",
        None,
        2306,
        "00:38:26",
    )
    assert parse_frame_name("IPX-338_cover_full.jpg") == (
        "cover",
        "full",
        None,
        None,
    )
    assert safe_thumb_path("/thumb/token/MIMK-200/main.webp") is True
    assert safe_thumb_path("/thumb/token/../main.webp") is False


def test_avscan_gate_enforces_single_flight_and_gap():
    clock = FakeClock()
    gate = AvscanGate(clock=clock, min_gap=5)

    assert gate.try_acquire() == (True, 0)
    assert gate.try_acquire()[0] is False
    gate.release()
    assert gate.try_acquire()[0] is False

    clock.now = 5
    assert gate.try_acquire() == (True, 0)
    gate.release()
    gate.penalize(10)
    clock.now = 14
    assert gate.try_acquire()[0] is False
    clock.now = 15
    assert gate.try_acquire()[0] is True


def test_image_preparation_passes_small_images_and_resizes_large_images():
    small = _jpeg((64, 48))
    assert MAX_EDGE == 1024
    assert prepare_image(small) == small

    large = _jpeg((2000, 1000))
    resized = prepare_image(large)
    assert resized != large
    image = Image.open(BytesIO(resized))
    assert image.format == "JPEG"
    assert image.size == (1024, 512)


def test_image_search_router_returns_candidate_envelope(monkeypatch):
    monkeypatch.setattr(
        image_search_router,
        "lookup",
        lambda _data: [
            _raw_candidate("FC2-PPV-4966131", 95.0),
            _raw_candidate("IPZZ-001", 82.0),
        ],
    )
    monkeypatch.setattr(image_search_router, "init_db", lambda: None)
    monkeypatch.setattr(image_search_router, "VideoRepository", FakeRepository)
    FakeRepository.found = {"FC2-4966131": [object()]}

    result = image_search_router.image_search(_upload(_jpeg()))

    assert result["success"] is True
    assert result["source"] == "avscan"
    assert result["clear_hit"] is True
    assert result["lead"] == 13.0
    assert result["candidates"][0]["rank"] == 1
    assert result["candidates"][0]["number"] == "FC2-4966131"
    assert result["candidates"][0]["in_library"] is True
    assert result["candidates"][1]["in_library"] is False
    assert FakeRepository.calls == [["FC2-4966131", "IPZZ-001"]]


def test_image_search_router_maps_rate_limit_and_does_not_call_lookup_twice(
    monkeypatch,
):
    calls = []

    def rate_limited(_data):
        calls.append(1)
        raise AvscanRateLimited(7)

    monkeypatch.setattr(image_search_router, "lookup", rate_limited)
    monkeypatch.setattr(image_search_router, "init_db", lambda: None)
    monkeypatch.setattr(image_search_router, "VideoRepository", FakeRepository)

    response = image_search_router.image_search(_upload(_jpeg()))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 429
    assert b'"retry_after":7' in response.body
    assert calls == [1]


def test_image_search_router_rejects_oversize_before_lookup(monkeypatch):
    calls = []
    monkeypatch.setattr(
        image_search_router,
        "lookup",
        lambda data: calls.append(data) or [],
    )

    response = image_search_router.image_search(
        _upload(b"\xff\xd8\xff" + b"x" * image_search_router.MAX_BYTES)
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 413
    assert calls == []


def test_image_search_library_failure_is_reported_as_unknown(monkeypatch):
    monkeypatch.setattr(
        image_search_router,
        "lookup",
        lambda _data: [
            _raw_candidate("IPZZ-001", 90.0),
            _raw_candidate("SONE-103", 70.0),
        ],
    )
    monkeypatch.setattr(image_search_router, "init_db", lambda: None)
    monkeypatch.setattr(image_search_router, "VideoRepository", FakeRepository)
    FakeRepository.error = RuntimeError("database unavailable")

    result = image_search_router.image_search(_upload(_jpeg()))

    assert [item["in_library"] for item in result["candidates"]] == [None, None]
