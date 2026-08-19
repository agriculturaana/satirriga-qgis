"""Modelos de dominio para inspecao pontual de indices espectrais."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SceneIndexes:
    """Valores espectrais em um ponto para uma cena (id_imagem)."""
    id_imagem: str
    tile: str
    data_formatada: str
    ndvi: Optional[float] = None
    savi: Optional[float] = None
    evi: Optional[float] = None
    ndwi: Optional[float] = None
    mndwi: Optional[float] = None
    albedo: Optional[float] = None
    # Diferenca de NDVI em relacao a imagem anterior pareada (metodos de
    # deteccao de mudanca 2a/2b). Calculada pelo backend quando o request
    # informa id_imagens2; None quando nao ha comparacao.
    delta_ndvi: Optional[float] = None

    @classmethod
    def from_dict(cls, data: dict) -> "SceneIndexes":
        return cls(
            id_imagem=str(data.get("id_imagem") or ""),
            tile=str(data.get("tile") or ""),
            data_formatada=str(
                data.get("data_formatada") or data.get("data") or ""
            ),
            ndvi=_to_float(data.get("ndvi")),
            savi=_to_float(data.get("savi")),
            evi=_to_float(data.get("evi")),
            ndwi=_to_float(data.get("ndwi")),
            mndwi=_to_float(data.get("mndwi")),
            albedo=_to_float(data.get("albedo")),
            delta_ndvi=_to_float(data.get("delta_ndvi")),
        )

    @property
    def has_coverage(self) -> bool:
        """False quando todos os indices vieram nulos — em mapeamentos
        multi-tile isso significa que o footprint da cena nao cobre o
        ponto clicado (o Earth Engine retorna vazio silenciosamente)."""
        return any(
            v is not None
            for v in (self.ndvi, self.savi, self.evi,
                      self.ndwi, self.mndwi, self.albedo)
        )

    def display_label(self) -> str:
        """Texto curto para dropdown: 'DD/MM/YYYY - tile'."""
        parts = [p for p in (self.data_formatada, self.tile) if p]
        label = " - ".join(parts) or self.id_imagem
        if not self.has_coverage:
            label += " — sem cobertura no ponto"
        return label


def parse_scene_list(payload) -> List[SceneIndexes]:
    """Converte resposta da API (lista de dicts) em List[SceneIndexes]."""
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []
    return [SceneIndexes.from_dict(item) for item in payload if isinstance(item, dict)]


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f
