"""core.database.tag_alias — TagAliasRecord 與 TagAliasRepository（Tag 別名，spec-87 子模組）。"""
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, List
from datetime import datetime

from ._alias_base import _AliasRepositoryBase


@dataclass
class TagAliasRecord:
    """Tag 別名資料模型（平坦 group schema，鏡射 AliasRecord）"""
    primary_name: str = ""
    aliases: List[str] = field(default_factory=list)  # JSON array
    source: str = "manual"  # 'manual' | 'auto'
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """轉為字典（JSON 欄位序列化）"""
        data = asdict(self)
        data["aliases"] = json.dumps(self.aliases, ensure_ascii=False)
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        if self.updated_at:
            data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_row(cls, row: tuple, columns: List[str]) -> "TagAliasRecord":
        """從資料庫 row 建立"""
        data = dict(zip(columns, row, strict=True))
        if "aliases" in data and data["aliases"]:
            try:
                data["aliases"] = json.loads(data["aliases"])
            except json.JSONDecodeError:
                data["aliases"] = []
        else:
            data["aliases"] = []
        if "created_at" in data and data["created_at"]:
            if isinstance(data["created_at"], str):
                data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data and data["updated_at"]:
            if isinstance(data["updated_at"], str):
                data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)


class TagAliasRepository(_AliasRepositoryBase[TagAliasRecord]):
    """Tag 別名資料存取層（平坦 group schema，鏡射 AliasRepository）。

    uniqueness 只查本表 tag_aliases，不跨查 actress_aliases（CD-58-3，由 `_table` 結構性保證）。
    """

    _table = "tag_aliases"
    _sql_alias = "ta"
    _record_cls = TagAliasRecord
