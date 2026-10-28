"""core.database.notifications — 通知中心持久化資料庫操作（spec-144 T1）。

提供模組層級函式，使用 contextlib.closing(get_connection(db_path)) 管理連線。
"""
from contextlib import closing
from pathlib import Path
from typing import Optional

from .connection import get_connection


def insert_notification(row: dict, db_path: Optional[Path] = None) -> None:
    """插入一筆通知，並修剪 notifications 表至最新 50 筆。"""
    with closing(get_connection(db_path)) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO notifications (
                id, timestamp, level, title_key, message, task_type, is_read, url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                float(row["timestamp"]),
                row["level"],
                row["title_key"],
                row.get("message") or "",
                row.get("task_type"),
                1 if row.get("is_read") else 0,
                row.get("url"),
            ),
        )
        # `rowid DESC` 是承重的，不是裝飾（PR review 實測復現）：`timestamp` 是 REAL，
        # 只用 `ORDER BY timestamp DESC` 在**並列**時排序不穩定——55 筆 timestamp 相同的列，
        # SQLite 會留下最先插入的 50 筆，剛寫進去的那筆在**它自己這次 insert 之後立刻被刪掉**，
        # 與「保留最新 50 筆」的意圖完全相反。`rowid` 隨插入單調遞增，並列時用它決勝。
        conn.execute(
            "DELETE FROM notifications WHERE id NOT IN ("
            "SELECT id FROM notifications ORDER BY timestamp DESC, rowid DESC LIMIT 50)"
        )
        conn.commit()


def mark_notifications_read(ids: list[str], db_path: Optional[Path] = None) -> None:
    """將指定 ID 的通知標記為已讀。"""
    if not ids:
        return
    with closing(get_connection(db_path)) as conn:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE notifications SET is_read = 1 WHERE id IN ({placeholders})",
            tuple(ids),
        )
        conn.commit()


def clear_all_notifications(db_path: Optional[Path] = None) -> None:
    """清空 notifications 表所有資料。"""
    with closing(get_connection(db_path)) as conn:
        conn.execute("DELETE FROM notifications")
        conn.commit()


def load_recent_notifications(limit: int = 50, db_path: Optional[Path] = None) -> list[dict]:
    """載入最近的通知（依時間戳降冪排序，最新在前）。"""
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, timestamp, level, title_key, message, task_type, is_read, url
            FROM notifications
            ORDER BY timestamp DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "level": r[2],
                "title_key": r[3],
                "message": r[4],
                "task_type": r[5],
                "is_read": bool(r[6]),
                "url": r[7] or None,
            }
            for r in rows
        ]
