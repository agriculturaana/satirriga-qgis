import re
from dataclasses import dataclass, field
from typing import List, Optional


def _strip_html(text: str) -> str:
    """Remove tags HTML e decodifica entidades comuns."""
    if not text:
        return text
    clean = re.sub(r"<[^>]+>", "", text)
    clean = clean.replace("&nbsp;", " ").replace("&amp;", "&")
    clean = clean.replace("&lt;", "<").replace("&gt;", ">")
    return clean.strip()


def _format_date(iso_str: str) -> str:
    """Converte ISO datetime para dd/mm/yyyy."""
    if not iso_str:
        return ""
    try:
        date_part = iso_str[:10]  # '2025-09-30'
        parts = date_part.split("-")
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    except (IndexError, ValueError):
        pass
    return iso_str


@dataclass
class Mapeamento:
    id: int
    descricao: str
    data_referencia: str
    status: str
    satelite: Optional[str] = None
    regiao: Optional[str] = None
    area_total_ha: Optional[float] = None
    percent_nuvem: Optional[int] = None
    can_homologar: Optional[bool] = None
    mascara_id: Optional[int] = None
    user_name: Optional[str] = None
    metodos: List["Metodo"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Mapeamento":
        from .metodo import Metodo
        metodos_raw = data.get("metodos") or data.get("metodoMapeamentos") or []
        metodos = [Metodo.from_dict(m) for m in metodos_raw]

        # Descrição pode conter HTML
        descricao = _strip_html(data.get("descricao", ""))

        # Data pode ser ISO datetime
        data_ref = _format_date(data.get("dataReferencia", ""))

        # User pode ser objeto aninhado
        user_obj = data.get("user")
        user_name = user_obj.get("name") if isinstance(user_obj, dict) else None

        return cls(
            id=data.get("id", 0),
            descricao=descricao,
            data_referencia=data_ref,
            status=data.get("status", ""),
            satelite=data.get("satelite"),
            regiao=data.get("regiao"),
            area_total_ha=data.get("areaTotalHa"),
            percent_nuvem=data.get("percentNuvem"),
            can_homologar=data.get("canHomologar"),
            mascara_id=data.get("mascaraId"),
            user_name=user_name,
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
        # API retorna items em "data" (ou "content" como fallback)
        items_raw = data.get("data") or data.get("content") or []
        content = [Mapeamento.from_dict(m) for m in items_raw]

        # Paginação pode estar em "pagination" (aninhado) ou no root
        pagination = data.get("pagination", data)

        # pagination.page da API e 1-indexed; normaliza para 0-indexed
        raw_page = pagination.get("page", data.get("number", 0))
        if "pagination" in data:
            raw_page = max(raw_page - 1, 0)

        return cls(
            content=content,
            page=raw_page,
            size=pagination.get("size", 15),
            total_elements=pagination.get("total", data.get("totalElements", 0)),
            total_pages=pagination.get("totalPages", 0),
        )
