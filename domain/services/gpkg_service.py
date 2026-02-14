"""Servico de GeoPackage — paths, nomes, schema de sync."""

import os
from pathlib import Path

from qgis.core import QgsApplication

from ..models.enums import SyncStatusEnum

# Campos adicionais de controle de sync inseridos no GPKG local
SYNC_FIELDS = [
    ("_original_fid", "INTEGER"),
    ("_sync_status", "TEXT"),
    ("_sync_timestamp", "TEXT"),
    ("_mapeamento_id", "INTEGER"),
    ("_metodo_id", "INTEGER"),
]


def gpkg_base_dir(configured_dir: str = "") -> str:
    """Retorna diretorio base para GPKGs. Usa configurado ou fallback."""
    if configured_dir and os.path.isdir(configured_dir):
        return configured_dir
    default = os.path.join(
        QgsApplication.qgisSettingsDirPath(), "satirriga_data"
    )
    os.makedirs(default, exist_ok=True)
    return default


def gpkg_path(base_dir: str, mapeamento_id: int, metodo_id: int) -> str:
    """Caminho completo do GPKG para um metodo especifico."""
    folder = os.path.join(base_dir, f"mapeamento_{mapeamento_id}")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"metodo_{metodo_id}.gpkg")


def layer_group_name(descricao: str) -> str:
    """Nome do grupo de camadas no layer tree."""
    return f"SatIrriga / {descricao}"


def layer_name(metodo_apply: str) -> str:
    """Nome da camada no QGIS."""
    return metodo_apply


def count_features_by_sync_status(gpkg_path: str) -> dict:
    """Conta features por status de sync no GPKG.

    Returns dict: {DOWNLOADED: n, MODIFIED: n, UPLOADED: n, total: n}
    """
    from qgis.core import QgsVectorLayer

    counts = {"DOWNLOADED": 0, "MODIFIED": 0, "UPLOADED": 0, "total": 0}
    layer = QgsVectorLayer(gpkg_path, "count_sync", "ogr")
    if not layer.isValid():
        return counts

    sync_idx = layer.fields().indexOf("_sync_status")
    if sync_idx < 0:
        counts["total"] = layer.featureCount()
        return counts

    for feat in layer.getFeatures():
        status = feat.attribute(sync_idx)
        if status in counts:
            counts[status] += 1
        counts["total"] += 1

    return counts


def list_local_gpkgs(base_dir: str) -> list:
    """Lista todos os GPKGs na pasta base com metadados."""
    result = []
    base = Path(base_dir)
    if not base.exists():
        return result

    for gpkg_file in base.rglob("*.gpkg"):
        parts = gpkg_file.parts
        mapeamento_dir = gpkg_file.parent.name
        mapeamento_id = None
        metodo_id = None

        if mapeamento_dir.startswith("mapeamento_"):
            try:
                mapeamento_id = int(mapeamento_dir.split("_", 1)[1])
            except (ValueError, IndexError):
                pass

        fname = gpkg_file.stem
        if fname.startswith("metodo_"):
            try:
                metodo_id = int(fname.split("_", 1)[1])
            except (ValueError, IndexError):
                pass

        result.append({
            "path": str(gpkg_file),
            "mapeamento_id": mapeamento_id,
            "metodo_id": metodo_id,
            "size_mb": round(gpkg_file.stat().st_size / (1024 * 1024), 2),
        })

    return result
