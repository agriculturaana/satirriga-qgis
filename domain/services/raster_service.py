"""Servico de raster — constroi hierarquia de camadas XYZ a partir da API tilesMetodos.

A API GET /api/mapeamento/tilesMetodos?jobId= retorna TileData[] (array).
Cada item (PrecipitationImageData):
{
    tile: "T21KYR",                  # ID do tile Sentinel-2
    data: "2025-10-22T00:00:00Z",    # data de aquisicao
    id_imagem: "img-12345",          # ID da imagem (para customizacao)
    url: "https://jobs.snirh.gov.br/tiles/s2/IMG/{z}/{x}/{y}",  # RGB (XYZ)
    metodo1_response:          { url_indices: { classIrri, NDVI, NDWI, albedo } },
    metodo2_discreto_response: { url_indices: { ... } },
    metodo2_fuzzy_response:    { url_indices: { ... } },
    metodo3_response:          { url_indices: { ... } },
    metodo_automatico_response:{ url_indices: { ... } },
}

As URLs em ``url`` e ``url_indices`` sao pre-construidas pelo servidor
(podem incluir tokens/assinaturas) e devem ser usadas diretamente.

Para customizacao de visualizacao, o endpoint direto pode ser usado:
    https://jobs.snirh.gov.br/tiles/s2/{image_id}/{z}/{x}/{y}?band={index}
"""

import re
from collections import defaultdict
from typing import List

from ..models.raster import (
    BandGroup,
    DateGroup,
    RasterHierarchy,
    RasterLayerConfig,
    VisParams,
)


# URL base do servidor de tiles (para customizacao de visualizacao)
_JOBS_BASE = "https://jobs.snirh.gov.br/tiles/s2"

# Chaves de method response no TileData — iteradas em ordem de prioridade
_ALL_METHOD_KEYS = [
    "metodo1_response",
    "metodo2_discreto_response",
    "metodo2_fuzzy_response",
    "metodo3_response",
    "metodo_automatico_response",
]

# Padroes de visualizacao — calibrados com P2/P98 de 48k geometrias zonais
_BAND_DEFAULTS = {
    "original":    VisParams(band="original", min_val=0, max_val=3000, gamma=1.2),
    "NDVI":        VisParams(band="NDVI", min_val=0, max_val=0.8, palette="RDYLGN"),
    "NDWI":        VisParams(band="NDWI", min_val=-0.7, max_val=0.4, palette="BLUES"),
    "albedo":      VisParams(band="albedo", min_val=-0.7, max_val=0.4, palette="ALBEDO"),
    "ndvi_diff":   VisParams(band="NDVI", palette="SPECTRAL"),
    "ndwi_diff":   VisParams(band="NDWI", palette="SPECTRAL"),
    "albedo_diff": VisParams(band="albedo", palette="COOLWARM"),
}

# Mapeamento: chave em url_indices da API -> (band_key, display_name, layer_type, visible)
# O servidor pode retornar tanto class_irri (snake) quanto classIrri (camel)
_INDEX_KEY_MAP = {
    "NDVI":       ("NDVI",      "NDVI",          "NDVI",       False),
    "NDWI":       ("NDWI",      "NDWI",          "NDWI",       False),
    "albedo":     ("albedo",    "Albedo",        "ALBEDO",     False),
}

# Mapeamento das chaves de diferenca (pre-construidas com operator=SUBTRACT).
# URL ja vem pronta do servidor com image_id composto {img_A}-{img_B}.
_DIFF_KEY_MAP = {
    "Diferença NDVI":   ("ndvi_diff",   "Diff NDVI",   "NDVI_DIFF"),
    "Diferença NDWI":   ("ndwi_diff",   "Diff NDWI",   "NDWI_DIFF"),
    "Diferença albedo": ("albedo_diff", "Diff Albedo", "ALBEDO_DIFF"),
}

# Ordem desejada das bandas na arvore QGIS
_BAND_ORDER = ["original", "NDVI", "NDWI", "albedo",
               "ndvi_diff", "ndwi_diff", "albedo_diff"]

# Paletas disponiveis para customizacao
AVAILABLE_PALETTES = [
    # Especificas de dominio
    ("NDVI", "NDVI (branco → verde)"),
    ("NDWI", "NDWI (branco → azul)"),
    ("ALBEDO", "Albedo (preto → branco)"),
    # Genericas (matplotlib)
    ("VIRIDIS", "Viridis"), ("VIRIDIS_R", "Viridis (invertida)"),
    ("PLASMA", "Plasma"), ("PLASMA_R", "Plasma (invertida)"),
    ("RDYLGN", "Vermelho-Amarelo-Verde"), ("RDYLGN_R", "Verde-Amarelo-Vermelho"),
    ("SPECTRAL", "Spectral"), ("SPECTRAL_R", "Spectral (invertida)"),
    ("HOT", "Hot"), ("HOT_R", "Hot (invertida)"),
    ("BLUES", "Azuis"), ("BLUES_R", "Azuis (invertida)"),
    ("GREENS", "Verdes"), ("GREENS_R", "Verdes (invertida)"),
    ("COOLWARM", "Frio-Quente"), ("COOLWARM_R", "Quente-Frio"),
    ("TERRAIN", "Terreno"), ("TERRAIN_R", "Terreno (invertida)"),
]


def get_default_vis_params(band: str, sidecar: dict = None) -> VisParams:
    """Retorna VisParams para uma banda.

    Prioridade: sidecar (por mapeamento) > global (QgsSettings) > hardcoded.
    """
    try:
        from .vis_config_service import get_mapeamento_vis_params, get_global_vis_params
        if sidecar:
            return get_mapeamento_vis_params(sidecar, band)
        return get_global_vis_params(band)
    except Exception as e:
        # Fallback para defaults hardcoded se vis_config_service falhar
        from qgis.core import QgsMessageLog, Qgis
        QgsMessageLog.logMessage(
            f"[VisConfig] Fallback para hardcoded ({band}): {e}",
            "SatIrriga", Qgis.Warning,
        )
        defaults = _BAND_DEFAULTS.get(band)
        if defaults:
            return VisParams(
                band=defaults.band,
                min_val=defaults.min_val,
                max_val=defaults.max_val,
                gamma=defaults.gamma,
                palette=defaults.palette,
                gain=defaults.gain,
                bias=defaults.bias,
            )
        return VisParams(band=band)


def build_xyz_url(image_id: str, vis_params: VisParams) -> str:
    """URL XYZ com parametros de visualizacao customizados.

    Regra GEE: gamma e palette sao mutuamente exclusivos.
    Quando palette esta definida, gamma e omitido.
    """
    # Bandas multi-banda (RGB) nao aceitam palette no GEE
    is_multiband = vis_params.band in ("original",)
    has_palette = vis_params.palette and not is_multiband

    url = f"{_JOBS_BASE}/{image_id}/{{z}}/{{x}}/{{y}}?band={vis_params.band}"
    if vis_params.min_val is not None:
        url += f"&min={vis_params.min_val}"
    if vis_params.max_val is not None:
        url += f"&max={vis_params.max_val}"
    # GEE: gamma e palette sao mutuamente exclusivos;
    #       palette so funciona em bandas single-band
    if has_palette:
        url += f"&palette={vis_params.palette}"
    elif vis_params.gamma is not None:
        url += f"&gamma={vis_params.gamma}"
    if vis_params.gain is not None:
        url += f"&gain={vis_params.gain}"
    if vis_params.bias is not None:
        url += f"&bias={vis_params.bias}"
    return url


def get_tile_url(image_id: str, band: str = "original") -> str:
    """URL XYZ simples para exibicao inicial. Servidor aplica defaults.

    Gera URL com apenas ``?band=X``, sem parametros extras (min, max,
    palette). O jobs-server aplica ``S2_BAND_DEFAULTS`` automaticamente
    quando recebe apenas o parametro ``band``.
    """
    return f"{_JOBS_BASE}/{image_id}/{{z}}/{{x}}/{{y}}?band={band}"


def build_raster_hierarchy(tile_data, metodo_apply: str,
                           sidecar: dict = None) -> RasterHierarchy:
    """Constroi hierarquia de camadas raster a partir da resposta de tilesMetodos.

    Para tiles com ``id_imagem``, gera URLs diretas ao jobs-server com
    parametros de visualizacao da configuracao (sidecar > global > hardcoded).

    Para tiles legados (sem ``id_imagem``), usa URLs pre-construidas da API.

    O ``image_id`` e preservado em cada config para permitir customizacao
    posterior via ``build_xyz_url()``.

    Args:
        tile_data: JSON da resposta de GET /api/mapeamento/tilesMetodos.
        metodo_apply: Ignorado na selecao de bandas — mantido por assinatura.
        sidecar: Metadados do sidecar para config de vis por mapeamento.

    Returns:
        RasterHierarchy com datas > bandas > cenas.
    """
    if not isinstance(tile_data, list):
        if isinstance(tile_data, dict):
            tile_data = [tile_data]
        else:
            return RasterHierarchy()

    if not tile_data:
        return RasterHierarchy()

    # Agrupa tiles por data
    by_date = defaultdict(list)
    for item in tile_data:
        date_iso = _extract_date(item)
        by_date[date_iso].append(item)

    # Camadas de diferenca (URLs ja prontas com operator=SUBTRACT),
    # deduplicadas por URL e indexadas pela data da primeira imagem do par.
    diff_layers = _collect_diff_layers(tile_data, sidecar)

    # Garante que datas de diffs ausentes em tiles (raro) ainda apareçam.
    # Ordena datas (mais recente primeiro); "" vai ao final
    all_dates = set(by_date.keys()) | set(diff_layers.keys())
    sorted_dates = sorted(all_dates, reverse=True)

    date_groups = []
    for date_iso in sorted_dates:
        tiles = by_date.get(date_iso, [])
        date_label = _format_date_label(date_iso)

        # Coleta layers por band_key para todos os tiles desta data
        bands_map = {}  # band_key -> list[RasterLayerConfig]

        for tile_item in tiles:
            image_id = tile_item.get("id_imagem") or ""
            tile_name = tile_item.get("tile") or _extract_tile_name(image_id)

            if image_id:
                # Acesso direto: gera URL com params de visualizacao
                _build_direct_layers(bands_map, image_id, tile_name, sidecar)
            else:
                # Legado: usa URLs pre-construidas da API
                _build_legacy_layers(bands_map, tile_item, tile_name, image_id,
                                     sidecar)

        # Anexa camadas de diferenca desta data (ja deduplicadas)
        for band_key, config in diff_layers.get(date_iso, {}).items():
            bands_map.setdefault(band_key, []).append(config)

        # Monta BandGroups na ordem definida por _BAND_ORDER
        band_groups = []
        for band_key in _BAND_ORDER:
            layers = bands_map.get(band_key)
            if not layers:
                continue
            band_name = _resolve_band_name(band_key)
            band_groups.append(BandGroup(
                band_name=band_name,
                band_key=band_key,
                layers=layers,
            ))

        if band_groups:
            date_groups.append(DateGroup(
                date_label=date_label,
                date_iso=date_iso,
                bands=band_groups,
            ))

    return RasterHierarchy(dates=date_groups)


def _build_direct_layers(bands_map: dict, image_id: str, tile_name: str,
                         sidecar: dict = None):
    """Gera layers para TODAS as bandas via URL direta (tiles com image_id).

    Usa configuracao de visualizacao (sidecar > global > hardcoded) para
    gerar URLs com parametros customizados. Se nao houver customizacao,
    gera URL simples com apenas ``?band=X`` (servidor aplica defaults).
    """
    _DIRECT_BANDS = {
        "original":  ("RGB",            "RGB",        True),
        "NDVI":      ("NDVI",           "NDVI",       False),
        "NDWI":      ("NDWI",           "NDWI",       False),
        "albedo":    ("Albedo",         "ALBEDO",     False),
    }

    for band_key in _BAND_ORDER:
        info = _DIRECT_BANDS.get(band_key)
        if not info:
            continue
        display_name, layer_type, default_visible = info

        vis_params = get_default_vis_params(band_key, sidecar)
        # Gera URL com params customizados se houver config; senão URL simples
        xyz_url = build_xyz_url(image_id, vis_params)

        bands_map.setdefault(band_key, []).append(
            RasterLayerConfig(
                name=tile_name or display_name,
                xyz_url=xyz_url,
                layer_type=layer_type,
                tile=tile_name,
                image_id=image_id,
                vis_params=vis_params,
                is_visible=default_visible,
            )
        )


def _build_legacy_layers(bands_map: dict, tile_item: dict,
                         tile_name: str, image_id: str,
                         sidecar: dict = None):
    """Gera layers para tiles legados (sem image_id) usando URLs da API.

    RGB vem do campo ``url``; indices espectrais de ``url_indices``
    encontrado no primeiro method response disponivel.
    """
    # RGB: URL pre-construida do campo "url"
    rgb_url = tile_item.get("url")
    if rgb_url:
        bands_map.setdefault("original", []).append(
            RasterLayerConfig(
                name=tile_name or "RGB",
                xyz_url=rgb_url,
                layer_type="RGB",
                tile=tile_name,
                image_id=image_id,
                vis_params=get_default_vis_params("original", sidecar),
                is_visible=True,
            )
        )

    # Indices espectrais: URLs pre-construidas de url_indices
    url_indices = _find_url_indices(tile_item)
    for api_key, index_url in url_indices.items():
        if not index_url:
            continue
        mapping = _INDEX_KEY_MAP.get(api_key)
        if not mapping:
            continue
        band_key, display_name, layer_type, default_visible = mapping

        bands_map.setdefault(band_key, []).append(
            RasterLayerConfig(
                name=tile_name or display_name,
                xyz_url=index_url,
                layer_type=layer_type,
                tile=tile_name,
                image_id=image_id,
                vis_params=get_default_vis_params(band_key, sidecar),
                is_visible=default_visible,
            )
        )


def _resolve_band_name(band_key: str) -> str:
    """Nome de exibicao do grupo de banda a partir do band_key."""
    if band_key == "original":
        return "RGB"
    name = next(
        (dn for k, dn, _, _ in _INDEX_KEY_MAP.values() if k == band_key),
        None,
    )
    if name:
        return name
    name = next(
        (dn for k, dn, _ in _DIFF_KEY_MAP.values() if k == band_key),
        None,
    )
    return name or band_key


def _collect_diff_layers(tile_data: list, sidecar: dict = None) -> dict:
    """Extrai camadas de diferenca (NDVI/NDWI/albedo diff) dos method responses.

    As URLs de diferenca ja vem prontas com operator=SUBTRACT e image_id
    composto {img_A}-{img_B}. Como o servidor replica a mesma URL em todos
    os tiles da resposta, deduplicamos por URL (uma diff por banda por par).

    Returns:
        dict date_iso -> {band_key: RasterLayerConfig}, onde date_iso e a
        data extraida da primeira parte do compound image_id (img_A).
    """
    seen_urls = set()
    out = defaultdict(dict)
    for tile_item in tile_data:
        for key in _ALL_METHOD_KEYS:
            resp = tile_item.get(key)
            if not resp or not isinstance(resp, dict):
                continue
            url_indices = resp.get("url_indices") or {}
            for api_key, url in url_indices.items():
                mapping = _DIFF_KEY_MAP.get(api_key)
                if not mapping or not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                band_key, display_name, layer_type = mapping
                compound_id = _extract_image_id_from_url(url)
                date_iso = _extract_date_from_image_id(compound_id)
                if band_key in out[date_iso]:
                    continue  # ja ha diff desta banda nesta data
                out[date_iso][band_key] = RasterLayerConfig(
                    name=display_name,
                    xyz_url=url,
                    layer_type=layer_type,
                    tile="",
                    image_id=compound_id,
                    vis_params=get_default_vis_params(band_key, sidecar),
                    is_visible=False,
                )
    return out


def _extract_image_id_from_url(url: str) -> str:
    """Extrai segmento de image_id (possivelmente composto) de uma URL de tiles."""
    m = re.search(r"/tiles/s2/([^/]+)/", url)
    return m.group(1) if m else ""


def _extract_date_from_image_id(compound_id: str) -> str:
    """Para image_id composto 'img_A-img_B', retorna data ISO de img_A.

    Ex: '20251122T125321_20251122T125323_T24MXU-20251115T...' -> '2025-11-22'
    """
    if not compound_id:
        return ""
    first = compound_id.split("-", 1)[0]
    m = re.match(r"(\d{4})(\d{2})(\d{2})T", first)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def _find_url_indices(tile_item: dict) -> dict:
    """Encontra url_indices no primeiro method response disponivel do tile.

    Itera todos os method response keys conhecidos e retorna o primeiro
    url_indices nao vazio, sem depender de metodo_apply.
    """
    for key in _ALL_METHOD_KEYS:
        resp = tile_item.get(key)
        if resp and isinstance(resp, dict):
            url_indices = resp.get("url_indices")
            if url_indices and isinstance(url_indices, dict):
                return url_indices
    return {}


def _extract_date(tile_item: dict) -> str:
    """Extrai data ISO de um tile, tentando campos comuns da API."""
    for key in ("data", "date", "dataReferencia", "scanDate"):
        val = tile_item.get(key)
        if val and isinstance(val, str):
            return val.split("T")[0]  # normaliza para YYYY-MM-DD
    return ""


def _format_date_label(date_iso: str) -> str:
    """Converte data ISO (YYYY-MM-DD) para formato brasileiro (DD/MM/YYYY)."""
    if not date_iso:
        return "Sem data"
    try:
        parts = date_iso.split("T")[0].split("-")
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    except (ValueError, IndexError):
        pass
    return date_iso


def _extract_tile_name(image_id: str) -> str:
    """Extrai nome do tile a partir do image_id Sentinel-2.

    Ex: "S2A_MSIL2A_20251022T132231_N0511_R038_T24MXT_20251022T172030"
        -> "24MXT"
    """
    if not image_id:
        return ""
    parts = image_id.split("_")
    for part in parts:
        if part.startswith("T") and len(part) == 6:
            return part[1:]  # Remove prefixo "T"
    return ""


# ----------------------------------------------------------------
# Compatibilidade com codigo legado
# ----------------------------------------------------------------

def build_raster_configs(tile_data, metodo_apply: str) -> List[RasterLayerConfig]:
    """Wrapper de compatibilidade — retorna lista plana de RasterLayerConfig.

    DEPRECATED: Usar build_raster_hierarchy() para hierarquia completa.
    """
    hierarchy = build_raster_hierarchy(tile_data, metodo_apply)
    configs = []
    for date_group in hierarchy.dates:
        for band_group in date_group.bands:
            configs.extend(band_group.layers)
    return configs
