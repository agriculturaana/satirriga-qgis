"""Modelos para batch de upload zonal — status em tempo real e histórico."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class UploadBatchStatus:
    batch_uuid: str
    status: str
    progress_pct: int = 0
    feature_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    conflict_count: int = 0
    accepted_count: int = 0
    modified_count: int = 0
    new_count: int = 0
    deleted_count: int = 0
    error_log: Optional[str] = None
    completed_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "UploadBatchStatus":
        return cls(
            batch_uuid=data.get("batchUuid", ""),
            status=data.get("status", ""),
            progress_pct=data.get("progressPct", 0),
            feature_count=data.get("featureCount", 0),
            valid_count=data.get("validCount", 0),
            invalid_count=data.get("invalidCount", 0),
            conflict_count=data.get("conflictCount", 0),
            accepted_count=data.get("acceptedCount", 0),
            modified_count=data.get("modifiedCount", 0),
            new_count=data.get("newCount", 0),
            deleted_count=data.get("deletedCount", 0),
            error_log=data.get("errorLog"),
            completed_at=data.get("completedAt"),
        )


@dataclass
class UploadHistoryItem:
    """Item do histórico de uploads retornado pelo endpoint /upload/history."""
    batch_uuid: str
    status: str
    zonal_id: int = 0
    mapeamento_id: int = 0
    mapeamento_descricao: str = ""
    author: str = ""
    file_name: Optional[str] = None
    file_size_bytes: int = 0
    feature_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    conflict_count: int = 0
    new_count: int = 0
    modified_count: int = 0
    deleted_count: int = 0
    accepted_count: int = 0
    progress_pct: float = 0.0
    error_log: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "UploadHistoryItem":
        user = data.get("user") or {}
        mapeamento = data.get("mapeamento") or {}
        return cls(
            batch_uuid=data.get("batchUuid", ""),
            status=data.get("status", ""),
            zonal_id=data.get("zonalId", 0),
            mapeamento_id=data.get("mapeamentoId", 0),
            mapeamento_descricao=mapeamento.get("descricao", ""),
            author=user.get("name", ""),
            file_name=data.get("fileName"),
            file_size_bytes=data.get("fileSizeBytes", 0),
            feature_count=data.get("featureCount", 0),
            valid_count=data.get("validCount", 0),
            invalid_count=data.get("invalidCount", 0),
            conflict_count=data.get("conflictCount", 0),
            new_count=data.get("newCount", 0),
            modified_count=data.get("modifiedCount", 0),
            deleted_count=data.get("deletedCount", 0),
            accepted_count=data.get("acceptedCount", 0),
            progress_pct=data.get("progressPct", 0.0),
            error_log=data.get("errorLog"),
            created_at=data.get("createdAt"),
            completed_at=data.get("completedAt"),
        )
