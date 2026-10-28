"""core.database.maker_javbus_map — 片商 → JavBus 作品頁代號對應記錄（173-T2，CD-173-5）。

三態：有列 `found`、有列 `not_found`、沒有列（＝沒查過）。
寫入單調（I-M1）：`found` 可覆蓋任何狀態；`not_found` 絕不覆蓋既有的列。
`maker_key` 對本模組是不透明字串，不做任何正規化。無 TTL、無刪除。
"""
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

from .connection import get_connection


def get_mapping(key: str, db_path: Optional[Path] = None) -> Optional[dict]:
    with closing(get_connection(db_path)) as conn:
        row = conn.execute(
            "SELECT status, kind, studio_id, label, checked_at "
            "FROM maker_javbus_map WHERE maker_key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    return {
        "status": row[0],
        "kind": row[1],
        "studio_id": row[2],
        "label": row[3],
        "checked_at": row[4],
    }


def record_found(
    key: str, kind: str, studio_id: str, label: str, db_path: Optional[Path] = None
) -> None:
    with closing(get_connection(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO maker_javbus_map (maker_key, status, kind, studio_id, label, checked_at)
            VALUES (?, 'found', ?, ?, ?, ?)
            ON CONFLICT(maker_key) DO UPDATE SET
                status = excluded.status,
                kind = excluded.kind,
                studio_id = excluded.studio_id,
                label = excluded.label,
                checked_at = excluded.checked_at
            """,
            (key, kind, studio_id, label, time.time()),
        )
        conn.commit()


def record_not_found(key: str, label: str, db_path: Optional[Path] = None) -> None:
    with closing(get_connection(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO maker_javbus_map (maker_key, status, kind, studio_id, label, checked_at)
            VALUES (?, 'not_found', '', '', ?, ?)
            ON CONFLICT(maker_key) DO NOTHING
            """,
            (key, label, time.time()),
        )
        conn.commit()


def list_not_found_keys(db_path: Optional[Path] = None) -> list:
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute("SELECT maker_key FROM maker_javbus_map WHERE status = 'not_found'").fetchall()
    return [r[0] for r in rows]
