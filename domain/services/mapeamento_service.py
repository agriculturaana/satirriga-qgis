"""Parsers e regras de negocio para mapeamentos — camada Domain pura."""

from typing import Optional

from ..models.mapeamento import Mapeamento, PaginatedResult
from ..models.metodo import Metodo
from ..models.enums import JobStatusEnum


_METODO_LABELS = {
    "METODO_1": "Fatiamento do índice de Vegetação",
    "METODO_2_DISCRETO": "Detecção de mudança (discreto)",
    "METODO_2_FUZZY": "Detecção de mudança (fuzzy)",
    "METODO_3": "Método 3",
    "AUTOMATICO": "Automático",
}


def format_metodo_label(metodo_apply: Optional[str]) -> str:
    """Converte metodoApply (chave da API) em label legivel para a UI."""
    if not metodo_apply:
        return "—"
    return _METODO_LABELS.get(metodo_apply, metodo_apply)


def parse_mapeamento(data: dict) -> Mapeamento:
    return Mapeamento.from_dict(data)


def parse_paginated_result(data: dict) -> PaginatedResult:
    return PaginatedResult.from_dict(data)


def parse_metodo(data: dict) -> Metodo:
    return Metodo.from_dict(data)


def has_downloadable_metodo(mapeamento: Mapeamento) -> bool:
    """Verifica se o mapeamento possui ao menos um metodo com status DONE."""
    return any(
        m.status == JobStatusEnum.DONE
        for m in mapeamento.metodos
    )


def has_processing_metodo(mapeamento: Mapeamento) -> bool:
    """Verifica se o mapeamento possui metodos ainda em processamento."""
    return any(
        m.status == JobStatusEnum.PROCESSING
        for m in mapeamento.metodos
    )
