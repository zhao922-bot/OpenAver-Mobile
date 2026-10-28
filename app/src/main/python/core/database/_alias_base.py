"""core.database._alias_base — `_AliasRepositoryBase`（alias/tag_alias 共用基類，spec-87 子模組）。

收納 `AliasRepository` / `TagAliasRepository` 的 12 個鏡像 method（body 逐字搬移、僅套 3 軸
參數化 `self._table` / `self._sql_alias` / `self._record_cls`），消除鏡像重複碼。
子類各設 `_table` / `_sql_alias` / `_record_cls` 三個 class 屬性。
"""
import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Generic, TypeVar

from . import connection

T = TypeVar("T")


class _AliasRepositoryBase(Generic[T]):
    """alias/tag_alias 共用資料存取基類（平坦 group schema）。

    子類必須設定下列三個 class 屬性：
    - `_table`：實際資料表名（如 ``actress_aliases`` / ``tag_aliases``）
    - `_sql_alias`：json_each 查詢用的 SQL alias token（如 ``aa`` / ``ta``）
    - `_record_cls`：對應的 record dataclass（如 ``AliasRecord`` / ``TagAliasRecord``）
    """

    _table: str
    _sql_alias: str
    _record_cls: type[T]

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or connection.get_db_path()

    def _get_connection(self) -> sqlite3.Connection:
        """取得資料庫連線"""
        return connection.get_connection(self.db_path)

    def _get_columns(self) -> List[str]:
        """取得欄位名稱列表"""
        return ["primary_name", "aliases", "source", "created_at", "updated_at"]

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def get_all(self) -> List[T]:
        """取得所有別名組，依 primary_name 排序"""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT * FROM {self._table} ORDER BY primary_name"
            )
            rows = cursor.fetchall()
            cols = self._get_columns()
            return [self._record_cls.from_row(row, cols) for row in rows]
        finally:
            conn.close()

    def get_by_primary(self, name: str) -> Optional[T]:
        """根據 primary_name 查詢；不存在回傳 None"""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"SELECT * FROM {self._table} WHERE primary_name = ?", (name,)
            )
            row = cursor.fetchone()
            if row:
                return self._record_cls.from_row(row, self._get_columns())
            return None
        finally:
            conn.close()

    def find_by_alias(self, alias: str) -> Optional[T]:
        """在 aliases JSON 陣列中搜尋；不存在回傳 None"""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                f"""SELECT {self._sql_alias}.* FROM {self._table} {self._sql_alias}, json_each({self._sql_alias}.aliases)
                   WHERE json_each.value = ?""",
                (alias,),
            )
            row = cursor.fetchone()
            if row:
                return self._record_cls.from_row(row, self._get_columns())
            return None
        finally:
            conn.close()

    def resolve(self, name: str) -> set:
        """
        解析名稱：
        - primary hit  → {primary_name} ∪ set(aliases)
        - alias hit    → {primary_name} ∪ set(aliases)
        - miss         → {name}
        """
        record = self.get_by_primary(name)
        if record is None:
            record = self.find_by_alias(name)
        if record is None:
            return {name}
        return {record.primary_name} | set(record.aliases)

    # ------------------------------------------------------------------
    # Write methods — all use BEGIN EXCLUSIVE
    # ------------------------------------------------------------------

    def add(
        self,
        primary_name: str,
        aliases: Optional[List[str]] = None,
        source: str = "manual",
    ) -> T:
        """
        新增別名組。

        Raises:
            ValueError: primary_name 已存在（作為 primary 或 alias）
        """
        if aliases is None:
            aliases = []

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN EXCLUSIVE")

            # 全域唯一檢查 primary_name
            ok, msg = self._check_global_uniqueness_cursor(cursor, primary_name)
            if not ok:
                raise ValueError(msg)

            # 全域唯一檢查每個 alias
            for alias in aliases:
                ok, msg = self._check_global_uniqueness_cursor(cursor, alias)
                if not ok:
                    raise ValueError(f"alias '{alias}': {msg}")

            aliases_json = json.dumps(aliases, ensure_ascii=False)
            cursor.execute(
                f"""INSERT INTO {self._table} (primary_name, aliases, source)
                   VALUES (?, ?, ?)""",
                (primary_name, aliases_json, source),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return self.get_by_primary(primary_name)

    def add_alias(self, primary_name: str, alias: str) -> tuple:
        """
        為既有 group 新增一個 alias。

        Returns:
            (True, None)       — 成功
            (False, error_msg) — 衝突
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN EXCLUSIVE")

            # 確認 primary 存在
            cursor.execute(
                f"SELECT aliases FROM {self._table} WHERE primary_name = ?",
                (primary_name,),
            )
            row = cursor.fetchone()
            if row is None:
                return False, f"'{primary_name}' 不存在"

            # 全域唯一檢查（排除自己的 group）
            ok, msg = self._check_global_uniqueness_cursor(
                cursor, alias, exclude_primary=primary_name
            )
            if not ok:
                conn.rollback()
                return False, msg

            current = json.loads(row[0]) if row[0] else []
            if alias not in current:
                current.append(alias)
            cursor.execute(
                f"""UPDATE {self._table}
                   SET aliases = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE primary_name = ?""",
                (json.dumps(current, ensure_ascii=False), primary_name),
            )
            conn.commit()
            return True, None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def remove_alias(self, primary_name: str, alias: str) -> bool:
        """
        從 group 中移除一個 alias。

        Returns:
            True  — 成功移除
            False — alias 不存在
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN EXCLUSIVE")
            cursor.execute(
                f"SELECT aliases FROM {self._table} WHERE primary_name = ?",
                (primary_name,),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            current = json.loads(row[0]) if row[0] else []
            if alias not in current:
                return False
            current.remove(alias)
            cursor.execute(
                f"""UPDATE {self._table}
                   SET aliases = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE primary_name = ?""",
                (json.dumps(current, ensure_ascii=False), primary_name),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete(self, name: str) -> bool:
        """
        刪除 group。name 可為 primary 或 alias（先 resolve 取得 primary）。

        Returns:
            True  — 成功刪除
            False — 不存在
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN EXCLUSIVE")

            # 解析 primary_name
            cursor.execute(
                f"SELECT primary_name FROM {self._table} WHERE primary_name = ?",
                (name,),
            )
            row = cursor.fetchone()
            if row is None:
                # 試 alias
                cursor.execute(
                    f"""SELECT {self._sql_alias}.primary_name FROM {self._table} {self._sql_alias}, json_each({self._sql_alias}.aliases)
                       WHERE json_each.value = ?""",
                    (name,),
                )
                row = cursor.fetchone()
            if row is None:
                return False

            primary = row[0]
            cursor.execute(
                f"DELETE FROM {self._table} WHERE primary_name = ?", (primary,)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Private helper — cursor-based uniqueness check (within transaction)
    # ------------------------------------------------------------------

    def _check_global_uniqueness_cursor(
        self, cursor, name: str, exclude_primary: Optional[str] = None
    ) -> tuple:
        """
        在交易內以既有 cursor 對本表做全域唯一性檢查（primary_name + aliases）。
        """
        # Check primary_name
        cursor.execute(
            f"SELECT primary_name FROM {self._table} WHERE primary_name = ?", (name,)
        )
        row = cursor.fetchone()
        if row and row[0] != exclude_primary:
            return False, f"'{name}' 已是 primary_name"

        # Check aliases (json_each)
        cursor.execute(
            f"""SELECT {self._sql_alias}.primary_name FROM {self._table} {self._sql_alias}, json_each({self._sql_alias}.aliases)
               WHERE json_each.value = ?""",
            (name,),
        )
        row = cursor.fetchone()
        if row and row[0] != exclude_primary:
            return False, f"'{name}' 已經是 '{row[0]}' 的別名"

        return True, None
