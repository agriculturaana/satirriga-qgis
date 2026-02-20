"""Modelos para resolucao de conflitos de upload zonal."""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class ConflictItem:
    feature_hash: str
    conflict_type: str
    mine: Optional[dict] = None
    theirs: Optional[dict] = None
    suggested: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "ConflictItem":
        return cls(
            feature_hash=data.get("featureHash", ""),
            conflict_type=data.get("conflictType", ""),
            mine=data.get("mine"),
            theirs=data.get("theirs"),
            suggested=data.get("suggested"),
        )


@dataclass
class ConflictSet:
    conflict_id: int
    base_version: int
    current_version: int
    items: List[ConflictItem] = field(default_factory=list)
    expires_at: Optional[str] = None
    status: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ConflictSet":
        items_raw = data.get("items") or []
        items = [ConflictItem.from_dict(item) for item in items_raw]
        return cls(
            conflict_id=data.get("conflictId", 0),
            base_version=data.get("baseVersion", 0),
            current_version=data.get("currentVersion", 0),
            items=items,
            expires_at=data.get("expiresAt"),
            status=data.get("status", ""),
        )
