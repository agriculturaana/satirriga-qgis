"""Servico de GeoPackage — paths, nomes, schema de sync."""

import json
import os
from pathlib import Path

from qgis.core import QgsApplication

from ..models.enums import SyncStatusEnum

# Campos adicionais de controle de sync inseridos no GPKG local (V1)
SYNC_FIELDS = [
    ("_original_fid", "INTEGER"),
    ("_sync_status", "TEXT"),
    ("_sync_timestamp", "TEXT"),
    ("_mapeamento_id", "INTEGER"),
    ("_metodo_id", "INTEGER"),
]

# Campos de controle de sync V2 (fluxo zonal)
SYNC_FIELDS_V2 = [
    ("_original_fid", "INTEGER"),
    ("_sync_status", "TEXT"),
    ("_sync_timestamp", "TEXT"),
    ("_zonal_id", "INTEGER"),
    ("_edit_token", "TEXT"),
]

SIDECAR_FILENAME = ".satirriga.json"


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
    """Caminho completo do GPKG para um metodo especifico (V1)."""
    folder = os.path.join(base_dir, f"mapeamento_{mapeamento_id}")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"metodo_{metodo_id}.gpkg")


def gpkg_path_for_zonal(base_dir: str, zonal_id: int) -> str:
    """Caminho completo do GPKG para um zonal (V2)."""
    folder = os.path.join(base_dir, f"zonal_{zonal_id}")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"zonal_{zonal_id}.gpkg")


def sidecar_path(gpkg_path_str: str) -> str:
    """Retorna caminho do sidecar .satirriga.json ao lado do GPKG."""
    return os.path.join(os.path.dirname(gpkg_path_str), SIDECAR_FILENAME)


def write_sidecar(gpkg_path_str: str, data: dict):
    """Grava JSON de metadados de checkout ao lado do GPKG."""
    path = sidecar_path(gpkg_path_str)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def read_sidecar(gpkg_path_str: str) -> dict:
    """Le JSON do sidecar. Retorna {} se inexistente."""
    path = sidecar_path(gpkg_path_str)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def detect_gpkg_version(gpkg_path_str: str) -> int:
    """Detecta versao do GPKG: 2 (zonal), 1 (mapeamento), 0 (desconhecido)."""
    from qgis.core import QgsVectorLayer

    layer = QgsVectorLayer(gpkg_path_str, "detect_version", "ogr")
    if not layer.isValid():
        return 0

    field_names = [f.name() for f in layer.fields()]
    if "_zonal_id" in field_names:
        return 2
    if "_mapeamento_id" in field_names:
        return 1
    return 0


def layer_group_name(descricao: str) -> str:
    """Nome do grupo de camadas no layer tree."""
    return f"SatIrriga / {descricao}"


def layer_name(metodo_apply: str) -> str:
    """Nome da camada no QGIS."""
    return metodo_apply


def count_features_by_sync_status(gpkg_path_str: str) -> dict:
    """Conta features por status de sync no GPKG.

    Returns dict: {DOWNLOADED: n, MODIFIED: n, UPLOADED: n, NEW: n, total: n}
    """
    from qgis.core import QgsVectorLayer

    counts = {"DOWNLOADED": 0, "MODIFIED": 0, "UPLOADED": 0, "NEW": 0, "total": 0}
    layer = QgsVectorLayer(gpkg_path_str, "count_sync", "ogr")
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
    """Lista todos os GPKGs na pasta base com metadados (V1 e V2)."""
    result = []
    base = Path(base_dir)
    if not base.exists():
        return result

    for gpkg_file in base.rglob("*.gpkg"):
        mapeamento_id = None
        metodo_id = None
        zonal_id = None
        gpkg_type = "v1"

        parent_name = gpkg_file.parent.name
        fname = gpkg_file.stem

        # Detecta V2: zonal_X/zonal_X.gpkg
        if parent_name.startswith("zonal_") and fname.startswith("zonal_"):
            try:
                zonal_id = int(parent_name.split("_", 1)[1])
                gpkg_type = "v2"
            except (ValueError, IndexError):
                pass

        # Detecta V1: mapeamento_X/metodo_Y.gpkg
        if parent_name.startswith("mapeamento_"):
            try:
                mapeamento_id = int(parent_name.split("_", 1)[1])
            except (ValueError, IndexError):
                pass

        if fname.startswith("metodo_"):
            try:
                metodo_id = int(fname.split("_", 1)[1])
            except (ValueError, IndexError):
                pass

        has_sidecar = os.path.exists(sidecar_path(str(gpkg_file)))

        result.append({
            "path": str(gpkg_file),
            "mapeamento_id": mapeamento_id,
            "metodo_id": metodo_id,
            "zonal_id": zonal_id,
            "type": gpkg_type,
            "has_sidecar": has_sidecar,
            "size_mb": round(gpkg_file.stat().st_size / (1024 * 1024), 2),
        })

    return result
