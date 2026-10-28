"""core/self_update.py — 查 GitHub 有沒有新版、開終端機跑官方安裝腳本（伺服器端點與桌面殼共用）。

純 Python；不 import web／webview。httpx／subprocess／sys／Path 一律屬性存取，
讓既有 ``mock.patch("web.app.subprocess.Popen")``、``monkeypatch.setattr(sys, ...)`` 繼續命中。
"""
import re
import subprocess
import sys
from pathlib import Path

import httpx

from core.logger import get_logger
from core.version import VERSION

logger = get_logger(__name__)

GITHUB_LATEST_API = "https://api.github.com/repos/slive777/OpenAver/releases/latest"
INSTALL_PS1_URL = "https://raw.githubusercontent.com/slive777/OpenAver/main/install.ps1"
INSTALL_SH_URL = "https://raw.githubusercontent.com/slive777/OpenAver/main/install.sh"

_VER_RE = re.compile(r"(\d+(?:\.\d+)*)")


def parse_version(v) -> tuple:
    """'0.10.0-rc1' → (0, 10, 0)；無法解析丟 ValueError（含非字串）。"""
    m = _VER_RE.match(v) if isinstance(v, str) else None
    if not m:
        raise ValueError(f"Cannot parse version: {v!r}")
    return tuple(int(x) for x in m.group(1).split("."))


def is_newer(latest, current) -> bool:
    """語意版本比較（tuple，避免 '0.10.0' < '0.9.0'）；解析失敗 False。"""
    try:
        lt, ct = parse_version(latest), parse_version(current)
    except ValueError:
        return False
    return lt > ct


def check_latest(current=None, *, transport=None) -> dict:
    """同步查 GitHub 最新 release。

    成功 ``{ok:True, has_update, current_version[, latest_version, download_url]}``；
    失敗 ``{ok:False, reason: timeout|network|bad_response}``。
    """
    current = VERSION if current is None else current
    try:
        with httpx.Client(timeout=httpx.Timeout(5.0), transport=transport) as client:
            resp = client.get(GITHUB_LATEST_API, headers={"Accept": "application/vnd.github.v3+json"})
    except httpx.TimeoutException:
        return {"ok": False, "reason": "timeout"}
    except httpx.HTTPError as e:
        logger.warning("檢查更新連線失敗: %s", e)
        return {"ok": False, "reason": "network"}
    if resp.status_code == 404:
        return {"ok": True, "has_update": False, "current_version": current}
    if not 200 <= resp.status_code < 300:
        return {"ok": False, "reason": "bad_response"}
    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "reason": "bad_response"}
    if not isinstance(data, dict):
        return {"ok": False, "reason": "bad_response"}
    latest = str(data.get("tag_name") or "").lstrip("v")
    return {
        "ok": True,
        "has_update": is_newer(latest, current),
        "current_version": current,
        "latest_version": latest,
        "download_url": data.get("html_url", ""),
    }


def install_dir():
    """目前 Python 所在的安裝根目錄（darwin 上三層、其餘兩層）。"""
    exe = Path(sys.executable)
    if sys.platform == "darwin":
        return exe.parent.parent.parent  # python/bin/python3 → OpenAver/
    return exe.parent.parent  # python\pythonw.exe → OpenAver\


def is_default_install() -> bool:
    """安裝在預設位置 ``~/OpenAver``？偵測失敗視為 True（保守）。"""
    try:
        return install_dir() == Path.home() / "OpenAver"
    except Exception:
        return True


def installer_argv(platform=None) -> list:
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return ["powershell.exe", "-ExecutionPolicy", "Bypass", "-NoProfile",
                "-Command", f"irm {INSTALL_PS1_URL} | iex"]
    return ["osascript", "-e",
            "tell application \"Terminal\" to do script "
            f"\"curl -fsSL {INSTALL_SH_URL} | bash\""]


def launch_installer() -> None:
    """開外部終端機跑官方安裝腳本。Popen 例外往外丟。"""
    if sys.platform == "win32":
        subprocess.Popen(installer_argv("win32"), creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen(installer_argv(sys.platform))
