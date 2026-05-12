"""Serviço de configuração de visualização de rasters.

Dois níveis de configuração:
1. Global (QgsSettings) — defaults editáveis na aba Configurações
2. Por mapeamento (sidecar .satirriga.json) — sobrepõe a global

Parâmetros por banda: min, max, gamma, palette.
"""

import json

from qgis.core import QgsSettings

from ..models.raster import VisParams

_SETTINGS_PREFIX = "SatIrriga/vis/"

# Defaults hardcoded — calibrados com P2/P98 de 48k geometrias zonais reais
_HARDCODED_DEFAULTS = {
    "original": VisParams(band="original", min_val=0, max_val=3000, gamma=1.2),
    "NDVI":     VisParams(band="NDVI", min_val=0, max_val=0.8, palette="RDYLGN"),
    "NDWI":     VisParams(band="NDWI", min_val=-0.7, max_val=0.4, palette="BLUES"),
    "albedo":   VisParams(band="albedo", min_val=-0.7, max_val=0.4, palette="ALBEDO"),
}

# Bandas configuráveis (ordem de exibição na UI)
CONFIGURABLE_BANDS = [
    ("original", "RGB"),
    ("NDVI", "NDVI"),
    ("NDWI", "NDWI"),
    ("albedo", "Albedo"),
]


def get_global_vis_params(band: str) -> VisParams:
    """Retorna VisParams da configuração global (QgsSettings).

    Fallback para defaults hardcoded se nenhuma configuração foi salva.
    Aplica regra GEE: gamma e palette sao mutuamente exclusivos.
    """
    settings = QgsSettings()
    key = f"{_SETTINGS_PREFIX}{band}"
    raw = settings.value(key)

    if raw:
        try:
            data = json.loads(raw)
            palette = data.get("palette")
            gamma = data.get("gamma")
            # GEE nao permite gamma + palette simultaneamente
            if palette:
                gamma = None
            return VisParams(
                band=band,
                min_val=data.get("min"),
                max_val=data.get("max"),
                gamma=gamma,
                palette=palette,
                gain=data.get("gain"),
                bias=data.get("bias"),
            )
        except (json.JSONDecodeError, TypeError):
            pass

    defaults = _HARDCODED_DEFAULTS.get(band)
    if defaults:
        return VisParams(
            band=defaults.band,
            min_val=defaults.min_val,
            max_val=defaults.max_val,
            gamma=defaults.gamma,
            palette=defaults.palette,
        )
    return VisParams(band=band)


def save_global_vis_params(band: str, params: VisParams):
    """Salva VisParams na configuração global (QgsSettings)."""
    settings = QgsSettings()
    key = f"{_SETTINGS_PREFIX}{band}"
    data = {}
    if params.min_val is not None:
        data["min"] = params.min_val
    if params.max_val is not None:
        data["max"] = params.max_val
    if params.gamma is not None:
        data["gamma"] = params.gamma
    if params.palette:
        data["palette"] = params.palette
    if params.gain is not None:
        data["gain"] = params.gain
    if params.bias is not None:
        data["bias"] = params.bias
    settings.setValue(key, json.dumps(data))


def restore_global_defaults():
    """Restaura configuração global para defaults hardcoded."""
    settings = QgsSettings()
    for band, _ in CONFIGURABLE_BANDS:
        key = f"{_SETTINGS_PREFIX}{band}"
        settings.remove(key)


def get_mapeamento_vis_params(sidecar: dict, band: str) -> VisParams:
    """Retorna VisParams do sidecar (por mapeamento), com fallback à global.

    O sidecar pode conter:
    {
      "visConfig": {
        "NDVI": {"min": 0, "max": 0.8, "palette": "VIRIDIS"},
        "albedo": {"min": 0, "max": 0.5}
      }
    }
    """
    vis_config = sidecar.get("visConfig") or {}
    band_config = vis_config.get(band)

    # Base: configuração global
    base = get_global_vis_params(band)

    if not band_config:
        return base

    # Sobrepõe com valores do sidecar
    palette = band_config.get("palette", base.palette)
    gamma = band_config.get("gamma", base.gamma)
    # GEE nao permite gamma + palette simultaneamente
    if palette:
        gamma = None
    return VisParams(
        band=band,
        min_val=band_config.get("min", base.min_val),
        max_val=band_config.get("max", base.max_val),
        gamma=gamma,
        palette=palette,
        gain=band_config.get("gain", base.gain),
        bias=band_config.get("bias", base.bias),
    )


def save_mapeamento_vis_params(sidecar: dict, band: str, params: VisParams):
    """Salva VisParams no sidecar (por mapeamento)."""
    vis_config = sidecar.setdefault("visConfig", {})
    data = {}
    if params.min_val is not None:
        data["min"] = params.min_val
    if params.max_val is not None:
        data["max"] = params.max_val
    if params.gamma is not None:
        data["gamma"] = params.gamma
    if params.palette:
        data["palette"] = params.palette
    if params.gain is not None:
        data["gain"] = params.gain
    if params.bias is not None:
        data["bias"] = params.bias
    vis_config[band] = data
