"""Fabrica de QgsVectorLayer (memory provider) para camadas-base.

Cada camada (municipios, bacias, empreendimentos) tem schema fixo e estilo
proprio. As geometrias sao recebidas em GeoJSON via BasesService e injetadas
no provider em memoria; nao ha I/O em disco.
"""

import json

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsField,
    QgsFillSymbol,
    QgsJsonUtils,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)


# Caps de bbox por camada (em graus^2). Aplicados no cliente para evitar
# requests destinados a 413 — espelho dos limites server-side em
# server/src/controllers/bases.ts:LAYER_CONFIG.
MAX_BBOX_DEG2 = {
    "empreendimentos": 4.0,
    "municipios": 16.0,
    "bacias": 16.0,
}

_CRS_4674 = "EPSG:4674"


# Schema (nome, label exibido, tipo Python -> QVariant)
_SCHEMAS = {
    "municipios": [
        ("muncd", "Codigo IBGE", QVariant.LongLong),
        ("munnm", "Municipio", QVariant.String),
        ("ufdsg", "UF", QVariant.String),
    ],
    "bacias": [
        ("baf_id", "ID", QVariant.LongLong),
        ("baf_cd", "Codigo", QVariant.LongLong),
        ("baf_nm", "Bacia", QVariant.String),
        ("baf_uam_cd", "Codigo UAM", QVariant.LongLong),
        ("baf_uam_nm", "UAM", QVariant.String),
    ],
    "empreendimentos": [
        ("empid", "ID", QVariant.LongLong),
        ("empcd", "Codigo", QVariant.String),
        ("empnm", "Empreendimento", QVariant.String),
        ("usunm", "Usuario", QVariant.String),
    ],
}


_LAYER_NAMES = {
    "municipios": "Municipios",
    "bacias": "Bacias Hidrograficas",
    "empreendimentos": "Empreendimentos",
}


def _style_for(layer_id: str) -> QgsFillSymbol:
    """Estilo equivalente ao usado no MVT antigo (plugin.py:799-828)."""
    if layer_id == "municipios":
        props = {
            "color": "0,0,0,0",
            "outline_color": "#7f8c8d",
            "outline_width": "0.4",
            "outline_style": "dash",
        }
    elif layer_id == "bacias":
        props = {
            "color": "0,0,0,0",
            "outline_color": "#2980b9",
            "outline_width": "0.6",
            "outline_style": "solid",
        }
    elif layer_id == "empreendimentos":
        props = {
            "color": "230,126,34,38",
            "outline_color": "#e67e22",
            "outline_width": "0.5",
            "outline_style": "solid",
        }
    else:
        raise ValueError(f"layer_id invalido: {layer_id}")
    return QgsFillSymbol.createSimple(props)


def display_name(layer_id: str) -> str:
    return _LAYER_NAMES[layer_id]


def create_empty_layer(layer_id: str) -> QgsVectorLayer:
    """Cria uma camada Polygon em memoria com schema da camada e estilo padrao.

    A camada inicia vazia — usar ``populate(layer, fc)`` para inserir features.
    """
    if layer_id not in _SCHEMAS:
        raise ValueError(f"layer_id invalido: {layer_id}")

    layer = QgsVectorLayer(
        f"Polygon?crs={_CRS_4674}",
        _LAYER_NAMES[layer_id],
        "memory",
    )
    if not layer.isValid():
        raise RuntimeError(f"Falha ao criar memory layer para {layer_id}")

    fields = [
        QgsField(name, qvariant)
        for name, _label, qvariant in _SCHEMAS[layer_id]
    ]
    layer.dataProvider().addAttributes(fields)
    layer.updateFields()

    layer.setRenderer(QgsSingleSymbolRenderer(_style_for(layer_id)))
    layer.setCustomProperty("satirriga/base_layer_id", layer_id)
    return layer


def populate(layer: QgsVectorLayer, feature_collection: dict) -> int:
    """Substitui as features da camada pelas do FeatureCollection informado.

    Retorna a quantidade de features adicionadas. Se o FC vier vazio, a camada
    e apenas truncada.
    """
    provider = layer.dataProvider()
    if provider.featureCount() > 0:
        provider.truncate()

    raw_features = feature_collection.get("features") or []
    if not raw_features:
        layer.updateExtents()
        layer.triggerRepaint()
        return 0

    fc_json = json.dumps(feature_collection)
    qgs_features = list(
        QgsJsonUtils.stringToFeatureList(fc_json, layer.fields(), None)
    )

    if not qgs_features and raw_features:
        # Fallback explicito: parse Feature por Feature via stringToFeatureList
        # (cada Feature serializada). Chama-se quando o parser de
        # FeatureCollection nao reconhece o payload por algum motivo.
        for raw in raw_features:
            single = json.dumps({
                "type": "FeatureCollection",
                "features": [raw],
            })
            sub = QgsJsonUtils.stringToFeatureList(single, layer.fields(), None)
            qgs_features.extend(sub)

    provider.addFeatures(qgs_features)
    layer.updateExtents()
    layer.triggerRepaint()
    return len(qgs_features)


def bbox_area_deg2(bbox_4674) -> float:
    """Area em graus^2 do bbox (minX, minY, maxX, maxY)."""
    min_x, min_y, max_x, max_y = bbox_4674
    return max(0.0, (max_x - min_x) * (max_y - min_y))


def is_bbox_within_cap(layer_id: str, bbox_4674) -> bool:
    """True se o bbox estiver dentro do limite por camada (evita 413)."""
    cap = MAX_BBOX_DEG2.get(layer_id)
    if cap is None:
        return True
    return bbox_area_deg2(bbox_4674) <= cap
