"""Controller de mapeamentos — catalogo zonal, download, upload V2."""

import json

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.core import QgsApplication, QgsVectorLayer, QgsMessageLog, Qgis

from ...infra.config.settings import PLUGIN_NAME
from ...infra.http.client import HttpClient
from ...app.state.store import AppState


class MapeamentoController(QObject):
    """Orquestra operacoes de mapeamento V2 (zonal)."""

    # Signals V2 (zonal)
    zonal_download_completed = pyqtSignal(str, int)  # gpkg_path, zonal_id
    zonal_upload_completed = pyqtSignal(str, int)    # gpkg_path, zonal_id
    upload_progress = pyqtSignal(dict)               # UploadBatchStatus dict
    conflict_detected = pyqtSignal(str)              # batchUuid
    edit_tracking_done = pyqtSignal()                # apos marcar features editadas

    def __init__(self, state: AppState, http_client: HttpClient,
                 config_repo, token_provider=None, parent=None):
        super().__init__(parent)
        self._state = state
        self._http = http_client
        self._config = config_repo
        self._token_provider = token_provider

        # Tracking de requests pendentes
        self._pending_catalogo_id = None
        self._active_tasks = []
        self._pending_edit_fids = {}

        # Conecta signals do HttpClient
        self._http.request_finished.connect(self._on_request_finished)
        self._http.request_error.connect(self._on_request_error)

    def _api_url(self, path):
        base = self._config.get("api_base_url").rstrip("/")
        return f"{base}{path}"

    def get_gpkg_base_dir(self):
        """Retorna diretorio base para GPKGs, respeitando configuracao."""
        from ...domain.services.gpkg_service import gpkg_base_dir
        return gpkg_base_dir(self._config.get("gpkg_base_dir"))

    # ----------------------------------------------------------------
    # Catalogo Zonal (V2)
    # ----------------------------------------------------------------

    def load_catalogo(self):
        """Carrega catalogo de zonais consolidados/concluidos."""
        if not self._state.is_authenticated:
            return

        url = self._api_url("/zonal/catalogo?status=CONSOLIDATED")
        self._state.set_loading("catalogo", True)
        self._pending_catalogo_id = self._http.get(url)

    # ----------------------------------------------------------------
    # Request handlers
    # ----------------------------------------------------------------

    def _on_request_finished(self, request_id, status_code, body):
        if request_id == self._pending_catalogo_id:
            self._pending_catalogo_id = None
            self._state.set_loading("catalogo", False)
            try:
                from ...domain.models.zonal import CatalogoItem
                data = json.loads(body)
                if isinstance(data, list):
                    items_raw = data
                else:
                    items_raw = data.get("data") or data.get("content") or []
                items = [CatalogoItem.from_dict(item) for item in items_raw]
                self._state.catalogo_items = items
                QgsMessageLog.logMessage(
                    f"[Catalogo] {len(items)} zonais carregados",
                    PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear catalogo: {e}\nBody: {body[:500]}",
                    PLUGIN_NAME, Qgis.Warning,
                )
                self._state.set_error("catalogo", f"Erro ao processar catalogo: {e}")

    def _on_request_error(self, request_id, error_msg):
        if request_id == self._pending_catalogo_id:
            self._pending_catalogo_id = None
            self._state.set_loading("catalogo", False)
            self._state.set_error("catalogo", error_msg)

    # ----------------------------------------------------------------
    # Download Zonal (V2)
    # ----------------------------------------------------------------

    def download_zonal_result(self, zonal_id):
        """Inicia download do resultado zonal via checkout + FlatGeobuf."""
        from ...infra.tasks.download_task import DownloadZonalTask
        from ...domain.services.gpkg_service import gpkg_path_for_zonal, gpkg_base_dir

        if not self._state.is_authenticated or not self._token_provider:
            self._state.set_error("download", "Nao autenticado")
            return

        token = self._token_provider()
        if not token:
            self._state.set_error("download", "Token nao disponivel")
            return

        checkout_url = self._api_url(f"/zonal/{zonal_id}/checkout")
        download_url = self._api_url(f"/zonal/{zonal_id}/download-result")
        base_dir = gpkg_base_dir(self._config.get("gpkg_base_dir"))
        output_path = gpkg_path_for_zonal(base_dir, zonal_id)

        task = DownloadZonalTask(
            checkout_url=checkout_url,
            download_url=download_url,
            access_token=token,
            gpkg_output_path=output_path,
            zonal_id=zonal_id,
        )

        task.signals.completed.connect(
            lambda success, msg: self._on_zonal_download_completed(
                success, msg, output_path, zonal_id
            )
        )
        task.signals.status_message.connect(
            lambda msg: QgsMessageLog.logMessage(msg, PLUGIN_NAME, Qgis.Info)
        )

        self._active_tasks.append(task)
        self._state.set_loading("download", True)
        QgsApplication.taskManager().addTask(task)

    def _on_zonal_download_completed(self, success, message, gpkg_path, zonal_id):
        self._cleanup_finished_tasks()
        self._state.set_loading("download", False)
        if success:
            self.zonal_download_completed.emit(gpkg_path, zonal_id)
            QgsMessageLog.logMessage(
                f"Download zonal concluido: {gpkg_path}", PLUGIN_NAME, Qgis.Info,
            )
        else:
            self._state.set_error("download", message)
            QgsMessageLog.logMessage(
                f"Download zonal falhou: {message}", PLUGIN_NAME, Qgis.Warning,
            )

    # ----------------------------------------------------------------
    # Upload Zonal (V2)
    # ----------------------------------------------------------------

    def upload_zonal_edits(self, gpkg_path, conflict_strategy="REJECT_CONFLICTS"):
        """Inicia upload de edicoes via fluxo zonal V2."""
        from ...infra.tasks.upload_task import UploadZonalTask
        from ...domain.services.gpkg_service import read_sidecar

        if not self._state.is_authenticated or not self._token_provider:
            self._state.set_error("upload", "Nao autenticado")
            return

        token = self._token_provider()
        if not token:
            self._state.set_error("upload", "Token nao disponivel")
            return

        sidecar = read_sidecar(gpkg_path)
        edit_token = sidecar.get("editToken")
        zonal_id = sidecar.get("zonalId")
        zonal_version = sidecar.get("zonalVersion", 0)

        if not edit_token or not zonal_id:
            self._state.set_error(
                "upload",
                "Metadados de checkout nao encontrados. Faca novo download."
            )
            return

        upload_url = self._api_url(f"/zonal/{zonal_id}/upload")

        task = UploadZonalTask(
            upload_url=upload_url,
            access_token=token,
            gpkg_source_path=gpkg_path,
            zonal_id=zonal_id,
            edit_token=edit_token,
            expected_version=zonal_version,
            conflict_strategy=conflict_strategy,
        )

        task.signals.completed.connect(
            lambda success, msg: self._on_zonal_upload_completed(
                success, msg, gpkg_path, zonal_id
            )
        )
        task.signals.status_message.connect(
            lambda msg: QgsMessageLog.logMessage(msg, PLUGIN_NAME, Qgis.Info)
        )
        task.signals.upload_progress.connect(
            lambda data: self.upload_progress.emit(data)
        )
        task.signals.conflict_detected.connect(
            lambda batch_uuid: self.conflict_detected.emit(batch_uuid)
        )

        self._active_tasks.append(task)
        self._state.set_loading("upload", True)
        QgsApplication.taskManager().addTask(task)

    def _on_zonal_upload_completed(self, success, message, gpkg_path, zonal_id):
        self._cleanup_finished_tasks()
        self._state.set_loading("upload", False)
        if success:
            self._mark_uploaded(gpkg_path)
            self.zonal_upload_completed.emit(gpkg_path, zonal_id)
            QgsMessageLog.logMessage(
                f"Upload zonal concluido: {gpkg_path}", PLUGIN_NAME, Qgis.Info,
            )
        else:
            self._state.set_error("upload", message)
            QgsMessageLog.logMessage(
                f"Upload zonal falhou: {message}", PLUGIN_NAME, Qgis.Warning,
            )

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    def _cleanup_finished_tasks(self):
        """Remove tasks finalizadas da lista de tasks ativas."""
        self._active_tasks = [
            t for t in self._active_tasks
            if t.status() not in (t.Complete, t.Terminated)
        ]

    def _mark_uploaded(self, gpkg_path):
        """Marca features MODIFIED/NEW como UPLOADED no GPKG via dataProvider batch."""
        from ...domain.models.enums import SyncStatusEnum
        from datetime import datetime, timezone

        layer = QgsVectorLayer(gpkg_path, "mark_uploaded", "ogr")
        if not layer.isValid():
            return

        sync_idx = layer.fields().indexOf("_sync_status")
        ts_idx = layer.fields().indexOf("_sync_timestamp")
        if sync_idx < 0:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        attr_changes = {}
        for feat in layer.getFeatures():
            status = feat.attribute(sync_idx)
            if status in (SyncStatusEnum.MODIFIED.value, SyncStatusEnum.NEW.value):
                changes = {sync_idx: SyncStatusEnum.UPLOADED.value}
                if ts_idx >= 0:
                    changes[ts_idx] = now_iso
                attr_changes[feat.id()] = changes

        if attr_changes:
            layer.dataProvider().changeAttributeValues(attr_changes)

    # ----------------------------------------------------------------
    # Edit tracking
    # ----------------------------------------------------------------

    def connect_edit_tracking(self, layer, mapeamento_id=None,
                              metodo_id=None, zonal_id=None):
        """Conecta signals para rastrear edicoes na camada.

        Usa beforeCommitChanges para capturar IDs editados do editBuffer,
        e afterCommitChanges para persistir o _sync_status no GPKG.
        """
        layer_id = layer.id()
        self._pending_edit_fids[layer_id] = {"changed": set(), "added": set()}

        layer.beforeCommitChanges.connect(
            lambda: self._capture_edited_fids(layer)
        )
        layer.afterCommitChanges.connect(
            lambda: QTimer.singleShot(0, lambda: self._mark_edited_features(layer))
        )

    def _capture_edited_fids(self, layer):
        """Captura IDs das features alteradas e adicionadas antes do commit."""
        layer_id = layer.id()
        changed_fids = set()
        added_fids = set()

        buf = layer.editBuffer()
        if buf:
            changed_fids.update(buf.changedGeometries().keys())
            changed_fids.update(buf.changedAttributeValues().keys())
            added_fids.update(buf.addedFeatures().keys())

        self._pending_edit_fids[layer_id] = {
            "changed": changed_fids,
            "added": added_fids,
        }

    def _mark_edited_features(self, layer):
        """Marca features editadas como MODIFIED e novas como NEW no GPKG.

        Usa dataProvider().changeAttributeValues() para batch direto no GPKG,
        sem startEditing/commitChanges (evita loop de signals e e O(1) no provider).
        """
        from ...domain.models.enums import SyncStatusEnum
        from datetime import datetime, timezone

        layer_id = layer.id()
        fid_data = self._pending_edit_fids.pop(layer_id, None)
        if not fid_data:
            return
        changed_fids = fid_data.get("changed", set())
        added_fids = fid_data.get("added", set())

        if not changed_fids and not added_fids:
            return

        sync_idx = layer.fields().indexOf("_sync_status")
        ts_idx = layer.fields().indexOf("_sync_timestamp")
        if sync_idx < 0:
            return

        now_iso = datetime.now(timezone.utc).isoformat()

        # Batch: {fid: {field_idx: new_value, ...}, ...}
        attr_changes = {}
        modified_count = 0
        new_count = 0

        for fid in changed_fids:
            if fid in added_fids:
                continue
            feat = layer.getFeature(fid)
            if not feat.isValid():
                continue
            current_status = feat.attribute(sync_idx)
            if current_status in (SyncStatusEnum.DOWNLOADED.value,
                                  SyncStatusEnum.MODIFIED.value):
                changes = {sync_idx: SyncStatusEnum.MODIFIED.value}
                if ts_idx >= 0:
                    changes[ts_idx] = now_iso
                attr_changes[fid] = changes
                modified_count += 1

        for fid in added_fids:
            feat = layer.getFeature(fid)
            if not feat.isValid():
                continue
            changes = {sync_idx: SyncStatusEnum.NEW.value}
            if ts_idx >= 0:
                changes[ts_idx] = now_iso
            attr_changes[fid] = changes
            new_count += 1

        if attr_changes:
            layer.dataProvider().changeAttributeValues(attr_changes)
            layer.triggerRepaint()

        self._pending_edit_fids[layer_id] = {"changed": set(), "added": set()}

        QgsMessageLog.logMessage(
            f"Edit tracking: {modified_count} MODIFIED, {new_count} NEW",
            PLUGIN_NAME, Qgis.Info,
        )
        self.edit_tracking_done.emit()
