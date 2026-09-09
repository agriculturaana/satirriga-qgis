"""Retorno do upload zonal: rejeições registradas pelo servidor e desfecho
do reprocessamento (overlay e estatísticas zonais)."""

from dataclasses import dataclass, field
from typing import Optional

from ..models.enums import ZonalStatusEnum

REJECTION_LABELS = {
    "SLIVER": "área menor que 900 m²",
    "DUPLICATE_FEATURE": "cópia idêntica de feição já enviada",
    "STALE_DELETED": "feição removida no servidor em versão posterior",
    "UNKNOWN_ORIGINAL_FID": "identificador de origem desconhecido",
    "INVALID_TOPOLOGY": "geometria inválida",
    "INVALID_GEOMETRY_TYPE": "tipo de geometria não suportado",
    "NULL_GEOMETRY": "sem geometria",
}

# Rejeições em que a feição deixa de existir no servidor. Nas demais, quando a
# feição já existia, o servidor mantém a versão anterior.
DISCARDING_TYPES = {"STALE_DELETED", "UNKNOWN_ORIGINAL_FID"}

INTERMEDIATE_ZONAL_STATUSES = {"PROCESSING", "OVERLAID", "CREATED", "CONSOLIDATING"}
SUCCESS_ZONAL_STATUSES = {"CONSOLIDATED", "DONE", "AGUARDANDO"}


@dataclass
class RejectedFeature:
    original_fid: Optional[int]
    reasons: list
    kept_previous: bool
    sync_status: Optional[str] = None

    def describe(self) -> str:
        alvo = f"Feição {self.original_fid}" if self.original_fid else "Feição nova"
        desfecho = "versão anterior mantida" if self.kept_previous else "descartada"
        return f"{alvo}: {'; '.join(self.reasons)} ({desfecho})"


def _reason_label(error: dict) -> str:
    tipo = str(error.get("type", "")) if isinstance(error, dict) else str(error)
    return REJECTION_LABELS.get(tipo, tipo)


def parse_rejections(error_log) -> list:
    """Extrai as feições rejeitadas de ``errorLog`` (dict com ``rejeitadas``)."""
    if not isinstance(error_log, dict):
        return []
    result = []
    for item in error_log.get("rejeitadas") or []:
        if not isinstance(item, dict):
            continue
        errors = item.get("errors") or []
        types = {str(e.get("type", "")) for e in errors if isinstance(e, dict)}
        fid = item.get("originalFid")
        result.append(RejectedFeature(
            original_fid=int(fid) if fid else None,
            reasons=[_reason_label(e) for e in errors] or ["motivo não informado"],
            kept_previous=bool(fid) and not (types & DISCARDING_TYPES),
            sync_status=item.get("syncStatus"),
        ))
    return result


@dataclass
class BatchSummary:
    feature_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    accepted_count: int = 0
    modified_count: int = 0
    new_count: int = 0
    deleted_count: int = 0
    kept_count: int = 0
    rejected: list = field(default_factory=list)

    def detail_text(self) -> str:
        parts = []
        if self.feature_count:
            parts.append(f"Features: {self.feature_count}")
        if self.accepted_count:
            parts.append(f"Aceitas: {self.accepted_count}")
        if self.modified_count:
            parts.append(f"Modificadas: {self.modified_count}")
        if self.new_count:
            parts.append(f"Novas: {self.new_count}")
        if self.deleted_count:
            parts.append(f"Removidas: {self.deleted_count}")
        if self.invalid_count:
            parts.append(f"Inválidas: {self.invalid_count}")
        if self.rejected:
            parts.append(f"Rejeitadas: {len(self.rejected)}")
        return " | ".join(parts)

    def rejection_text(self) -> str:
        return "\n".join(r.describe() for r in self.rejected)


def summarize_batch(status_data: dict) -> BatchSummary:
    error_log = status_data.get("errorLog")
    kept = error_log.get("mantidas", 0) if isinstance(error_log, dict) else 0
    return BatchSummary(
        feature_count=status_data.get("featureCount") or 0,
        valid_count=status_data.get("validCount") or 0,
        invalid_count=status_data.get("invalidCount") or 0,
        accepted_count=status_data.get("acceptedCount") or 0,
        modified_count=status_data.get("modifiedCount") or 0,
        new_count=status_data.get("newCount") or 0,
        deleted_count=status_data.get("deletedCount") or 0,
        kept_count=kept or 0,
        rejected=parse_rejections(error_log),
    )


@dataclass
class ReprocessingOutcome:
    ok: bool
    status: str
    label: str
    color: str
    message: str


def is_terminal_zonal_status(status) -> bool:
    return bool(status) and status not in INTERMEDIATE_ZONAL_STATUSES


def reprocessing_outcome(status, last_error: Optional[str], pending_geoids: int = 0) -> ReprocessingOutcome:
    """Traduz o status final do zonal após o upload em rótulo, cor e mensagem."""
    if not status:
        return ReprocessingOutcome(True, "", "Concluído", "#4CAF50",
                                   "Upload e reprocessamento finalizados")
    try:
        enum = ZonalStatusEnum(status)
        label, color = enum.label, enum.color
    except ValueError:
        label, color = str(status), "#9E9E9E"

    ok = status in SUCCESS_ZONAL_STATUSES
    if ok:
        message = "Overlay e estatísticas zonais recalculados."
    else:
        message = f"{label}."
        if last_error:
            message += f" {last_error}"
        else:
            message += " O servidor não concluiu o recálculo."
        message += " Use 'Reprocessar overlay' na aba Mapeamentos ou contate o suporte."
    if pending_geoids:
        message += f" {pending_geoids} feição(ões) ainda sem identificador."
    return ReprocessingOutcome(ok, status, label, color, message)


def find_duplicate_original_fids(fids) -> dict:
    """Conta ``_original_fid`` repetidos, ignorando nulos e zero."""
    counts = {}
    for fid in fids:
        if not fid:
            continue
        counts[fid] = counts.get(fid, 0) + 1
    return {fid: n for fid, n in counts.items() if n > 1}
