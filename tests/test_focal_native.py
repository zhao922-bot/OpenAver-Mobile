from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import core


def _load_detector_without_package_side_effects():
    focal_package = types.ModuleType("core.focal")
    focal_package.__path__ = [
        str(Path(core.__file__).resolve().parent / "focal")
    ]
    sys.modules["core.focal"] = focal_package
    setattr(core, "focal", focal_package)
    return importlib.import_module("core.focal.detector")


detector = _load_detector_without_package_side_effects()


def test_native_focal_status_degrades_without_library(monkeypatch, tmp_path):
    missing = tmp_path / "missing-libopenaver_mobile.so"
    monkeypatch.setenv("OPENAVER_NATIVE_LIB", str(missing))
    monkeypatch.setattr(detector, "_lib", None)

    assert detector.native_focal_status() == "unavailable"


def test_detect_focal_returns_none_for_unreadable_image(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAVER_FOCAL_NATIVE", "1")

    assert detector.detect_focal(str(tmp_path / "missing.jpg"), 0.72, 650) is None
