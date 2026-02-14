from dataclasses import dataclass, field
from typing import List, Optional, Generic, TypeVar

T = TypeVar("T")


@dataclass
class Mapeamento:
    id: int
    descricao: str
    data_referencia: str
    status: str
    satelite: Optional[str] = None
    regiao: Optional[str] = None
    area_total_ha: Optional[float] = None
    metodos: List["Metodo"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Mapeamento":
        from .metodo import Metodo
        metodos_raw = data.get("metodos") or data.get("metodoMapeamentos") or []
        metodos = [Metodo.from_dict(m) for m in metodos_raw]
        return cls(
            id=data.get("id", 0),
            descricao=data.get("descricao", ""),
            data_referencia=data.get("dataReferencia", ""),
            status=data.get("status", ""),
            satelite=data.get("satelite"),
            regiao=data.get("regiao"),
            area_total_ha=data.get("areaTotalHa"),
            metodos=metodos,
        )


@dataclass
class PaginatedResult:
    content: List[Mapeamento]
    page: int
    size: int
    total_elements: int
    total_pages: int

    @classmethod
    def from_dict(cls, data: dict) -> "PaginatedResult":
        content = [Mapeamento.from_dict(m) for m in data.get("content", [])]
        return cls(
            content=content,
            page=data.get("number", data.get("page", 0)),
            size=data.get("size", 15),
            total_elements=data.get("totalElements", 0),
            total_pages=data.get("totalPages", 0),
        )
