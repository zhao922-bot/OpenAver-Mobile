"""人一按，cron 讓路（feature/144-auto-organize T4a）。

這**不是鎖**——沒有租約、沒有續租、沒有取得閘。四個 module-level 變數是
cron 迴圈與三個既有 web handler 之間的體感交接板：人在場時人優先、
cron 不白跑、訊息看得懂（plan CD-144-12）。任何時序漏洞的代價上限是
「兩邊白跑一趟」，不會掉片——真正的資料安全保證在 core/organizer.py
的原子佔位（T0）。

公開介面：
  - enter_cron(trigger, now=None) -> bool
  - exit_cron() -> None
  - set_current_number(number) -> None
  - should_abort() -> bool
  - mark_manual_activity(now=None) -> None
  - request_abort() -> None
  - get_status(now=None) -> dict

🚫 紅線（CD-144-12 明文）：``_last_manual_at`` 全庫只有 ``enter_cron()``
一個讀取點，且只在 ``trigger == 'schedule'`` 分支裡讀。不得新增第二個
讀取點做「人還持有中所以擋住某個手動操作」這類判斷。
"""

from __future__ import annotations

import threading
import time
from typing import Literal

_lock = threading.Lock()
_running: bool = False
_current_number: str | None = None
_abort_requested: bool = False
_last_manual_at: float = float("-inf")

_MANUAL_QUIET_WINDOW_S = 600.0


def _now() -> float:
    """Indirection over ``time.time()`` so tests can inject a fake clock.

    Wall clock，刻意不用 ``time.monotonic()``（見 plan CD-144-12 設計決策②）：
    ``_last_manual_at`` 語意是「牆上時鐘的 10 分鐘」，與 T2
    ``organize_failures`` 的時鐘一致。Module-level function（不是 lambda）
    讓 ``unittest.mock.patch.object`` 能穩定 monkeypatch。
    """
    return time.time()


def enter_cron(trigger: Literal["schedule", "run_now"], now: float | None = None) -> bool:
    """cron 進場。``trigger='run_now'`` 只被『另一輪已在跑』擋下。"""
    global _running, _current_number, _abort_requested
    now = now if now is not None else _now()
    with _lock:
        if _running:
            return False
        if trigger == "schedule" and now - _last_manual_at < _MANUAL_QUIET_WINDOW_S:
            return False
        _running = True
        _abort_requested = False
        _current_number = None
        return True


def exit_cron() -> None:
    global _running, _current_number, _abort_requested
    with _lock:
        _running = False
        _current_number = None
        _abort_requested = False


def set_current_number(number: str) -> None:
    global _current_number
    with _lock:
        _current_number = number


def should_abort() -> bool:
    with _lock:
        return _abort_requested


def mark_manual_activity(now: float | None = None) -> None:
    """三個既有 handler 的掛載點都打這支；純記憶體寫入，零 I/O。"""
    global _last_manual_at
    now = now if now is not None else _now()
    with _lock:
        _last_manual_at = now


def request_abort() -> None:
    """兩個呼叫點：favorite-files handler（人要用了）與撥掉排程開關（人要它停）。

    沒在跑時不設旗標；``enter_cron()`` 進場也會把旗標歸零，所以不會外溢到之後的輪次。
    """
    global _abort_requested
    with _lock:
        if _running:
            _abort_requested = True


def get_status(now: float | None = None) -> dict:
    """純讀，不改變任何狀態，也不讀/寫 ``_last_manual_at``。"""
    with _lock:
        return {"running": _running, "current_number": _current_number}
