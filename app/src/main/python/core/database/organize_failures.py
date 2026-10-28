"""core.database.organize_failures — 整理失敗記憶持久化資料庫操作（spec-144 T2）。

提供模組層級函式，使用 contextlib.closing(get_connection(db_path)) 管理連線。

**兩種 `reason` 共用同一張表、同一個 `key` 主鍵，靠的是「兩種鍵的字串空間不重疊」**
（CD-144-8）：`not_found` 的鍵是 `UPPER(番號)`（形如 `ABC-123`），`duplicate` 的鍵是
`duplicate_key()` 的輸出、**恆以 `file:///` 開頭**。番號長不成 URI，所以不會互撞。

⚠️ 這是一個**前提，不是保證**——`key` 是單欄主鍵，`ON CONFLICT(key) DO UPDATE` 不會
檢查 `reason` 是否一致。呼叫端若把 `reason` 傳錯（例如拿番號當 `duplicate` 的鍵），
兩筆記錄會擠進同一列、`reason` 被後來者覆寫，症狀是「記憶寫得進去卻查不到」。
排錯時先確認呼叫端有沒有守住鍵空間規則，不要先懷疑退避邏輯。
"""
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

from core.path_utils import to_file_uri
from .connection import get_connection


def _now() -> float:
    return time.time()


def _normalize_key(reason: str, key: str) -> str:
    """兩種鍵的正規化規則不同，而且**只有 `not_found` 那種可以動大小寫**。

    - `reason='not_found'`：鍵是**番號**，`abc-123` 與 `ABC-123` 是同一部片 → 一律轉大寫。
    - `reason='duplicate'`：鍵是 `duplicate_key()` 算出來的 **`file:///` 路徑 URI**
      → **逐字原樣存**。在區分大小寫的檔案系統（NAS／Linux，正是本功能 7/24 無人值守
      的目標平台）上，`/x/abc.mp4` 與 `/x/ABC.mp4` 是**兩個不同的檔案**；把路徑一起
      大寫化會讓它們撞成同一列，於是其中一個被記進失敗記憶時，另一個也跟著被跳過，
      最長 7 天不會被自動整理，而使用者看不出為什麼。這也違反 CD-144-8 明文的
      「以 `to_file_uri(fs_path, path_mappings)` 正規化後存」——大寫化不是正規化。
    """
    return key.upper() if reason == "not_found" else key


def should_skip(
    reason: str,
    key: str,
    now: Optional[float] = None,
    db_path: Optional[Path] = None,
) -> bool:
    now = now if now is not None else _now()
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT attempt_count, last_failed_at FROM organize_failures "
            "WHERE reason = ? AND key = ?",
            (reason, _normalize_key(reason, key)),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        attempt_count, last_failed_at = row[0], row[1]
        window = 86400 if attempt_count <= 1 else 7 * 86400
        return (now - last_failed_at) < window


def record_failure(
    reason: str,
    key: str,
    number: str,
    duplicate_target: str = "",
    now: Optional[float] = None,
    db_path: Optional[Path] = None,
) -> None:
    now = now if now is not None else _now()
    with closing(get_connection(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO organize_failures (
                key, reason, number, duplicate_target, attempt_count, last_failed_at
            ) VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(key) DO UPDATE SET
                reason = excluded.reason,
                number = excluded.number,
                attempt_count = attempt_count + 1,
                last_failed_at = excluded.last_failed_at,
                duplicate_target = excluded.duplicate_target
            """,
            (_normalize_key(reason, key), reason, number, duplicate_target, now),
        )
        conn.commit()


def clear_on_success(
    number: str,
    now: Optional[float] = None,
    db_path: Optional[Path] = None,
) -> None:
    now = now if now is not None else _now()
    with closing(get_connection(db_path)) as conn:
        conn.execute(
            "DELETE FROM organize_failures WHERE reason='not_found' AND key = ?",
            (_normalize_key("not_found", number),),
        )
        conn.commit()


def duplicate_key(fs_path: str, path_mappings: dict) -> str:
    return to_file_uri(fs_path, path_mappings)


def get_duplicate_target(key: str, db_path: Optional[Path] = None) -> str:
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT duplicate_target FROM organize_failures WHERE reason = 'duplicate' AND key = ?",
            (_normalize_key("duplicate", key),),
        )
        row = cursor.fetchone()
        if row is None or not row[0]:
            return ""
        return str(row[0])
