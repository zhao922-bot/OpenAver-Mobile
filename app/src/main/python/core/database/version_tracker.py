"""process-global 版本追蹤：showcase revision 計數器 + DB/-wal 指紋 + 開機隨機值。

供 web/routers/showcase.py 的 ETag 計算使用（CD-145a-8/10/12）。
"""
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
from pathlib import Path

_lock = threading.Lock()
_revision = 0

_BOOT_SECRET = secrets.token_bytes(32)


class _RevisionTrackingConnection(sqlite3.Connection):
    """sqlite3.Connection 子類：commit() 成功後，若該連線的 total_changes
    相對上次 commit 有增加（＝真的寫入了東西），process-global revision 計數器 +1。

    必須覆寫 __exit__：CPython 的 sqlite3.Connection.__exit__ 在 C 層直接
    commit，不走 Python 屬性查找，因此 with 區塊結束時不會呼叫上面的
    commit()，revision 就不會累加。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_committed_total_changes = 0

    def commit(self):
        super().commit()
        current = self.total_changes
        if current > self._last_committed_total_changes:
            _bump_showcase_revision()
        self._last_committed_total_changes = current

    def __exit__(self, exc_type, exc_val, exc_tb):
        """C 層 __exit__ 不 dispatch 到 Python commit()；改走這裡以維持 revision 不變式。"""
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def _bump_showcase_revision() -> None:
    global _revision
    with _lock:
        _revision += 1


def bump_showcase_revision() -> None:
    """公開版 `_bump_showcase_revision`，給**非 DB 寫入、但會改變 API 回應內容**的
    檔案操作呼叫（例如女優照片檔落地／刪除）——這類變動不會經過
    `_RevisionTrackingConnection.commit()`，若不手動 bump，ETag 會對不上實際檔案
    狀態（見 web/routers/insights.py `hasPhoto` 欄位、PR#207 Codex P2）。"""
    _bump_showcase_revision()


def get_showcase_revision() -> int:
    with _lock:
        return _revision


def _stat_fingerprint(path: Path) -> tuple:
    try:
        st = path.stat()
        return (True, st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    except OSError:
        return (False, 0, 0, 0, 0)


def compute_db_fingerprint(db_path: Path) -> tuple:
    wal_path = db_path.with_name(db_path.name + "-wal")
    return (_stat_fingerprint(db_path), _stat_fingerprint(wal_path))


def compute_etag(revision: int, db_fingerprint: tuple, projection: dict) -> str:
    """把 revision／DB 指紋／設定投影三項與開機隨機值一起算 HMAC，回傳可直接
    當 ETag response header 值使用的字串（強驗證子，帶雙引號、不加 `W/` 前綴）。

    三個輸入分別覆蓋「同一次啟動內部發生的寫入」（revision）、「外部整份抽換
    或還原 DB 檔／未經連線工廠的 -wal 寫入」（db_fingerprint）、「使用者改了
    會影響回應內容的設定」（projection）；`_BOOT_SECRET` 讓同一個鍵在不同次
    啟動之間也不會撞值。序列化用 `sort_keys=True` 是刻意的——`db_fingerprint`
    是巢狀 tuple、`projection` 是 dict，都不能依賴呼叫端湊出的插入順序。
    """
    material = json.dumps(
        {"revision": revision, "db_fingerprint": db_fingerprint, "projection": projection},
        sort_keys=True,
        default=str,
    )
    digest = hmac.new(_BOOT_SECRET, material.encode("utf-8"), hashlib.sha256).hexdigest()
    return f'"{digest}"'
