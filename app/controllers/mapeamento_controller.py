"""Controller de mapeamentos — listagem, detalhe, download, upload."""

import json

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsApplication, QgsVectorLayer, QgsMessageLog, Qgis

from ...infra.config.settings import PLUGIN_NAME
from ...infra.http.client import HttpClient
from ...domain.services.mapeamento_service import parse_paginated_result, parse_mapeamento
from ...app.state.store import AppState


class MapeamentoController(QObject):
    """Orquestra operacoes de mapeamento."""

    download_completed = pyqtSignal(str, int, int)  # gpkg_path, mapeamento_id, metodo_id
    upload_completed = pyqtSignal(str, int)          # gpkg_path, count

    def __init__(self, state: AppState, http_client: HttpClient,
                 config_repo, token_provider=None, parent=None):
        super().__init__(parent)
        self._state = state
        self._http = http_client
        self._config = config_repo
        self._token_provider = token_provider

        # Tracking de requests pendentes
        self._pending_list_id = None
        self._pending_detail_id = None
        self._active_tasks = []
        self._pending_edit_fids = {}

        # Parametros de listagem atuais
        self._current_page = 0
        self._current_search = ""
        self._current_sort_field = "dataReferencia"
        self._current_sort_order = "desc"

        # Conecta signals do HttpClient
        self._http.request_finished.connect(self._on_request_finished)
        self._http.request_error.connect(self._on_request_error)

    @property
    def current_page(self):
        return self._current_page

    def _api_url(self, path):
        base = self._config.get("api_base_url").rstrip("/")
        return f"{base}{path}"

    # ----------------------------------------------------------------
    # Listagem
    # ----------------------------------------------------------------

    def load_mapeamentos(self, page=None, search=None,
                         sort_field=None, sort_order=None):
        """Carrega lista paginada de mapeamentos."""
        if not self._state.is_authenticated:
            return

        if page is not None:
            self._current_page = page
        if search is not None:
            self._current_search = search
        if sort_field is not None:
            self._current_sort_field = sort_field
        if sort_order is not None:
            self._current_sort_order = sort_order

        page_size = self._config.get("page_size")
        params = (
            f"?includeGeom=false"
            f"&page={self._current_page}"
            f"&size={page_size}"
            f"&sortField={self._current_sort_field}"
            f"&sortOrder={self._current_sort_order}"
        )
        if self._current_search:
            from urllib.parse import quote
            params += f"&search={quote(self._current_search)}"

        url = self._api_url(f"/mapeamento/all{params}")

        self._state.set_loading("mapeamentos", True)
        self._pending_list_id = self._http.get(url)

    def next_page(self):
        result = self._state.mapeamentos
        if result and self._current_page < result.total_pages - 1:
            self.load_mapeamentos(page=self._current_page + 1)

    def previous_page(self):
        if self._current_page > 0:
            self.load_mapeamentos(page=self._current_page - 1)

    def search(self, text):
        """Busca com reset de pagina."""
        self.load_mapeamentos(page=0, search=text)

    def sort(self, field, order):
        self.load_mapeamentos(page=0, sort_field=field, sort_order=order)

    # ----------------------------------------------------------------
    # Detalhe
    # ----------------------------------------------------------------

    def load_detail(self, mapeamento_id):
        """Carrega detalhe de um mapeamento."""
        if not self._state.is_authenticated:
            return

        url = self._api_url(f"/mapeamento/{mapeamento_id}")
        self._state.set_loading("detail", True)
        self._pending_detail_id = self._http.get(url)

    # ----------------------------------------------------------------
    # Request handlers
    # ----------------------------------------------------------------

    def _on_request_finished(self, request_id, status_code, body):
        if request_id == self._pending_list_id:
            self._pending_list_id = None
            self._state.set_loading("mapeamentos", False)
            try:
                data = json.loads(body)
                QgsMessageLog.logMessage(
                    f"[Mapeamentos] JSON keys: {list(data.keys())}, "
                    f"content items: {len(data.get('content', []))}",
                    PLUGIN_NAME, Qgis.Info,
                )
                result = parse_paginated_result(data)
                QgsMessageLog.logMessage(
                    f"[Mapeamentos] Parsed: {len(result.content)} mapeamentos, "
                    f"page={result.page}, totalPages={result.total_pages}",
                    PLUGIN_NAME, Qgis.Info,
                )
                self._state.mapeamentos = result
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear mapeamentos: {e}\nBody: {body[:500]}",
                    PLUGIN_NAME, Qgis.Warning,
                )
                self._state.set_error("mapeamentos", f"Erro ao processar dados: {e}")

        elif request_id == self._pending_detail_id:
            self._pending_detail_id = None
            self._state.set_loading("detail", False)
            try:
                data = json.loads(body)
                mapeamento = parse_mapeamento(data)
                self._state.selected_mapeamento = mapeamento
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear detalhe: {e}",
                    PLUGIN_NAME, Qgis.Warning,
                )
                self._state.set_error("detail", f"Erro ao processar detalhe: {e}")

    def _on_request_error(self, request_id, error_msg):
        if request_id == self._pending_list_id:
            self._pending_list_id = None
            self._state.set_loading("mapeamentos", False)
            self._state.set_error("mapeamentos", error_msg)

        elif request_id == self._pending_detail_id:
            self._pending_detail_id = None
            self._state.set_loading("detail", False)
            self._state.set_error("detail", error_msg)

    # ----------------------------------------------------------------
    # Download
    # ----------------------------------------------------------------

    def download_classification(self, mapeamento_id, metodo_id):
        """Inicia download da classificacao de um metodo via QgsTask."""
        from ...infra.tasks.download_task import DownloadClassificationTask
        from ...domain.services.gpkg_service import gpkg_path, gpkg_base_dir

        if not self._state.is_authenticated or not self._token_provider:
            self._state.set_error("download", "Nao autenticado")
            return

        download_url = self._api_url(
            f"/mapeamento/metodo-geometria/metodo/{metodo_id}/download-shp"
        )
        base_dir = gpkg_base_dir(self._config.get("gpkg_base_dir"))
        output_path = gpkg_path(base_dir, mapeamento_id, metodo_id)

        token = self._token_provider()
        if not token:
            self._state.set_error("download", "Token nao disponivel")
            return

        task = DownloadClassificationTask(
            download_url=download_url,
            access_token=token,
            gpkg_output_path=output_path,
            mapeamento_id=mapeamento_id,
            metodo_id=metodo_id,
        )

        task.signals.completed.connect(
            lambda success, msg: self._on_download_completed(
                success, msg, output_path, mapeamento_id, metodo_id
            )
        )
        task.signals.status_message.connect(
            lambda msg: QgsMessageLog.logMessage(msg, PLUGIN_NAME, Qgis.Info)
        )

        self._active_tasks.append(task)
        self._state.set_loading("download", True)
        QgsApplication.taskManager().addTask(task)

    def _cleanup_finished_tasks(self):
        """Remove tasks finalizadas da lista de tasks ativas."""
        self._active_tasks = [
            t for t in self._active_tasks
            if t.status() not in (t.Complete, t.Terminated)
        ]

    def _on_download_completed(self, success, message, gpkg_path,
                                mapeamento_id, metodo_id):
        self._cleanup_finished_tasks()
        self._state.set_loading("download", False)
        if success:
            self.download_completed.emit(gpkg_path, mapeamento_id, metodo_id)
            QgsMessageLog.logMessage(
                f"Download concluido: {gpkg_path}", PLUGIN_NAME, Qgis.Info,
            )
        else:
            self._state.set_error("download", message)
            QgsMessageLog.logMessage(
                f"Download falhou: {message}", PLUGIN_NAME, Qgis.Warning,
            )

    # ----------------------------------------------------------------
    # Upload
    # ----------------------------------------------------------------

    def upload_classification(self, gpkg_path, mapeamento_id, metodo_id):
        """Inicia upload de features modificadas via QgsTask."""
        from ...infra.tasks.upload_task import UploadClassificationTask

        if not self._state.is_authenticated or not self._token_provider:
            self._state.set_error("upload", "Nao autenticado")
            return

        upload_url = self._api_url("/mapeamento/metodo-geometria/upload")
        token = self._token_provider()
        if not token:
            self._state.set_error("upload", "Token nao disponivel")
            return

        task = UploadClassificationTask(
            upload_url=upload_url,
            access_token=token,
            gpkg_source_path=gpkg_path,
            mapeamento_id=mapeamento_id,
            metodo_id=metodo_id,
        )

        task.signals.completed.connect(
            lambda success, msg: self._on_upload_completed(
                success, msg, gpkg_path
            )
        )
        task.signals.status_message.connect(
            lambda msg: QgsMessageLog.logMessage(msg, PLUGIN_NAME, Qgis.Info)
        )

        self._active_tasks.append(task)
        self._state.set_loading("upload", True)
        QgsApplication.taskManager().addTask(task)

    def _on_upload_completed(self, success, message, gpkg_path):
        self._cleanup_finished_tasks()
        self._state.set_loading("upload", False)
        if success:
            # Conta features MODIFIED antes de marcar como UPLOADED
            count = self._count_modified(gpkg_path)
            self._mark_uploaded(gpkg_path)
            self.upload_completed.emit(gpkg_path, count)
            QgsMessageLog.logMessage(
                f"Upload concluido: {gpkg_path}", PLUGIN_NAME, Qgis.Info,
            )
        else:
            self._state.set_error("upload", message)
            QgsMessageLog.logMessage(
                f"Upload falhou: {message}", PLUGIN_NAME, Qgis.Warning,
            )

    def _count_modified(self, gpkg_path):
        """Conta features com status MODIFIED no GPKG."""
        from ...domain.models.enums import SyncStatusEnum

        layer = QgsVectorLayer(gpkg_path, "count_modified", "ogr")
        if not layer.isValid():
            return 0

        sync_idx = layer.fields().indexOf("_sync_status")
        if sync_idx < 0:
            return 0

        count = 0
        for feat in layer.getFeatures():
            if feat.attribute(sync_idx) == SyncStatusEnum.MODIFIED.value:
                count += 1
        return count

    def _mark_uploaded(self, gpkg_path):
        """Marca features MODIFIED como UPLOADED no GPKG."""
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
        layer.startEditing()
        for feat in layer.getFeatures():
            if feat.attribute(sync_idx) == SyncStatusEnum.MODIFIED.value:
                layer.changeAttributeValue(feat.id(), sync_idx, SyncStatusEnum.UPLOADED.value)
                if ts_idx >= 0:
                    layer.changeAttributeValue(feat.id(), ts_idx, now_iso)
        layer.commitChanges()

    # ----------------------------------------------------------------
    # Edit tracking
    # ----------------------------------------------------------------

    def connect_edit_tracking(self, layer, mapeamento_id, metodo_id):
        """Conecta signals para rastrear edicoes na camada.

        Usa beforeCommitChanges para capturar IDs editados do editBuffer,
        e afterCommitChanges para persistir o _sync_status no GPKG.
        """
        # Armazena IDs pendentes por layer id para uso entre signals
        layer_id = layer.id()
        self._pending_edit_fids[layer_id] = set()

        layer.beforeCommitChanges.connect(
            lambda: self._capture_edited_fids(layer)
        )
        layer.afterCommitChanges.connect(
            lambda: self._mark_edited_features(layer)
        )

    def _capture_edited_fids(self, layer):
        """Captura IDs das features alteradas antes do commit."""
        layer_id = layer.id()
        fids = set()

        buf = layer.editBuffer()
        if buf:
            # Features com geometria alterada
            fids.update(buf.changedGeometries().keys())
            # Features com atributos alterados
            fids.update(buf.changedAttributeValues().keys())

        self._pending_edit_fids[layer_id] = fids

    def _mark_edited_features(self, layer):
        """Marca features editadas como MODIFIED no GPKG."""
        from ...domain.models.enums import SyncStatusEnum
        from datetime import datetime, timezone

        layer_id = layer.id()
        fids = self._pending_edit_fids.get(layer_id, set())
        if not fids:
            return

        sync_idx = layer.fields().indexOf("_sync_status")
        ts_idx = layer.fields().indexOf("_sync_timestamp")
        if sync_idx < 0:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        layer.startEditing()
        for fid in fids:
            feat = layer.getFeature(fid)
            if not feat.isValid():
                continue
            current_status = feat.attribute(sync_idx)
            # Nao sobrescreve UPLOADED — usuario pode querer re-upload
            if current_status in (SyncStatusEnum.DOWNLOADED.value,
                                  SyncStatusEnum.MODIFIED.value):
                layer.changeAttributeValue(fid, sync_idx, SyncStatusEnum.MODIFIED.value)
                if ts_idx >= 0:
                    layer.changeAttributeValue(fid, ts_idx, now_iso)
        layer.commitChanges()

        # Limpa fids pendentes
        self._pending_edit_fids[layer_id] = set()

        QgsMessageLog.logMessage(
            f"Edit tracking: {len(fids)} feature(s) marcada(s) como MODIFIED",
            PLUGIN_NAME, Qgis.Info,
        )
