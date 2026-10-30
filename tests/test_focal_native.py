from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import core


def _load_detector_without_package_side_effects():
    previous_module = sys.modules.get("core.focal")
    previous_attribute = getattr(core, "focal", None)
    focal_package = types.ModuleType("core.focal")
    focal_package.__path__ = [
        str(Path(core.__file__).resolve().parent / "focal")
    ]
    sys.modules["core.focal"] = focal_package
    setattr(core, "focal", focal_package)
    try:
        return importlib.import_module("core.focal.detector")
    finally:
        if previous_module is None:
            sys.modules.pop("core.focal", None)
        else:
            sys.modules["core.focal"] = previous_module
        if previous_attribute is None:
            delattr(core, "focal")
        else:
            setattr(core, "focal", previous_attribute)


detector = _load_detector_without_package_side_effects()


def test_native_focal_status_degrades_without_library(monkeypatch, tmp_path):
    missing = tmp_path / "missing-libopenaver_mobile.so"
    monkeypatch.setenv("OPENAVER_NATIVE_LIB", str(missing))
    monkeypatch.setattr(detector, "_lib", None)

    assert detector.native_focal_status() == "unavailable"


def test_detect_focal_returns_none_for_unreadable_image(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAVER_FOCAL_NATIVE", "1")

    assert detector.detect_focal(str(tmp_path / "missing.jpg"), 0.72, 650) is None


def test_detect_focal_exposes_timeout_status(monkeypatch, tmp_path):
    from PIL import Image

    cover = tmp_path / "cover.jpg"
    Image.new("RGB", (8, 8), "white").save(cover)
    monkeypatch.setenv("OPENAVER_FOCAL_NATIVE", "1")
    monkeypatch.setattr(
        detector,
        "_native_detect_focal_status",
        lambda _image, _timeout_ms: (None, "timeout"),
    )

    focal, status = detector.detect_focal_with_status(
        str(cover), 0.71, 650, timeout_s=0.1
    )

    assert focal is None
    assert status == "timeout"
