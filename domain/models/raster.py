"""Modelo de configuracao de camadas raster (tiles XYZ)."""

from dataclasses import dataclass


@dataclass
class RasterLayerConfig:
    """Configuracao de uma camada raster XYZ para carregamento no QGIS."""
    name: str         # "RGB", "NDVI", "NDWI", "Albedo", "Classificação"
    xyz_url: str      # URL XYZ completa
    layer_type: str   # RGB | NDVI | NDWI | ALBEDO | CLASS_IRRI | DIF_IMG
    is_visible: bool = True