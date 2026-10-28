"""啟動各階段時間戳（只寫 debug.log）。

僅 stdlib；logger 在寫出路徑內才 import，import 本模組時不依賴 logger 狀態。
flush() 之前的 mark() 只暫存，flush() 才補寫並進入直接輸出狀態。
"""
import threading
import time

_T0 = time.perf_counter()
_lock = threading.Lock()
_buffer = []
_seen = set()
_armed = False
_last_cum = 0

_BASELINE = "啟動計時基準：累計毫秒自 standalone／launcher 腳本載入起算（不含 Python 直譯器啟動）"


def _logger():
    from core.logger import get_logger
    return get_logger("startup")


def _emit(key: str, cum: int) -> None:
    global _last_cum
    step = cum - _last_cum
    _last_cum = cum
    _logger().info("啟動計時 %s 累計 %dms（+%dms）", key, cum, step)
    if key == "first_page_loaded":
        _logger().info("啟動計時 total 累計 %dms", cum)


def mark(key: str) -> None:
    now = time.perf_counter()
    cum = int((now - _T0) * 1000)
    with _lock:
        if key in _seen:
            return
        _seen.add(key)
        if not _armed:
            _buffer.append((key, cum))
            return
        _emit(key, cum)


def flush() -> None:
    global _armed
    with _lock:
        if _armed:
            return
        _armed = True
        _logger().info(_BASELINE)
        pending = list(_buffer)
        _buffer.clear()
        for key, cum in pending:
            _emit(key, cum)
