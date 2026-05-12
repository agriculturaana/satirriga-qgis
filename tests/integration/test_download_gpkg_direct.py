"""Testes do download zonal direto em GeoPackage."""

import importlib.util
import os
import shutil
import sys
import tempfile
import types
from unittest.mock import MagicMock

import pytest
from osgeo import ogr, osr

from .conftest import (
    SAMPLE_FEATURES,
    read_gpkg_features,
    read_gpkg_field_names,
)


@pytest.fixture
def temp_dir():
    directory = tempfile.mkdtemp(prefix="satirriga_test_")
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


class _Signal:
    def __init__(self, *args):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)

    def connect(self, *args):
        pass

    def disconnect(self, *args):
        pass


class _QgsTask:
    CanCancel = 1

    def __init__(self, *args, **kwargs):
        self.progress_values = []

    def setProgress(self, value):
        self.progress_values.append(value)

    def isCanceled(self):
        return False


class _QgsMessageLog:
    messages = []

    @classmethod
    def logMessage(cls, *args, **kwargs):
        cls.messages.append((args, kwargs))


class _Qgis:
    Info = 0
    Warning = 1


class _Response:
    def __init__(self, status_code, body=b"", headers=None, json_data=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self._json_data = json_data or {}
        self.text = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else str(body)

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]


def _install_qgis_mocks():
    qgis = types.ModuleType("qgis")
    core = types.ModuleType("qgis.core")
    pyqt = types.ModuleType("qgis.PyQt")
    qtcore = types.ModuleType("qgis.PyQt.QtCore")

    qtcore.QObject = type("QObject", (), {"__init__": lambda *a, **k: None})
    qtcore.pyqtSignal = _Signal
    core.QgsTask = _QgsTask
    core.QgsMessageLog = _QgsMessageLog
    core.Qgis = _Qgis
    core.QgsApplication = MagicMock()

    sys.modules.update({
        "qgis": qgis,
        "qgis.core": core,
        "qgis.PyQt": pyqt,
        "qgis.PyQt.QtCore": qtcore,
    })


def _load_download_module():
    """Carrega a task simulando o pacote QGIS, para resolver imports relativos."""
    _install_qgis_mocks()

    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    packages = {
        "satirriga_qgis": root,
        "satirriga_qgis.infra": os.path.join(root, "infra"),
        "satirriga_qgis.infra.tasks": os.path.join(root, "infra", "tasks"),
        "satirriga_qgis.infra.config": os.path.join(root, "infra", "config"),
        "satirriga_qgis.domain": os.path.join(root, "domain"),
        "satirriga_qgis.domain.models": os.path.join(root, "domain", "models"),
        "satirriga_qgis.domain.services": os.path.join(root, "domain", "services"),
    }
    for name, path in packages.items():
        module = types.ModuleType(name)
        module.__path__ = [path]
        sys.modules[name] = module

    module_name = "satirriga_qgis.infra.tasks.download_task"
    module_path = os.path.join(root, "infra", "tasks", "download_task.py")
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _create_server_gpkg(path, features):
    """Cria um GPKG como o servidor novo entrega: sem campos de sync locais."""
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(path)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    lyr = ds.CreateLayer("zonal_result", srs=srs, geom_type=ogr.wkbPolygon)

    fields = [
        ("id", ogr.OFTInteger),
        ("area_ha", ogr.OFTReal),
        ("codigo_empreendimento", ogr.OFTString),
        ("nome_empreendimento", ogr.OFTString),
        ("codigo_municipio", ogr.OFTString),
        ("nome_municipio", ogr.OFTString),
        ("sigla_uf", ogr.OFTString),
        ("codigo_bacia", ogr.OFTString),
        ("nome_bacia", ogr.OFTString),
    ]
    for name, field_type in fields:
        lyr.CreateField(ogr.FieldDefn(name, field_type))

    defn = lyr.GetLayerDefn()
    for idx, item in enumerate(features):
        feat = ogr.Feature(defn)
        feat.SetField("id", item["id"])
        feat.SetField("area_ha", item["attrs"].get("areaHa"))
        feat.SetField("codigo_empreendimento", f"EMP{idx + 1}")
        feat.SetField("nome_empreendimento", f"Empreendimento {idx + 1}")
        feat.SetField("codigo_municipio", "123")
        feat.SetField("nome_municipio", "Municipio Teste")
        feat.SetField("sigla_uf", "GO")
        feat.SetField("codigo_bacia", "456")
        feat.SetField("nome_bacia", "Bacia Teste")
        feat.SetGeometry(ogr.CreateGeometryFromWkt(item["geometry_wkt"]))
        lyr.CreateFeature(feat)

    ds = None
    with open(path, "rb") as fp:
        return fp.read()


class TestDownloadZonalTaskGpkg:
    def test_downloads_gpkg_and_adds_sync_fields(self, temp_dir, monkeypatch):
        module = _load_download_module()
        gpkg_bytes = _create_server_gpkg(
            os.path.join(temp_dir, "server.gpkg"),
            SAMPLE_FEATURES[:2],
        )

        checkout_data = {
            "editToken": "tok-edit",
            "zonalVersion": 7,
            "featureCount": 2,
            "snapshotHash": "hash-1",
            "expiresAt": "2026-05-01T00:00:00Z",
        }
        get_response = _Response(
            200,
            gpkg_bytes,
            headers={
                "ETag": '"gpkg-v7-42-1"',
                "X-Feature-Count": "2",
                "content-length": str(len(gpkg_bytes)),
            },
        )

        post_mock = MagicMock(return_value=_Response(200, json_data=checkout_data))
        get_mock = MagicMock(return_value=get_response)
        monkeypatch.setattr(module.requests, "post", post_mock)
        monkeypatch.setattr(module.requests, "get", get_mock)

        output_path = os.path.join(temp_dir, "zonal_42", "zonal_42.gpkg")
        task = module.DownloadZonalTask(
            checkout_url="https://api.test/zonal/42/checkout",
            download_url="https://api.test/zonal/42/download-result.gpkg",
            access_token="access-token",
            gpkg_output_path=output_path,
            zonal_id=42,
            catalogo_meta={"origin": "mapeamentos", "descricao": "Teste"},
            origin="mapeamentos",
        )

        assert task.run() is True
        assert os.path.exists(output_path)

        field_names = read_gpkg_field_names(output_path)
        for field_name in ["_original_fid", "_sync_status", "_sync_timestamp", "_zonal_id", "_edit_token"]:
            assert field_name in field_names
        for field_name in ["codigo_empreendimento", "nome_municipio", "sigla_uf", "nome_bacia"]:
            assert field_name in field_names

        features = read_gpkg_features(output_path)
        assert len(features) == 2
        assert features[0]["_original_fid"] == 101
        assert features[0]["_sync_status"] == "DOWNLOADED"
        assert features[0]["_zonal_id"] == 42
        assert features[0]["_edit_token"] == "tok-edit"
        assert features[0]["codigo_empreendimento"] == "EMP1"
        assert features[0]["nome_municipio"] == "Municipio Teste"

        sidecar = module.read_sidecar(output_path)
        assert sidecar["etag"] == '"gpkg-v7-42-1"'
        assert sidecar["featureCount"] == 2
        assert sidecar["editToken"] == "tok-edit"
        assert sidecar["origin"] == "mapeamentos"
        assert sidecar["descricao"] == "Teste"

        get_headers = get_mock.call_args.kwargs["headers"]
        assert get_headers["Accept"] == "application/geopackage+sqlite3"

    def test_304_reuses_valid_cached_gpkg_and_updates_sidecar(self, temp_dir, monkeypatch):
        module = _load_download_module()
        cached_path = os.path.join(temp_dir, "zonal_42", "zonal_42.gpkg")
        os.makedirs(os.path.dirname(cached_path), exist_ok=True)
        _create_server_gpkg(cached_path, SAMPLE_FEATURES[:1])

        module.write_sidecar(cached_path, {
            "etag": '"gpkg-v7-42-1"',
            "featureCount": 1,
            "editToken": "old-token",
            "origin": "mapeamentos",
        })

        checkout_data = {
            "editToken": "new-token",
            "zonalVersion": 8,
            "featureCount": 1,
            "snapshotHash": "hash-2",
            "expiresAt": "2026-05-02T00:00:00Z",
        }
        monkeypatch.setattr(
            module.requests,
            "post",
            MagicMock(return_value=_Response(200, json_data=checkout_data)),
        )
        get_mock = MagicMock(return_value=_Response(304))
        monkeypatch.setattr(module.requests, "get", get_mock)

        task = module.DownloadZonalTask(
            checkout_url="https://api.test/zonal/42/checkout",
            download_url="https://api.test/zonal/42/download-result.gpkg",
            access_token="access-token",
            gpkg_output_path=cached_path,
            zonal_id=42,
            origin="mapeamentos",
        )

        assert task.run() is True

        sidecar = module.read_sidecar(cached_path)
        assert sidecar["editToken"] == "new-token"
        assert sidecar["zonalVersion"] == 8
        assert sidecar["snapshotHash"] == "hash-2"
        assert sidecar["expiresAt"] == "2026-05-02T00:00:00Z"

        get_headers = get_mock.call_args.kwargs["headers"]
        assert get_headers["If-None-Match"] == '"gpkg-v7-42-1"'
        assert get_headers["Accept"] == "application/geopackage+sqlite3"


def test_controller_uses_direct_gpkg_endpoint():
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    controller_path = os.path.join(root, "app", "controllers", "mapeamento_controller.py")
    with open(controller_path, encoding="utf-8") as fp:
        source = fp.read()

    assert 'f"/zonal/{zonal_id}/download-result.gpkg"' in source
    assert 'download_url = self._api_url(f"/zonal/{zonal_id}/download-result")' not in source
