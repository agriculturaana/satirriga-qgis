"""Modelo para status de batch de upload zonal."""

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
