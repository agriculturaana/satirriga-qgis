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

    def request(self, image_ids: List[str], lat: float, lon: float,
                image_ids2: Optional[List[str]] = None) -> str:
        """Dispara POST. Retorna request_id do HttpClient.

        Pre-condicao: caller deve ter checado cache via cached_for().

        ``image_ids2`` e uma lista paralela posicional a ``image_ids`` com o
        id da imagem anterior pareada de cada cena ("" = sem comparacao) —
        habilita o calculo de delta_ndvi no backend (metodos 2a/2b). O campo
        so entra no payload quando ha ao menos uma posicao preenchida.
        """
        url = self._build_url()
        body = {
            "id_imagens": list(image_ids),
            "lat": lat,
            "lon": lon,
        }
        if image_ids2 and any(image_ids2):
            body["id_imagens2"] = list(image_ids2)
        payload = json.dumps(body).encode("utf-8")
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
                   lon: float,
                   image_ids2: Optional[List[str]] = None
                   ) -> Optional[List[SceneIndexes]]:
        """Retorna resultado do cache se houver hit."""
        key = self._cache_key(image_ids, lat, lon, image_ids2)
        if key not in self._cache:
            return None
        # Move para o final (LRU)
        value = self._cache.pop(key)
        self._cache[key] = value
        return value

    def store(self, image_ids: List[str], lat: float, lon: float,
              scenes: List[SceneIndexes],
              image_ids2: Optional[List[str]] = None):
        """Insere resultado no cache LRU."""
        key = self._cache_key(image_ids, lat, lon, image_ids2)
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
    def _cache_key(image_ids, lat, lon, image_ids2=None) -> tuple:
        # Chave por PARES (id, id2) ordenados: continua insensivel a ordem da
        # lista, mas distingue pareamentos diferentes (delta_ndvi depende da
        # imagem2 associada a cada cena).
        ids2 = list(image_ids2 or [])
        pairs = tuple(sorted(
            (str(img), str(ids2[i]) if i < len(ids2) else "")
            for i, img in enumerate(image_ids)
        ))
        return (
            round(float(lat), _COORD_PRECISION),
            round(float(lon), _COORD_PRECISION),
            pairs,
        )
