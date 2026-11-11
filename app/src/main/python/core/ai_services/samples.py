"""Consistency-test samples A/B and assertions (CD-186-7)."""

from __future__ import annotations

import base64
import io
import math
import time
from dataclasses import dataclass

from PIL import Image, ImageDraw

from core.ai_services.embeddings import EmbedResult, EndpointError, embed
from core.ai_services.faces import FacesResult, detect
from core.ai_services.image_prep import _encode_jpeg_data_uri

SAME_MIN = 0.99
DIFF_MAX = 0.9
DIM_MIN = 128
DIM_MAX = 4096

FACES_EXPECT_CENTER = (0.5, 0.3)
FACES_TOLERANCE = 0.1
FACES_MIN_FACES = 1
_cache_faces: str | None = None

# Sample B: deterministic synthetic PNG — fixed size / bg / primitives, no RNG.
# kind: "rect"(x0,y0,x1,y1,rgb) | "ellipse"(…) | "polygon"(points, rgb)
B_SIZE = 448
B_BG = (32, 48, 160)
B_SHAPES: tuple = (
    ("rect", 36, 36, 200, 200, (220, 48, 48)),
    ("ellipse", 220, 180, 412, 412, (240, 220, 48)),
    ("polygon", ((224, 24), (400, 168), (48, 168)), (48, 200, 72)),
)
B_PNG_COMPRESS_LEVEL = 6

_cache_a: str | None = None
_cache_b: str | None = None


def _cosine(a: list[float], b: list[float]) -> float:
    return math.sumprod(a, b)


def check_consistency(
    a1: EmbedResult, a2: EmbedResult, b: EmbedResult
) -> tuple[bool, str | None]:
    """Pure assertions over three embed results. Order fixed by CD-186-7."""
    if not (
        a1.dim == a2.dim == b.dim and DIM_MIN <= a1.dim <= DIM_MAX
    ):
        return False, "dim_mismatch"
    same = _cosine(a1.vector, a2.vector)
    if same < SAME_MIN:
        return False, "unstable"
    diff = _cosine(a1.vector, b.vector)
    if not (diff < DIFF_MAX):
        return False, "not_discriminative"
    if not (a1.model == a2.model == b.model):
        return False, "model_flapping"
    return True, None


def _render_sample_b_png_bytes() -> bytes:
    img = Image.new("RGB", (B_SIZE, B_SIZE), B_BG)
    draw = ImageDraw.Draw(img)
    for shape in B_SHAPES:
        kind = shape[0]
        if kind == "rect":
            _, x0, y0, x1, y1, fill = shape
            draw.rectangle((x0, y0, x1, y1), fill=fill)
        elif kind == "ellipse":
            _, x0, y0, x1, y1, fill = shape
            draw.ellipse((x0, y0, x1, y1), fill=fill)
        elif kind == "polygon":
            _, points, fill = shape
            draw.polygon(list(points), fill=fill)
        else:
            raise ValueError(f"unknown shape kind: {kind}")
    buf = io.BytesIO()
    # Fixed save params (DoD 5): no optimize, no pnginfo, fixed compress_level.
    img.save(
        buf,
        format="PNG",
        compress_level=B_PNG_COMPRESS_LEVEL,
        optimize=False,
    )
    return buf.getvalue()


def sample_b_data_uri() -> str:
    """Lazy module-level cache of synthetic sample B (PNG data URI)."""
    global _cache_b
    if _cache_b is None:
        raw = _render_sample_b_png_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        _cache_b = f"data:image/png;base64,{b64}"
    return _cache_b


def sample_a_data_uri() -> str:
    """Lazy module-level cache of deterministic synthetic sample A.

    The mobile build intentionally ships no demo photos.  A fixed portrait-like
    composition keeps the consistency test deterministic without restoring the
    removed desktop demo assets.
    """
    global _cache_a
    if _cache_a is None:
        img = Image.new("RGB", (448, 448), (226, 218, 205))
        draw = ImageDraw.Draw(img)
        draw.ellipse((104, 40, 344, 330), fill=(220, 168, 132))
        draw.polygon(((104, 110), (168, 22), (310, 28), (350, 124)),
                     fill=(38, 30, 28))
        draw.ellipse((156, 152, 194, 190), fill=(45, 42, 40))
        draw.ellipse((254, 152, 292, 190), fill=(45, 42, 40))
        draw.polygon(((214, 188), (234, 188), (226, 230)),
                     fill=(190, 132, 102))
        draw.arc((174, 218, 278, 292), 10, 170, fill=(120, 50, 50), width=7)
        draw.rectangle((0, 330, 448, 448), fill=(48, 78, 118))
        draw.ellipse((90, 334, 358, 500), fill=(238, 236, 230))
        _cache_a = _encode_jpeg_data_uri(img, 90)
    return _cache_a


def get_sample_inputs() -> tuple[str, str]:
    """Return cached (A, B) data URIs; builds on first call."""
    return sample_a_data_uri(), sample_b_data_uri()


@dataclass
class ConsistencyResult:
    ok: bool
    kind: str | None = None
    check: str | None = None
    model: str | None = None
    dim: int | None = None
    cos_same: float | None = None
    cos_diff: float | None = None
    elapsed_ms: int = 0


def run_consistency_test(cfg) -> ConsistencyResult:
    """A (first=True) → A → B; stop on first EndpointError."""
    t0 = time.perf_counter()
    try:
        a_uri, b_uri = get_sample_inputs()
        a1 = embed(cfg, a_uri, first=True)
        a2 = embed(cfg, a_uri, first=False)
        b = embed(cfg, b_uri, first=False)
    except EndpointError as e:
        elapsed = int((time.perf_counter() - t0) * 1000)
        return ConsistencyResult(
            ok=False, kind=e.kind, check=e.check, elapsed_ms=elapsed
        )

    elapsed = int((time.perf_counter() - t0) * 1000)
    ok, failed = check_consistency(a1, a2, b)
    cos_same = cos_diff = None
    if a1.dim == a2.dim == b.dim:
        cos_same = _cosine(a1.vector, a2.vector)
        cos_diff = _cosine(a1.vector, b.vector)
    return ConsistencyResult(
        ok=ok,
        kind=None if ok else "contract",
        check=failed,
        model=a1.model,
        dim=a1.dim,
        cos_same=cos_same,
        cos_diff=cos_diff,
        elapsed_ms=elapsed,
    )


def sample_faces_data_uri() -> str:
    """Lazy module-level cache of a deterministic face sample."""
    global _cache_faces
    if _cache_faces is None:
        img = Image.new("RGB", (640, 650), (202, 214, 226))
        draw = ImageDraw.Draw(img)
        # The face is centred at the documented expectation (0.5, 0.3).
        draw.ellipse((170, 28, 470, 362), fill=(224, 174, 140))
        draw.pieslice((160, 8, 480, 220), 180, 360, fill=(42, 34, 30))
        draw.ellipse((224, 146, 266, 188), fill=(44, 40, 38))
        draw.ellipse((374, 146, 416, 188), fill=(44, 40, 38))
        draw.polygon(((308, 186), (332, 186), (320, 242)),
                     fill=(188, 128, 100))
        draw.arc((252, 236, 388, 318), 12, 168, fill=(128, 56, 56), width=8)
        draw.rectangle((0, 390, 640, 650), fill=(52, 82, 112))
        draw.ellipse((118, 396, 522, 700), fill=(242, 240, 232))
        _cache_faces = _encode_jpeg_data_uri(img, 90)
    return _cache_faces


def get_faces_sample_input() -> str:
    """Return cached faces sample data URI; builds on first call."""
    return sample_faces_data_uri()


def check_faces_consistency(result: FacesResult) -> tuple[bool, str | None]:
    """Pure assertions over a faces detect result. Order fixed by CD-187a-19."""
    if len(result.boxes) < FACES_MIN_FACES:
        return False, "no_face"
    best = max(result.boxes, key=lambda b: b.score)
    cx = best.x + best.w / 2.0
    cy = best.y + best.h / 2.0
    if abs(cx - FACES_EXPECT_CENTER[0]) > FACES_TOLERANCE or abs(cy - FACES_EXPECT_CENTER[1]) > FACES_TOLERANCE:
        return False, "center_off"
    if not isinstance(result.model, str) or result.model == "":
        return False, "no_model"
    return True, None


@dataclass
class FacesTestResult:
    ok: bool
    kind: str | None = None
    check: str | None = None
    model: str | None = None
    elapsed_ms: int = 0
    boxes: list | None = None


def run_faces_test(cfg) -> FacesTestResult:
    """Sample → detect(profile=warmup) → consistency; stop on EndpointError."""
    t0 = time.perf_counter()
    try:
        uri = get_faces_sample_input()
        result = detect(cfg, uri, profile="warmup")
    except EndpointError as e:
        elapsed = int((time.perf_counter() - t0) * 1000)
        return FacesTestResult(
            ok=False, kind=e.kind, check=e.check, elapsed_ms=elapsed
        )

    elapsed = int((time.perf_counter() - t0) * 1000)
    ok, failed = check_faces_consistency(result)
    return FacesTestResult(
        ok=ok,
        kind=None if ok else "contract",
        check=failed,
        model=result.model,
        elapsed_ms=elapsed,
        boxes=list(result.boxes),
    )
