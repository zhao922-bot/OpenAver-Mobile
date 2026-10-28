"""core/data_root.py — process-lifetime data-root resolver.

T2 起 `OPENAVER_DATA_DIR` 生效（與 external-root gate 同顆交付）。
無 class、不 import web 層。

本模組有兩類函式：
1. 純路徑推導（`get_data_root()`／`get_default_data_root()`／`get_project_root()`／
   `resolve_gallery_output_path()`）——維持無 I/O。
2. layout marker 狀態判定（`read_layout_marker_state()`／`is_layout_finalized()`）——
   會讀 `<root>/.layout.json`。這是本模組唯一的 I/O 例外：`core/config.py` 與
   `core/data_layout.py` 必須共用同一判定，又不能互相 import（反向會循環——
   `data_layout.py` 已 import `CONFIG_DEFAULT_PATH`），而本檔是唯一同時被兩邊
   import、且不會造成循環的模組（`LAYOUT_MARKER_NAME` 當初就是同一理由放這裡）。
"""
import json
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

# 資料根定版標記檔名。放此檔（而非 data_layout）以免 config ↔ data_layout 循環 import。
LAYOUT_MARKER_NAME = ".layout.json"
LAYOUT_VERSION = 1

MARKER_STATE_ABSENT = "absent"
MARKER_STATE_VALID = "valid"
MARKER_STATE_INVALID = "invalid"


def _default_output_root() -> Path:
    """現有預設 output 目錄（= <project_root>/output）。純路徑推導，無 I/O。"""
    return _PROJECT_ROOT / "output"


def get_default_data_root() -> Path:
    """回傳未受 OPENAVER_DATA_DIR 覆寫的預設資料根。純路徑推導，無 I/O。"""
    return _default_output_root()


def get_data_root() -> Path:
    """回傳目前 process 的資料根目錄。

    非空的 OPENAVER_DATA_DIR 覆寫預設位置；本函式只做路徑推導，不建目錄、不讀檔。
    external-root gate（空 override + 本機有舊資料 → 阻斷）由
    ``core.data_layout.bootstrap_data_layout`` 負責。
    """
    raw = os.environ.get("OPENAVER_DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return _default_output_root()


def get_project_root() -> Path:
    """回傳專案根目錄。純路徑推導，無 I/O。"""
    return _PROJECT_ROOT


def resolve_gallery_output_path(output_dir: str) -> Path:
    """解析 gallery.output_dir 為絕對 Path。

    空／純空白 → get_data_root()（跟著資料根走）；
    非空相對值 → get_project_root() / value；
    非空絕對值 → 原樣。純路徑推導，無 I/O。
    """
    value = (output_dir or "").strip()
    if not value:
        return get_data_root()
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return get_project_root() / value


def read_layout_marker_state(root: Path) -> str:
    """讀取 ``<root>/.layout.json`` 的定版狀態（會讀檔）。

    回傳 ``MARKER_STATE_ABSENT``／``MARKER_STATE_VALID``／``MARKER_STATE_INVALID``。
    讀取／解析失敗、非 dict、version 不符、或 complete 不是 True → invalid。
    """
    marker_path = root / LAYOUT_MARKER_NAME
    if not marker_path.is_file():
        return MARKER_STATE_ABSENT
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return MARKER_STATE_INVALID
    if not isinstance(data, dict):
        return MARKER_STATE_INVALID
    if data.get("version") != LAYOUT_VERSION or data.get("complete") is not True:
        return MARKER_STATE_INVALID
    return MARKER_STATE_VALID


def is_layout_finalized(root: Path) -> bool:
    """``root`` 是否已定版（會讀 ``.layout.json``）。"""
    return read_layout_marker_state(root) == MARKER_STATE_VALID
