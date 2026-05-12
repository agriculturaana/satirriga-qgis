"""Servico de inspecao pontual de indices espectrais.

Encapsula a chamada POST /api/mapeamento/tiles/get/indexs/images com
cache LRU em memoria por (lat, lon, image_ids).

A API roteia o request para o jobs-server upstream que calcula os
indices (NDVI, NDWI, EVI, SAVI, MNDWI, Albedo) sobre o pixel solicitado.
Tiles XYZ servidos ao QGIS sao apenas RGBA visual — nao trazem o
valor numerico, por isso a consulta vai ao backend (mesmo padrao do
client web Angular: layer-indexes-panel).
"""

import json
from collections import OrderedDict
from typing import List, Optional

from ..models.pixel_indexes import SceneIndexes, parse_scene_list


_ENDPOINT_PATH = "/mapeamento/tiles/get/indexs/images"
_CACHE_MAX = 64
_COORD_PRECISION = 6  # decimais de lat/lon usados como chave de cache


class TileIndexesService:
    """Cliente assincrono para consulta de indices espectrais por ponto."""

    def __init__(self, http_client, config_repo):
        self._http = http_client
        self._config = config_repo
        self._cache: "OrderedDict[tuple, List[SceneIndexes]]" = OrderedDict()

    def request(self, image_ids: List[str], lat: float, lon: float) -> str:
        """Dispara POST. Retorna request_id do HttpClient.

        Pre-condicao: caller deve ter checado cache via cached_for().
        """
        url = self._build_url()
        payload = json.dumps({
            "id_imagens": list(image_ids),
            "lat": lat,
            "lon": lon,
        }).encode("utf-8")
        return self._http.post_json(url, payload)

    def parse_response(self, body: bytes) -> List[SceneIndexes]:
        """Decodifica body do HTTP em lista de SceneIndexes."""
        if not body:
            return []
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            return []
        return parse_scene_list(data)

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def cached_for(self, image_ids: List[str], lat: float,
                   lon: float) -> Optional[List[SceneIndexes]]:
        """Retorna resultado do cache se houver hit."""
        key = self._cache_key(image_ids, lat, lon)
        if key not in self._cache:
            return None
        # Move para o final (LRU)
        value = self._cache.pop(key)
        self._cache[key] = value
        return value

    def store(self, image_ids: List[str], lat: float, lon: float,
              scenes: List[SceneIndexes]):
        """Insere resultado no cache LRU."""
        key = self._cache_key(image_ids, lat, lon)
        self._cache[key] = scenes
        while len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)

    def clear_cache(self):
        self._cache.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_url(self) -> str:
        base = (self._config.get("api_base_url") or "").rstrip("/")
        return f"{base}{_ENDPOINT_PATH}"

    @staticmethod
    def _cache_key(image_ids, lat, lon) -> tuple:
        ids = tuple(sorted(str(i) for i in image_ids))
        return (
            round(float(lat), _COORD_PRECISION),
            round(float(lon), _COORD_PRECISION),
            ids,
        )
