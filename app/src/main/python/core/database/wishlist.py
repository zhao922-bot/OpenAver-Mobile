"""core.database.wishlist — WishlistRepository（書籤資料存取層，spec-140 子模組）。"""
import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Any

from core.logger import get_logger
from core.scraper import normalize_number

from . import connection

logger = get_logger(__name__)

_LIST_COLUMNS = {"actresses", "tags", "sample_images", "preview_sample_images"}


class WishlistRepository:
    """書籤資料存取層"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or connection.get_db_path()

    def _get_connection(self) -> sqlite3.Connection:
        """取得資料庫連線"""
        return connection.get_connection(self.db_path)

    def add(self, number: str, **fields: Any) -> bool:
        """新增書籤（防禦性正規化；若已存在則忽略）。

        Returns:
            bool: 成功插入新列回傳 True；重複加入（已存在）回傳 False。
        """
        number = normalize_number(number)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            title = fields.get("title", "") or ""
            maker = fields.get("maker", "") or ""
            director = fields.get("director", "") or ""
            series = fields.get("series", "") or ""
            label = fields.get("label", "") or ""
            duration = fields.get("duration")
            release_date = fields.get("release_date", "") or ""
            cover_path = fields.get("cover_path", "") or ""
            source = fields.get("source", "") or ""
            source_url = fields.get("source_url", "") or ""

            # 序列化 4 個 list 欄位
            list_values: dict[str, str] = {}
            for col in ("actresses", "tags", "sample_images", "preview_sample_images"):
                val = fields.get(col)
                if isinstance(val, (list, tuple)):
                    list_values[col] = json.dumps(val, ensure_ascii=False)
                elif isinstance(val, str):
                    list_values[col] = val
                else:
                    list_values[col] = "[]"

            cursor.execute(
                """
                INSERT OR IGNORE INTO wishlist (
                    number, title, actresses, tags, maker, director, series, label,
                    duration, release_date, cover_path, sample_images,
                    preview_sample_images, source, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    number,
                    title,
                    list_values["actresses"],
                    list_values["tags"],
                    maker,
                    director,
                    series,
                    label,
                    duration,
                    release_date,
                    cover_path,
                    list_values["sample_images"],
                    list_values["preview_sample_images"],
                    source,
                    source_url,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def remove(self, number: str) -> bool:
        """根據番號移除書籤（防禦性正規化）。

        Returns:
            bool: 成功刪除回傳 True；不存在回傳 False。
        """
        number = normalize_number(number)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM wishlist WHERE number = ?", (number,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def list_all(self) -> List[dict]:
        """列出所有書籤，依 created_at 降序排列。

        Returns:
            list[dict]: 書籤字典清單，4 個 list 欄位已還原為 Python list。
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM wishlist ORDER BY created_at DESC")
            if not cursor.description:
                return []
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(zip(columns, row, strict=True))
                for col in _LIST_COLUMNS:
                    val = item.get(col)
                    if not val:
                        item[col] = []
                    elif isinstance(val, str):
                        try:
                            parsed = json.loads(val)
                            item[col] = parsed if isinstance(parsed, list) else []
                        except (json.JSONDecodeError, TypeError):
                            item[col] = []
                    elif isinstance(val, list):
                        item[col] = val
                    else:
                        item[col] = []
                results.append(item)
            return results
        finally:
            conn.close()

    def count(self) -> int:
        """取得書籤總筆數。"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM wishlist")
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def delete_many(self, numbers: List[str]) -> int:
        """批次刪除書籤（防禦性正規化）。

        Returns:
            int: 實際刪除的筆數。
        """
        if not numbers:
            return 0

        normalized = [normalize_number(n) for n in numbers]
        placeholders = ", ".join(["?"] * len(normalized))
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"DELETE FROM wishlist WHERE number IN ({placeholders})",
                normalized,
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
