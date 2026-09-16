"""Contrato de persistência e repetição do upload com QGIS e GeoPackage reais."""

import importlib
import io
import json
import pathlib
import sys
import types
import uuid
import zipfile
from unittest.mock import MagicMock

import pytest
import requests
from osgeo import ogr

from .conftest import create_gpkg_v2_with_features, read_gpkg_features, SAMPLE_FEATURES

_PACKAGE = "satirriga_integrity"
package = types.ModuleType(_PACKAGE)
package.__path__ = [str(pathlib.Path(__file__).resolve().parents[2])]
sys.modules[_PACKAGE] = package
_PREVIOUS_QGIS = {name: module for name, module in sys.modules.items() if name == "qgis" or name.startswith("qgis.")}
for name in _PREVIOUS_QGIS:
    sys.modules.pop(name)
try:
    from qgis.core import QgsApplication, QgsVectorLayer
    upload = importlib.import_module(f"{_PACKAGE}.infra.tasks.upload_task")
    gpkg = importlib.import_module(f"{_PACKAGE}.domain.services.gpkg_service")
    controller_module = importlib.import_module(f"{_PACKAGE}.app.controllers.mapeamento_controller")
    widget_module = importlib.import_module(f"{_PACKAGE}.ui.widgets.upload_progress_widget")
    dialog_module = importlib.import_module(f"{_PACKAGE}.ui.dialogs.attribute_dialog")
    tab_module = importlib.import_module(f"{_PACKAGE}.ui.widgets.mapeamentos_tab")
    zonal_models = importlib.import_module(f"{_PACKAGE}.domain.models.zonal")
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
    }, {"id": 999, "sync_status": "DELETED"}])
    gpkg.write_sidecar(path, {
        "zonalId": 42, "zonalVersion": 7, "snapshotHash": "downloaded-hash",
        "editToken": "old-token", "featureCount": 3,
    })
    return path


def task(source):
    return upload.UploadZonalTask(
        "http://sat/api/zonal/42/upload", "http://sat/api/zonal/42/checkout",
        "access-token", source, 42, "old-token", 7,
        zonal_status_url="http://sat/api/zonal/42/status",
    )


def response(http_status=200, **payload):
    result = MagicMock()
    result.status_code = http_status
    result.json.return_value = payload
    result.text = json.dumps(payload)
    return result


def server(monkeypatch, failure=None, reprocessing="DONE"):
    requests_sent = []
    def post(url, **kwargs):
        if url.endswith("checkout"):
            return response(editToken="fresh-token", zonalVersion=12, snapshotHash="server-hash")
        requests_sent.append({"data": dict(kwargs["data"]), "archive": kwargs["files"]["file"][1].read()})
        if failure:
            raise failure
        return response(202, batchUuid="batch-42", pollUrl="/api/uploads/batch-42/status")
    monkeypatch.setattr(upload.requests, "post", post)
    monkeypatch.setattr(upload.requests, "get", lambda *a, **k: response(
        status="COMPLETED", batchUuid="batch-42", progressPct=100,
        reprocessingStatus=reprocessing, reprocessingError="Falha no cálculo" if reprocessing == "FAILED" else None,
        pendingGeoids=2 if reprocessing == "FAILED" else 0,
    ))
    return requests_sent


def test_renovacao_preserva_base_baixada(source):
    current = task(source)
    current._update_sidecar({"editToken": "fresh", "zonalVersion": 15, "snapshotHash": "other"})
    sidecar = gpkg.read_sidecar(source)
    assert sidecar["zonalVersion"] == 7
    assert sidecar["snapshotHash"] == "downloaded-hash"
    assert sidecar["editToken"] == "fresh"


def test_reenvio_apos_timeout_reutiliza_bytes_identidade_e_base(source, monkeypatch):
    sent = server(monkeypatch, failure=requests.Timeout("Resposta perdida"))
    assert task(source).run() is False
    ds = ogr.Open(source, 1)
    ds.ExecuteSQL("UPDATE gpkg_contents SET last_change = '2099-01-01T00:00:00.000Z'")
    ds.ExecuteSQL("UPDATE zonal SET _sync_timestamp = '2099-01-01T00:00:00Z'")
    ds = None
    assert task(source).run() is False
    assert len(sent) == 2
    assert sent[0]["archive"] == sent[1]["archive"]
    first = sent[0]["data"]
    assert uuid.UUID(first["operationId"])
    assert first["operationId"] == sent[1]["data"]["operationId"]
    assert first["protocolVersion"] == "2"
    assert first["baseVersion"] == first["expectedVersion"] == "7"
    assert first["baseSnapshotHash"] == "downloaded-hash"


def test_export_preserva_identidade_de_inclusao_e_tombstone(source, monkeypatch, tmp_path):
    sent = server(monkeypatch, failure=requests.Timeout())
    assert task(source).run() is False
    local = read_gpkg_features(source)
    inclusion = next(row for row in local if row["_sync_status"] == "NEW")
    assert uuid.UUID(inclusion["_client_feature_id"])
    with zipfile.ZipFile(io.BytesIO(sent[0]["archive"])) as archive:
        archive.extractall(tmp_path / "export")
    exported = read_gpkg_features(str(tmp_path / "export" / "upload.gpkg"))
    assert next(row for row in exported if row["_sync_status"] == "NEW")["_client_feature_id"] == inclusion["_client_feature_id"]
    tombstone = next(row for row in exported if row["_sync_status"] == "DELETED")
    assert tombstone["_original_fid"] == 999
    assert tombstone["has_geometry"] is False


def test_recibo_conhecido_retoma_polling_sem_post(source, monkeypatch):
    sent = server(monkeypatch)
    first = task(source)
    assert first.run() is True
    previous = gpkg.read_sidecar(source)
    assert previous.get("uploadOperations")
    second = task(source)
    assert second.run() is True
    assert len(sent) == 1
    assert second.batch_uuid == first.batch_uuid == "batch-42"
    assert gpkg.read_sidecar(source)["uploadOperations"][0]["response"] == previous["uploadOperations"][0]["response"]


def test_download_de_outra_revisao_permite_nova_edicao_apos_lote_concluido(source, monkeypatch):
    sent = server(monkeypatch)
    assert task(source).run() is True
    metadata = gpkg.read_sidecar(source)
    metadata.update(zonalVersion=8, snapshotHash="next-download-hash", needsRedownload=False)
    gpkg.write_sidecar(source, metadata)
    ds = ogr.Open(source, 1)
    ds.ExecuteSQL("UPDATE zonal SET grupo = 'Classe revisada' WHERE _sync_status = 'NEW'")
    ds = None
    following = upload.UploadZonalTask(
        "http://sat/api/zonal/42/upload", "http://sat/api/zonal/42/checkout",
        "access-token", source, 42, "next-token", 8,
        zonal_status_url="http://sat/api/zonal/42/status",
    )
    assert following.run() is True
    assert len(sent) == 2
    assert sent[0]["data"]["operationId"] != sent[1]["data"]["operationId"]
    assert sent[1]["data"]["baseVersion"] == "8"
    assert len(gpkg.read_sidecar(source)["uploadOperations"]) == 2


def test_falha_de_recalculo_mantem_upload_persistido_sem_conclusao_generica(source, monkeypatch):
    server(monkeypatch, reprocessing="FAILED")
    current = task(source)
    messages, events, completions = [], [], []
    current.signals.status_message.connect(messages.append)
    current.signals.upload_progress.connect(events.append)
    current.signals.completed.connect(lambda ok, message: completions.append((ok, message)))
    assert current.run() is True
    current.finished(True)
    assert "Concluído" not in messages
    assert current.result["uploadPersisted"] is True
    assert current.result["reprocessingStatus"] == "FAILED"
    assert current.result["pendingGeoids"] == 2
    assert current.result["reprocessingError"] == "Falha no cálculo"
    assert completions[-1][0] is True
    assert "falha" in completions[-1][1].lower()
    widget = widget_module.UploadProgressWidget()
    widget.update_from_status(events[-1])
    assert "falha" in widget._status_label.text().lower()


def test_timeout_processando_continua_pendente(source, monkeypatch):
    server(monkeypatch, reprocessing="PROCESSING")
    current = task(source)
    events = []
    current.signals.upload_progress.connect(events.append)
    assert current.run() is True
    assert current.result["uploadPersisted"] is True
    assert current.result["reprocessingStatus"] == "PROCESSING"
    assert current.result["pending"] is True
    assert events[-1]["phase"] == "reprocessing_timeout"


def test_persistencia_nao_remove_tombstones_nem_modifica_conteudo(source):
    controller = controller_module.MapeamentoController(MagicMock(), MagicMock(), MagicMock())
    before = read_gpkg_features(source)
    controller._mark_uploaded(source)
    assert read_gpkg_features(source) == before
    assert gpkg.read_sidecar(source)["needsRedownload"] is True


def test_dialog_aberto_nao_grava_apos_bloqueio_da_camada(source, monkeypatch):
    layer = QgsVectorLayer(source, "zonal", "ogr")
    feature = next(layer.getFeatures())
    dialog = dialog_module.AttributeEditDialog(layer, feature)
    dialog._widgets["grupo"].setText("9")
    before = read_gpkg_features(source)
    monkeypatch.setattr(importlib.import_module("qgis.PyQt.QtWidgets").QMessageBox, "warning", MagicMock())
    layer.setReadOnly(True)
    dialog._save()
    assert read_gpkg_features(source) == before
    dialog.close()


def test_rastreamento_atribui_id_uma_vez_e_bloqueia_base_consumida(source):
    controller = controller_module.MapeamentoController(MagicMock(), MagicMock(), MagicMock())
    layer = QgsVectorLayer(source, "zonal", "ogr")
    controller.connect_edit_tracking(layer, zonal_id=42)
    controller._mark_edited_features(layer)
    rows = read_gpkg_features(source)
    identity = next(row for row in rows if row["_sync_status"] == "NEW")["_client_feature_id"]
    assert uuid.UUID(identity)
    controller._mark_edited_features(layer)
    assert next(row for row in read_gpkg_features(source) if row["_sync_status"] == "NEW")["_client_feature_id"] == identity
    controller._mark_uploaded(source)
    reloaded = QgsVectorLayer(source, "zonal", "ogr")
    controller.connect_edit_tracking(reloaded, zonal_id=42)
    assert reloaded.readOnly() is True


def test_edicao_apos_persistencia_exige_download(source, monkeypatch):
    sent = server(monkeypatch)
    assert task(source).run() is True
    ds = ogr.Open(source, 1)
    ds.ExecuteSQL("UPDATE zonal SET grupo = 'Outra classe' WHERE _sync_status = 'NEW'")
    ds = None
    current = task(source)
    assert current.run() is False
    assert "download" in str(current._exception).lower()
    assert len(sent) == 1


def test_edicao_apos_lote_rejeitado_cria_outra_operacao_na_mesma_base(source, monkeypatch):
    sent = server(monkeypatch)
    monkeypatch.setattr(upload.requests, "get", lambda *a, **k: response(
        status="FAILED", batchUuid="batch-42", errorLog="Conflito de geometria",
    ))
    first = task(source)
    assert first.run() is False
    ds = ogr.Open(source, 1)
    ds.ExecuteSQL("UPDATE zonal SET grupo = 'Classe revisada' WHERE _sync_status = 'NEW'")
    ds = None
    second = task(source)
    assert second.run() is False
    assert len(sent) == 2
    assert sent[0]["data"]["operationId"] != sent[1]["data"]["operationId"]
    assert sent[1]["data"]["baseVersion"] == "7"
    history = gpkg.read_sidecar(source)["uploadOperations"]
    assert len(history) == 2
    assert history[0]["response"]["batchUuid"] == "batch-42"


def test_recibo_permanece_apos_timeout_do_polling(source, monkeypatch):
    sent = server(monkeypatch)
    monkeypatch.setattr(upload.requests, "get", MagicMock(side_effect=requests.Timeout("Consulta interrompida")))
    assert task(source).run() is False
    saved = gpkg.read_sidecar(source)["uploadOperations"][0]
    monkeypatch.setattr(upload.requests, "get", lambda *a, **k: response(
        status="COMPLETED", batchUuid="batch-42", reprocessingStatus="NOT_REQUIRED",
    ))
    resumed = task(source)
    assert resumed.run() is True
    assert len(sent) == 1
    assert gpkg.read_sidecar(source)["uploadOperations"][0]["response"] == saved["response"]
    assert resumed.result["reprocessingStatus"] == "NOT_REQUIRED"
    assert resumed.result["pending"] is False


def test_pacote_corrompido_nao_e_recriado_apos_timeout(source, monkeypatch):
    sent = server(monkeypatch, failure=requests.Timeout())
    assert task(source).run() is False
    archive = next((pathlib.Path(source).parent / ".satirriga-upload").glob("*.zip"))
    archive.write_bytes(b"incompleto")
    retry = task(source)
    assert retry.run() is False
    assert len(sent) == 1
    assert "pacote" in str(retry._exception).lower()


def test_mudanca_de_conteudo_sem_recibo_nao_gera_segunda_operacao(source, monkeypatch):
    sent = server(monkeypatch, failure=requests.Timeout())
    assert task(source).run() is False
    ds = ogr.Open(source, 1)
    ds.ExecuteSQL("UPDATE zonal SET grupo = 'Outra classe' WHERE _sync_status = 'NEW'")
    ds = None
    assert task(source).run() is False
    assert len(sent) == 1
    assert len(gpkg.read_sidecar(source)["uploadOperations"]) == 1


def test_clone_qgis_recebe_identidade_propria_e_a_preserva_no_commit(source, qgis_environment):
    from qgis.core import QgsFeature

    controller = controller_module.MapeamentoController(MagicMock(), MagicMock(), MagicMock())
    layer = QgsVectorLayer(source, "zonal", "ogr")
    controller.connect_edit_tracking(layer, zonal_id=42)
    controller._mark_edited_features(layer)
    template = next(feature for feature in layer.getFeatures() if feature["_sync_status"] == "NEW")
    assert layer.startEditing()
    clone = QgsFeature(template)
    clone["fid"] = None
    assert layer.addFeature(clone)
    added = layer.getFeature(clone.id())
    assert added["_client_feature_id"] != template["_client_feature_id"]
    identity = added["_client_feature_id"]
    assert layer.commitChanges()
    qgis_environment.processEvents()
    additions = [feature for feature in read_gpkg_features(source) if feature["_sync_status"] == "NEW"]
    assert len(additions) == 2
    assert identity in {feature["_client_feature_id"] for feature in additions}


def test_tombstone_repetido_pelo_signal_e_persistido_uma_vez(source):
    controller = controller_module.MapeamentoController(MagicMock(), MagicMock(), MagicMock())
    layer = QgsVectorLayer(source, "zonal", "ogr")
    controller.connect_edit_tracking(layer, zonal_id=42)
    controller._pending_edit_fids[layer.id()] = {"changed": set(), "deleted_originals": [999, 999, 123, 123]}
    controller._mark_edited_features(layer)
    tombstones = [feature["_original_fid"] for feature in read_gpkg_features(source) if feature["_sync_status"] == "DELETED"]
    assert sorted(tombstones) == [123, 999]


def test_sinais_reconectam_apos_reabrir_projeto_com_propriedades_persistidas(source):
    from qgis.core import QgsFeature

    controller = controller_module.MapeamentoController(MagicMock(), MagicMock(), MagicMock())
    layer = QgsVectorLayer(source, "zonal", "ogr")
    layer.setCustomProperty("satirriga/edit_tracking", True)
    controller.connect_edit_tracking(layer, zonal_id=42)
    assert layer.fields().indexOf("_client_feature_id") >= 0
    assert layer.startEditing()
    feature = QgsFeature(layer.fields())
    assert layer.addFeature(feature)
    added = layer.getFeature(feature.id())
    assert uuid.UUID(added["_client_feature_id"])
    layer.rollBack()


def test_download_nao_substitui_base_durante_upload(source, monkeypatch):
    state, config = MagicMock(), MagicMock()
    config.get.return_value = str(pathlib.Path(source).parent)
    controller = controller_module.MapeamentoController(state, MagicMock(), config, token_provider=lambda: "token")
    active = MagicMock()
    active._source_path = gpkg.gpkg_path_for_zonal(config.get.return_value, 42)
    active.status.return_value = 1
    active.Complete, active.Terminated = 3, 4
    controller._active_tasks = [active]
    application = MagicMock()
    monkeypatch.setattr(controller_module, "QgsApplication", application)
    controller.download_zonal_result(42)
    application.taskManager().addTask.assert_not_called()
    assert "andamento" in state.set_error.call_args.args[1]


def test_camada_pendente_de_recibo_permanece_bloqueada_apos_timeout(source, monkeypatch):
    server(monkeypatch, failure=requests.Timeout())
    assert task(source).run() is False
    controller = controller_module.MapeamentoController(MagicMock(), MagicMock(), MagicMock())
    layer = QgsVectorLayer(source, "zonal", "ogr")
    controller.connect_edit_tracking(layer, zonal_id=42)
    assert layer.readOnly() is True


def test_bloqueio_de_arquivo_impede_envios_de_processos_distintos(source, monkeypatch):
    from qgis.PyQt.QtCore import QLockFile

    sent = server(monkeypatch, failure=requests.Timeout())
    lock = QLockFile(str(pathlib.Path(source).parent / ".satirriga-upload.lock"))
    assert lock.tryLock(0)
    try:
        current = task(source)
        assert current.run() is False
        assert sent == []
        assert "andamento" in str(current._exception)
    finally:
        lock.unlock()


def test_recusa_http_nao_bloqueia_novo_download_como_resposta_incerta(source, monkeypatch):
    server(monkeypatch)
    def reject(url, **kwargs):
        if url.endswith("checkout"):
            return response(editToken="fresh-token", zonalVersion=9, snapshotHash="server")
        return response(409, message="Revisão-base conflitante")
    monkeypatch.setattr(upload.requests, "post", reject)
    current = task(source)
    assert current.run() is False
    assert gpkg.has_pending_upload(gpkg.read_sidecar(source)) is False
    assert current.result["pending"] is False


def test_consulta_recuperada_nao_mantem_erro_transitorio(source, monkeypatch):
    server(monkeypatch)
    monkeypatch.setattr(upload.requests, "get", MagicMock(side_effect=[
        response(status="COMPLETED", batchUuid="batch-42", reprocessingStatus="PROCESSING"),
        requests.Timeout("Consulta temporariamente indisponível"),
        response(status="COMPLETED", batchUuid="batch-42", reprocessingStatus="DONE"),
    ]))
    current = task(source)
    assert current.run() is True
    assert current.result["reprocessingStatus"] == "DONE"
    assert current.result["error"] is None


def refused_checkout():
    refused = response(403, message="Mapeamento finalizado.")
    refused.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
    return refused


def test_camada_bloqueada_na_carga_rastreia_exclusao_ao_voltar_a_ser_editavel(source, qgis_environment):
    from qgis.core import QgsProject

    metadata = gpkg.read_sidecar(source)
    metadata["uploadOperations"] = [{"operationId": str(uuid.uuid4()), "submitted": True}]
    gpkg.write_sidecar(source, metadata)
    controller = controller_module.MapeamentoController(MagicMock(), MagicMock(), MagicMock())
    layer = QgsVectorLayer(source, "zonal", "ogr")
    QgsProject.instance().addMapLayer(layer)
    try:
        controller.connect_edit_tracking(layer, zonal_id=42)
        assert layer.readOnly() is True
        metadata = gpkg.read_sidecar(source)
        metadata["uploadOperations"][0]["status"] = "FAILED"
        gpkg.write_sidecar(source, metadata)
        controller._on_zonal_upload_completed(False, "Envio não persistido: FAILED", source, 42, [(layer.id(), False)])
        assert layer.readOnly() is False
        target = next(feature for feature in layer.getFeatures() if feature["_original_fid"] == 101)
        assert layer.startEditing()
        assert layer.deleteFeature(target.id())
        assert layer.commitChanges()
        qgis_environment.processEvents()
        tombstones = [row["_original_fid"] for row in read_gpkg_features(source) if row["_sync_status"] == "DELETED"]
        assert 101 in tombstones
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def test_excluir_copia_nao_gera_tombstone_da_origem(source, qgis_environment):
    from qgis.core import QgsFeature

    controller = controller_module.MapeamentoController(MagicMock(), MagicMock(), MagicMock())
    layer = QgsVectorLayer(source, "zonal", "ogr")
    controller.connect_edit_tracking(layer, zonal_id=42)
    template = next(feature for feature in layer.getFeatures() if feature["_original_fid"] == 101)
    assert layer.startEditing()
    clone = QgsFeature(template)
    clone["fid"] = None
    assert layer.addFeature(clone)
    assert layer.commitChanges()
    qgis_environment.processEvents()
    copy = next(feature for feature in layer.getFeatures() if feature["_sync_status"] == "NEW" and feature["_original_fid"] == 101)
    assert layer.startEditing()
    assert layer.deleteFeature(copy.id())
    assert layer.commitChanges()
    qgis_environment.processEvents()
    rows = [(row["_original_fid"], row["_sync_status"]) for row in read_gpkg_features(source)]
    assert (101, "DOWNLOADED") in rows
    assert (101, "DELETED") not in rows


def test_checkout_recusado_nao_impede_recuperar_recibo_de_operacao_enviada(source, monkeypatch):
    sent, checkouts = [], []

    def post(url, **kwargs):
        if url.endswith("checkout"):
            checkouts.append(url)
            return response(editToken="fresh-token", expiresAt="2099-01-01T00:00:00Z") if len(checkouts) == 1 else refused_checkout()
        sent.append(kwargs["data"]["operationId"])
        if len(sent) == 1:
            raise requests.Timeout("Resposta perdida")
        return response(202, batchUuid="batch-42", pollUrl="/api/uploads/batch-42/status")

    monkeypatch.setattr(upload.requests, "post", post)
    monkeypatch.setattr(upload.requests, "get", lambda *a, **k: response(
        status="COMPLETED", batchUuid="batch-42", reprocessingStatus="NOT_REQUIRED"))
    assert task(source).run() is False
    retry = task(source)
    assert retry.run() is True
    assert len(sent) == 2
    assert sent[0] == sent[1]
    assert retry.batch_uuid == "batch-42"
    assert gpkg.has_pending_upload(gpkg.read_sidecar(source)) is False


def test_checkout_recusado_antes_do_primeiro_envio_nao_transmite_pacote(source, monkeypatch):
    sent = []

    def post(url, **kwargs):
        if url.endswith("checkout"):
            return refused_checkout()
        sent.append(kwargs["data"]["operationId"])
        return response(202, batchUuid="batch-42", pollUrl="/api/uploads/batch-42/status")

    monkeypatch.setattr(upload.requests, "post", post)
    assert task(source).run() is False
    assert sent == []


def test_pacote_e_sincronizado_por_descritor_aberto_para_escrita(source, monkeypatch):
    import errno
    import fcntl
    import os

    real_fsync = os.fsync

    # Emula o Windows, onde a sincronização exige descritor aberto com permissão de escrita.
    def windows_fsync(descriptor):
        if fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY:
            raise OSError(errno.EBADF, "Bad file descriptor")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", windows_fsync)
    sent = server(monkeypatch)
    assert task(source).run() is True
    assert len(sent) == 1


@pytest.mark.parametrize("final_status", ["FAILED", "CANCELLED"])
def test_lote_encerrado_sem_persistencia_permite_reenviar_mesmo_conteudo(source, monkeypatch, final_status):
    sent = server(monkeypatch)
    replies = iter([
        response(status=final_status, batchUuid="batch-42", errorLog="Falha transitória"),
        response(status="COMPLETED", batchUuid="batch-42", reprocessingStatus="NOT_REQUIRED"),
    ])
    monkeypatch.setattr(upload.requests, "get", lambda *a, **k: next(replies))
    assert task(source).run() is False
    retry = task(source)
    assert retry.run() is True
    assert len(sent) == 2
    assert sent[0]["data"]["operationId"] != sent[1]["data"]["operationId"]
    assert sent[1]["data"]["baseVersion"] == "7"
    assert [operation["status"] for operation in gpkg.read_sidecar(source)["uploadOperations"]] == [final_status, "COMPLETED"]


def test_sidecar_ilegivel_nao_e_sobrescrito(source):
    path = pathlib.Path(source).parent / ".satirriga.json"
    path.write_text("{corrompido", encoding="utf-8")
    with pytest.raises(ValueError):
        gpkg.update_sidecar(source, lambda sidecar: sidecar.update({"needsRedownload": True}))
    assert path.read_text(encoding="utf-8") == "{corrompido"


def test_upload_concluido_com_sidecar_ilegivel_informa_erro_e_mantem_camada_bloqueada(source):
    from qgis.core import QgsProject

    state = MagicMock()
    controller = controller_module.MapeamentoController(state, MagicMock(), MagicMock())
    layer = QgsVectorLayer(source, "zonal", "ogr")
    QgsProject.instance().addMapLayer(layer)
    try:
        (pathlib.Path(source).parent / ".satirriga.json").write_text("{corrompido", encoding="utf-8")
        controller._on_zonal_upload_completed(True, "Envio persistido", source, 42, [(layer.id(), False)])
        assert layer.readOnly() is True
        assert "metadados" in state.set_error.call_args.args[1].lower()
    finally:
        QgsProject.instance().removeMapLayer(layer.id())


def _status_polled(controller, zonal_id, payload):
    controller._pending_poll_ids["poll"] = zonal_id
    controller._on_request_finished("poll", 200, json.dumps(payload))


def _reprocess_controller():
    state = MagicMock()
    http = MagicMock()
    http.post_json.return_value = "reprocess"
    return state, controller_module.MapeamentoController(state, http, MagicMock())


def test_calculo_retomavel_encerra_acompanhamento_e_retomada_volta_a_acompanhar():
    state, controller = _reprocess_controller()
    controller.start_polling_zonal(42)
    _status_polled(controller, 42, {"status": "PROCESSING", "resumable": False})
    assert (controller.is_polling(42), controller.is_resumable(42)) == (True, False)
    _status_polled(controller, 42, {"status": "PROCESSING", "resumable": True})
    assert (controller.is_polling(42), controller.is_resumable(42)) == (False, True)
    state.zonal_status_polled.emit.assert_called_with(42, "PROCESSING")
    controller.reprocess_overlay(42)
    controller._on_request_finished("reprocess", 200, json.dumps({"message": "Reprocessamento iniciado"}))
    assert (controller.is_polling(42), controller.is_resumable(42)) == (True, False)


def test_retomada_recusada_informa_o_motivo_e_volta_a_acompanhar():
    state, controller = _reprocess_controller()
    controller.start_polling_zonal(42)
    _status_polled(controller, 42, {"status": "PROCESSING", "resumable": True})
    controller.reprocess_overlay(42)
    refusal = "Cálculo em andamento desde 2026-09-15T10:00:00.000Z; a retomada fica disponível após duas horas sem conclusão."
    controller._on_request_finished("reprocess", 409, json.dumps({"code": "PROCESSING_ACTIVE", "message": refusal}))
    state.set_error.assert_called_with("reprocess", refusal)
    assert (controller.is_polling(42), controller.is_resumable(42)) == (True, False)


@pytest.mark.parametrize("resumable", [True, False])
def test_card_em_processamento_so_oferece_reprocessar_quando_retomavel(resumable, tmp_path):
    from qgis.PyQt.QtWidgets import QPushButton

    state = MagicMock()
    state.is_authenticated = False
    controller = MagicMock()
    controller.get_gpkg_base_dir.return_value = str(tmp_path)
    controller.is_polling.return_value = False
    controller.is_resumable.return_value = resumable
    tab = tab_module.MapeamentosTab(state, controller)
    card = tab._create_card(zonal_models.CatalogoItem(id=42, descricao="Zonal", status="PROCESSING", mapeamento_id=7))
    assert ("Reprocessar" in [button.text() for button in card.findChildren(QPushButton)]) is resumable
    assert controller.start_polling_zonal.called is not resumable


def test_card_de_calculo_retomavel_e_recriado_quando_o_acompanhamento_encerra():
    state = MagicMock()
    state.is_authenticated = False
    controller = MagicMock()
    controller.is_resumable.return_value = True
    tab = tab_module.MapeamentosTab(state, controller)
    tab._request_page = MagicMock()
    tab._on_zonal_status_polled(42, "PROCESSING")
    tab._request_page.assert_called_once()
