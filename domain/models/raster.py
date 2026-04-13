"""Modelo de configuracao de camadas raster (tiles XYZ).

Hierarquia: RasterHierarchy > DateGroup > BandGroup > RasterLayerConfig
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class VisParams:
    """Parametros de visualizacao para tiles XYZ do jobs-server."""
    band: str = "original"
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    gamma: Optional[float] = None
    palette: Optional[str] = None
    gain: Optional[float] = None
    bias: Optional[float] = None


@dataclass
class RasterLayerConfig:
    """Configuracao de uma camada raster XYZ para carregamento no QGIS."""
    name: str              # nome de exibicao (ex: "24MXT_52")
    xyz_url: str           # URL XYZ completa (com params atuais)
    layer_type: str        # RGB | NDVI | NDWI | ALBEDO | DIF_IMG
    tile: str = ""         # identificador da cena (ex: "24MXT_52")
    image_id: str = ""     # ID da imagem Sentinel-2 (para reconstruir URL)
    vis_params: VisParams = field(default_factory=VisParams)
    is_visible: bool = True


@dataclass
class BandGroup:
    """Agrupamento de camadas por banda/indice espectral."""
    band_name: str                      # "Classificacao", "RGB", "NDVI", etc.
    band_key: str                       # "original", "NDVI", "NDWI", "albedo"
    layers: List[RasterLayerConfig] = field(default_factory=list)


@dataclass
class DateGroup:
    """Agrupamento de bandas por data de aquisicao."""
    date_label: str                     # "22/10/2025"
    date_iso: str                       # ISO para ordenacao
    bands: List[BandGroup] = field(default_factory=list)


@dataclass
class RasterHierarchy:
    """Hierarquia completa de camadas raster: Datas > Bandas > Cenas."""
    dates: List[DateGroup] = field(default_factory=list)
