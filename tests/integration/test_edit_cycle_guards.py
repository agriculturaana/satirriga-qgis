"""Guardas do ciclo de edição: acompanhamento, download, bloqueio da camada e painel, com QGIS real."""

import importlib
import json
import os
import pathlib
import sys
import types
import uuid
from unittest.mock import MagicMock

import pytest

from .conftest import create_gpkg_v2_with_features, read_gpkg_features, SAMPLE_FEATURES

_PACKAGE = "satirriga_guards"
package = types.ModuleType(_PACKAGE)
package.__path__ = [str(pathlib.Path(__file__).resolve().parents[2])]
sys.modules[_PACKAGE] = package
_PREVIOUS_QGIS = {name: module for name, module in sys.modules.items() if name == "qgis" or name.startswith("qgis.")}
for name in _PREVIOUS_QGIS:
    sys.modules.pop(name)
try:
    from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
    upload = importlib.import_module(f"{_PACKAGE}.infra.tasks.upload_task")
    download = importlib.import_module(f"{_PACKAGE}.infra.tasks.download_task")
    gpkg = importlib.import_module(f"{_PACKAGE}.domain.services.gpkg_service")
    controller_module = importlib.import_module(f"{_PACKAGE}.app.controllers.mapeamento_controller")
    widget_module = importlib.import_module(f"{_PACKAGE}.ui.widgets.upload_progress_widget")
    dialog_module = importlib.import_module(f"{_PACKAGE}.ui.dialogs.attribute_dialog")
    _REAL_QGIS = {name: module for name, module in sys.modules.items() if name == "qgis" or name.startswith("qgis.")}
finally:
    for name in list(sys.modules):
        if name == "qgis" or name.startswith("qgis."):
            sys.modules.pop(name)
    sys.modules.update(_PREVIOUS_QGIS)


@pytest.fixture(autouse=True)
def qgis_environment(monkeypatch):
    for name, module in _REAL_QGIS.items():
        monkeypatch.setitem(sys.modules, name, module)
    app = QgsApplication.instance() or QgsApplication([], False)
    app.initQgis()
    monkeypatch.setattr(upload.time, "sleep", lambda _: None)
    yield app


@pytest.fixture
def source(tmp_path):
    path = str(tmp_path / "zonal_42.gpkg")
    create_gpkg_v2_with_features(path, [SAMPLE_FEATURES[0], {
        "id": 0, "geometry_wkt": SAMPLE_FEATURES[1]["geometry_wkt"], "sync_status": "NEW",
    }])
    gpkg.write_sidecar(path, {
        "zonalId": 42, "zonalVersion": 7, "snapshotHash": "downloaded-hash",
        "editToken": "old-token", "featureCount": 2,
    })
    return path


def response(http_status=200, **payload):
    result = MagicMock()
    result.status_code = http_status
    result.json.return_value = payload
    result.text = json.dumps(payload)
    return result


def upload_task(source, expected_version=7):
    return upload.UploadZonalTask(
        "http://sat/api/zonal/42/upload", "http://sat/api/zonal/42/checkout",
        "access-token", source, 42, "old-token", expected_version,
        zonal_status_url="http://sat/api/zonal/42/status",
    )


def upload_server(monkeypatch, poll_url="/api/zonal/upload/batch-42/status"):
    sent = []

    def post(url, **kwargs):
        if url.endswith("checkout"):
            return response(editToken="fresh-token", zonalVersion=7, snapshotHash="downloaded-hash")
        sent.append(dict(kwargs["data"]))
        return response(202, batchUuid="batch-42", pollUrl=poll_url)

    monkeypatch.setattr(upload.requests, "post", post)
    return sent


def cached_copy(tmp_path, **metadata):
    output = gpkg.gpkg_path_for_zonal(str(tmp_path), 42)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    create_gpkg_v2_with_features(output, SAMPLE_FEATURES[:1])
    gpkg.write_sidecar(output, {
        "zonalId": 42, "etag": '"zonal-42-v7"', "featureCount": 1, "zonalVersion": 7,
        "snapshotHash": "base-consumida", "editToken": "old-token", **metadata,
    })
    return output


def fresh_download(tmp_path):
    server_copy = str(tmp_path / "servidor.gpkg")
    create_gpkg_v2_with_features(server_copy, SAMPLE_FEATURES[:2])
    body = pathlib.Path(server_copy).read_bytes()
    result = MagicMock()
    result.status_code = 200
    result.headers = {"ETag": '"zonal-42-v9"', "X-Zonal-Version": "9", "X-Snapshot-Hash": "base-nova",
                      "X-Feature-Count": "2", "content-length": str(len(body))}
    result.iter_content.return_value = [body]
    return result


def not_modified():
    result = MagicMock()
    result.status_code = 304
    result.headers = {}
    return result


def run_download(output, monkeypatch, get):
    monkeypatch.setattr(download.requests, "post", MagicMock(return_value=response(
        editToken="new-token", zonalVersion=9, featureCount=2, snapshotHash="base-nova",
        expiresAt="2026-09-17T00:00:00Z",
    )))
    monkeypatch.setattr(download.requests, "get", get)
    return download.DownloadZonalTask(
        checkout_url="http://sat/api/zonal/42/checkout",
        download_url="http://sat/api/zonal/42/download-result.gpkg",
        access_token="access-token", gpkg_output_path=output, zonal_id=42, origin="mapeamentos",
    ).run()


def test_acompanhamento_recusa_endereco_de_outro_host_sem_enviar_o_token(source, monkeypatch):
    sent = upload_server(monkeypatch, poll_url="https://coletor.example/api/zonal/upload/batch-42/status")
    get = MagicMock(return_value=response(status="COMPLETED", batchUuid="batch-42", reprocessingStatus="DONE"))
    monkeypatch.setattr(upload.requests, "get", get)
    current = upload_task(source)
    assert current.run() is False
    assert len(sent) == 1
    get.assert_not_called()
    assert "fora do servidor" in str(current._exception)


def test_envio_com_versao_base_divergente_da_esperada_nao_transmite_pacote(source, monkeypatch):
    sent = upload_server(monkeypatch)
    current = upload_task(source, expected_version=8)
    assert current.run() is False
    assert sent == []
    assert "divergentes" in str(current._exception)
    assert not gpkg.read_sidecar(source).get("uploadOperations")


def test_download_com_recibo_pendente_nao_inicia_tarefa_nem_altera_a_copia(tmp_path, monkeypatch):
    output = cached_copy(tmp_path, uploadOperations=[{"operationId": str(uuid.uuid4()), "submitted": True}])
    before = gpkg.read_sidecar(output)
    state, config = MagicMock(), MagicMock()
    config.get.return_value = str(tmp_path)
    controller = controller_module.MapeamentoController(state, MagicMock(), config, token_provider=lambda: "token")
    application = MagicMock()
    monkeypatch.setattr(controller_module, "QgsApplication", application)
    controller.download_zonal_result(42)
    application.taskManager().addTask.assert_not_called()
    assert state.set_error.call_args.args[0] == "download:42"
    assert "pendente" in state.set_error.call_args.args[1]
    assert gpkg.read_sidecar(output) == before


def test_download_de_copia_consumida_nao_envia_if_none_match_nem_aproveita_resposta_304(tmp_path, monkeypatch):
    output = cached_copy(tmp_path, needsRedownload=True)
    get = MagicMock(side_effect=[not_modified(), fresh_download(tmp_path)])
    assert run_download(output, monkeypatch, get) is True
    assert "If-None-Match" not in get.call_args_list[0].kwargs["headers"]
    assert len(read_gpkg_features(output)) == 2
    sidecar = gpkg.read_sidecar(output)
    assert (sidecar["zonalVersion"], sidecar["snapshotHash"], sidecar.get("needsRedownload")) == (9, "base-nova", None)


def test_download_preserva_historico_de_operacoes_da_copia_anterior(tmp_path, monkeypatch):
    operations = [{"operationId": str(uuid.uuid4()), "submitted": True, "status": "COMPLETED", "batchUuid": "batch-42"}]
    output = cached_copy(tmp_path, needsRedownload=True, uploadOperations=operations)
    assert run_download(output, monkeypatch, MagicMock(return_value=fresh_download(tmp_path))) is True
    assert gpkg.read_sidecar(output)["uploadOperations"] == operations


def test_envio_bloqueia_as_camadas_antes_de_iniciar_a_tarefa(source, monkeypatch):
    state, config = MagicMock(), MagicMock()
    config.get.return_value = "http://sat/api"
    controller = controller_module.MapeamentoController(state, MagicMock(), config, token_provider=lambda: "token")
    layer = QgsVectorLayer(source, "zonal", "ogr")
    QgsProject.instance().addMapLayer(layer)
    locked_on_start = []
    application = MagicMock()
    application.taskManager().addTask.side_effect = lambda task: locked_on_start.append(layer.readOnly())
    monkeypatch.setattr(controller_module, "QgsApplication", application)
    try:
        assert layer.readOnly() is False
        controller.upload_zonal_edits(source)
        assert locked_on_start == [True]
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


@pytest.mark.parametrize("metadata", [
    {"needsRedownload": True},
    {"uploadOperations": [{"operationId": "5b0f8b1e-4f7c-4d7e-9a57-0f3f6f0d9c11", "submitted": True}]},
], ids=["copia_consumida", "envio_pendente"])
def test_dialogo_nao_grava_em_camada_editavel_com_copia_consumida_ou_envio_pendente(source, monkeypatch, metadata):
    sidecar = gpkg.read_sidecar(source)
    sidecar.update(metadata)
    gpkg.write_sidecar(source, sidecar)
    layer = QgsVectorLayer(source, "zonal", "ogr")
    dialog = dialog_module.AttributeEditDialog(layer, next(layer.getFeatures()))
    dialog._widgets["grupo"].setText("9")
    before = read_gpkg_features(source)
    warning = MagicMock()
    monkeypatch.setattr(importlib.import_module("qgis.PyQt.QtWidgets").QMessageBox, "warning", warning)
    assert layer.readOnly() is False
    dialog._save()
    assert read_gpkg_features(source) == before
    warning.assert_called_once()
    dialog.close()


def test_painel_mostra_falha_do_lote_mesmo_com_zonal_concluida():
    widget = widget_module.UploadProgressWidget()
    widget.update_from_status({
        "phase": "reprocessing_done", "reprocessingStatus": "FAILED", "zonalStatus": "DONE",
        "reprocessingError": "Cálculo do lote interrompido", "pendingGeoids": 0,
    })
    assert widget._status_label.text() == "Recálculo com falha"
    assert "Cálculo do lote interrompido" in widget._detail_label.text()
