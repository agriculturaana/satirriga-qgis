"""Servico de raster — constroi configuracoes de camadas XYZ a partir da API tilesMetodos.

A API tilesMetodos retorna TileData[] (array). Cada item:
{
    url: "https://...",  # RGB base
    metodo1_response: { url_indices: { class_irri, NDVI, NDWI, albedo } },
    metodo2_discreto_response: { url_indices: { ... } },
    metodo2_fuzzy_response: { url_indices: { ... } },
    metodo3_response: { url_indices: { ... } },
}
"""

from typing import List

from ..models.raster import RasterLayerConfig


# Mapeamento metodoApply -> chave da resposta no TileData
_METODO_RESPONSE_KEYS = {
    "METODO_1": "metodo1_response",
    "METODO_2_DISCRETO": "metodo2_discreto_response",
    "METODO_2_FUZZY": "metodo2_fuzzy_response",
    "METODO_3": "metodo3_response",
}


def build_raster_configs(tile_data, metodo_apply: str) -> List[RasterLayerConfig]:
    """Constroi lista de RasterLayerConfig a partir da resposta de tilesMetodos.

    Args:
        tile_data: JSON da resposta de GET /api/mapeamento/tilesMetodos.
                   Pode ser list (TileData[]) ou dict (TileData unico).
        metodo_apply: Chave do metodo (ex: METODO_1, METODO_2_DISCRETO)

    Returns:
        Lista de RasterLayerConfig para carregamento no QGIS.
    """
    # Normaliza: resposta e array, usa primeiro item
    if isinstance(tile_data, list):
        if not tile_data:
            return []
        tile_data = tile_data[0]

    if not isinstance(tile_data, dict):
        return []

    configs = []

    # RGB base — sempre presente em tile_data["url"]
    rgb_url = tile_data.get("url")
    if rgb_url:
        configs.append(RasterLayerConfig(
            name="RGB",
            xyz_url=rgb_url,
            layer_type="RGB",
            is_visible=True,
        ))

    # Dados do metodo especifico
    response_key = _METODO_RESPONSE_KEYS.get(metodo_apply)
    if not response_key:
        return configs

    metodo_response = tile_data.get(response_key)
    if not metodo_response:
        return configs

    # url_indices contem as URLs dos indices espectrais
    url_indices = metodo_response.get("url_indices") or {}

    # Indices espectrais (chaves da API: NDVI, NDWI, albedo — case-sensitive)
    _add_index_config(configs, url_indices, "albedo", "Albedo", "ALBEDO")
    _add_index_config(configs, url_indices, "NDWI", "NDWI", "NDWI")
    _add_index_config(configs, url_indices, "NDVI", "NDVI", "NDVI")

    # Classificacao de irrigacao
    class_url = url_indices.get("class_irri")
    if class_url:
        configs.append(RasterLayerConfig(
            name="Classificação",
            xyz_url=class_url,
            layer_type="CLASS_IRRI",
            is_visible=True,
        ))

    # difImg (metodos 2a/2b) — stub: chave ainda nao implementada no jobs-server
    if metodo_apply in ("METODO_2_DISCRETO", "METODO_2_FUZZY"):
        dif_url = url_indices.get("dif_img") or url_indices.get("difImg")
        if dif_url:
            configs.append(RasterLayerConfig(
                name="Diferença Temporal",
                xyz_url=dif_url,
                layer_type="DIF_IMG",
                is_visible=True,
            ))

    return configs


def _add_index_config(
    configs: List[RasterLayerConfig],
    url_indices: dict,
    key: str,
    name: str,
    layer_type: str,
):
    """Adiciona config de indice espectral se URL presente."""
    url = url_indices.get(key)
    if url:
        configs.append(RasterLayerConfig(
            name=name,
            xyz_url=url,
            layer_type=layer_type,
            is_visible=False,  # Indices invisiveis por padrao
        ))
