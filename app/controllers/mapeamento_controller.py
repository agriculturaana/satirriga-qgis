"""Controller de mapeamentos — catalogo zonal, download, upload V2."""

import json
import os
from urllib.parse import quote

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.core import QgsApplication, QgsVectorLayer, QgsMessageLog, Qgis

from ...infra.config.settings import PLUGIN_NAME
from ...infra.http.client import HttpClient
from ...app.state.store import AppState


class MapeamentoController(QObject):
    """Orquestra operacoes de mapeamento V2 (zonal)."""

    # Signals V2 (zonal)
    zonal_download_completed = pyqtSignal(str, int, object)  # gpkg_path, zonal_id, catalogo_meta
    zonal_upload_completed = pyqtSignal(str, int)    # gpkg_path, zonal_id
    versions_loaded = pyqtSignal(int, dict)          # zonal_id, versions_data
    compare_fgb_ready = pyqtSignal(int, str, bytes)  # zonal_id, batch_uuid, fgb_bytes
    upload_progress = pyqtSignal(dict)               # UploadBatchStatus dict
    conflict_detected = pyqtSignal(str)              # batchUuid
    conflict_data_ready = pyqtSignal(str, bytes)     # batchUuid, response body
    conflict_resolved = pyqtSignal(str)              # batchUuid
    edit_tracking_done = pyqtSignal()                # apos marcar features editadas

    def __init__(self, state: AppState, http_client: HttpClient,
                 config_repo, token_provider=None, parent=None):
        super().__init__(parent)
        self._state = state
        self._http = http_client
        self._config = config_repo
        self._token_provider = token_provider

        # Timer de renovação de editToken (verifica a cada 1h)
        self._renew_timer = QTimer(self)
        self._renew_timer.setInterval(60 * 60 * 1000)  # 1 hora
        self._renew_timer.timeout.connect(self._check_token_renewal)
        self._renew_timer.start()
        self._pending_renew_id = None
        self._pending_renew_zonal_id = None

        # Tracking de requests pendentes
        self._pending_catalogo_id = None
        self._pending_catalogo_homologacao_id = None
        self._pending_parecer_id = None
        self._pending_raster_id = None
        self._pending_raster_meta = {}
        self._pending_conflict_fetch_id = None
        self._pending_conflict_fetch_uuid = None
        self._pending_conflict_resolve_id = None
        self._pending_conflict_resolve_uuid = None
        self._pending_upload_history_id = None
        self._pending_suprimir_id = None
        self._pending_versions_ids = {}   # request_id -> zonal_id
        self._pending_compare_ids = {}    # request_id -> (zonal_id, batch_uuid)
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

    def load_catalogo(self, page=1, size=20, status="CONSOLIDATED", metodo="",
                      mapeamento_id="", author="", descricao="",
                      sort="", direction=""):
        """Carrega catalogo de zonais com paginação, filtros e ordenação server-side."""
        if not self._state.is_authenticated:
            return

        params = f"status={status}&page={page}&size={size}"
        if mapeamento_id:
            params += f"&mapeamentoId={quote(mapeamento_id)}"
        if author:
            params += f"&author={quote(author)}"
        if descricao:
            params += f"&descricao={quote(descricao)}"
        if metodo:
            params += f"&metodo={quote(metodo)}"
        if sort:
            params += f"&sort={quote(sort)}"
        if direction:
            params += f"&direction={quote(direction)}"
        url = self._api_url(f"/zonal/catalogo?{params}")
        self._state.set_loading("catalogo", True)
        self._pending_catalogo_id = self._http.get(url)

    # ----------------------------------------------------------------
    # Request handlers
    # ----------------------------------------------------------------

    def load_catalogo_homologacao(self, status_filter="AGUARDANDO",
                                  mapeamento_id="", author="", descricao="",
                                  page=1, size=20):
        """Carrega catalogo de zonais para homologação com filtros e paginação."""
        if not self._state.is_authenticated:
            return

        params = f"status={status_filter}&page={page}&size={size}"
        if mapeamento_id:
            params += f"&mapeamentoId={quote(mapeamento_id)}"
        if author:
            params += f"&author={quote(author)}"
        if descricao:
            params += f"&descricao={quote(descricao)}"
        url = self._api_url(f"/zonal/catalogo?{params}")
        self._state.set_loading("catalogo_homologacao", True)
        self._pending_catalogo_homologacao_id = self._http.get(url)

    def load_upload_history(self, page=1, size=20, status="", mapeamento_id=""):
        """Carrega histórico de uploads com paginação server-side."""
        if not self._state.is_authenticated:
            return

        params = f"page={page}&size={size}"
        if status:
            params += f"&status={quote(status)}"
        if mapeamento_id:
            params += f"&mapeamentoId={quote(mapeamento_id)}"
        url = self._api_url(f"/zonal/upload/history?{params}")
        self._state.set_loading("upload_history", True)
        self._pending_upload_history_id = self._http.get(url)

    def load_versions(self, zonal_id):
        """Busca versões disponíveis para comparação de um zonal."""
        if not self._state.is_authenticated:
            return
        url = self._api_url(f"/zonal/{zonal_id}/versions")
        req_id = self._http.get(url)
        self._pending_versions_ids[req_id] = zonal_id

    def download_compare_fgb(self, zonal_id, batch_uuid):
        """Baixa FlatGeobuf de uma versão específica para comparação."""
        if not self._state.is_authenticated:
            return
        url = self._api_url(f"/zonal/{zonal_id}/compare?batchUuid={quote(str(batch_uuid))}")
        req_id = self._http.get(url)
        self._pending_compare_ids[req_id] = (zonal_id, batch_uuid)

    def emitir_parecer(self, zonal_id, decisao, motivo=""):
        """Emite parecer de homologacao (aprovar/reprovar/cancelar)."""
        if not self._state.is_authenticated:
            self._state.set_error("parecer", "Nao autenticado")
            return

        user = self._state.user
        if not user or not user.is_homologador:
            self._state.set_error("parecer", "Permissao negada: role 'homologar' requerida")
            return

        url = self._api_url("/consolidado/parecer")
        payload = json.dumps({
            "zonalId": zonal_id,
            "decisao": decisao,
            "motivo": motivo,
        }).encode("utf-8")
        self._state.set_loading("parecer", True)
        self._pending_parecer_id = self._http.post_json(url, payload)

    def suprimir_mapeamento(self, mapeamento_id):
        """Suprime mapeamento (DELETE /api/mapeamento/delete/:id?force=true)."""
        if not self._state.is_authenticated:
            self._state.set_error("suprimir", "Nao autenticado")
            return

        user = self._state.user
        if not user or not user.is_homologador:
            self._state.set_error("suprimir", "Permissao negada: role 'homologar' requerida")
            return

        url = self._api_url(f"/mapeamento/delete/{mapeamento_id}?force=true")
        self._state.set_loading("suprimir", True)
        self._pending_suprimir_id = self._http.delete(url)

    def encerrar_mapeamento(self, mapeamento_id):
        """Encerra mapeamento (POST /api/mapeamento/:id/encerrar)."""
        if not self._state.is_authenticated:
            self._state.set_error("encerrar", "Nao autenticado")
            return

        url = self._api_url(f"/mapeamento/{mapeamento_id}/encerrar")
        self._http.post_json(url, b"{}")

    def _check_token_renewal(self):
        """Verifica sidecars locais e renova tokens com menos de 24h de validade."""
        from datetime import datetime, timezone
        from ...domain.services.gpkg_service import gpkg_base_dir, read_sidecar

        if not self._state.is_authenticated or not self._token_provider:
            return

        base = gpkg_base_dir(self._config.get("gpkg_base_dir"))
        if not os.path.isdir(base):
            return

        now = datetime.now(timezone.utc)
        threshold_hours = 24

        try:
            entries = os.listdir(base)
        except OSError:
            return

        for entry in entries:
            try:
                entry_path = os.path.join(base, entry)
                if not os.path.isdir(entry_path):
                    continue
                for fname in os.listdir(entry_path):
                    if not fname.endswith(".gpkg"):
                        continue
                    try:
                        gpkg = os.path.join(entry_path, fname)
                        sidecar = read_sidecar(gpkg)
                        expires_at = sidecar.get("expiresAt")
                        edit_token = sidecar.get("editToken")
                        zonal_id = sidecar.get("zonalId")
                        if not expires_at or not edit_token or not zonal_id:
                            continue
                        exp_dt = datetime.fromisoformat(
                            expires_at.replace("Z", "+00:00")
                        )
                        remaining = (exp_dt - now).total_seconds() / 3600
                        if 0 < remaining < threshold_hours:
                            self._renew_edit_token(zonal_id, edit_token)
                    except (ValueError, TypeError, OSError):
                        continue
            except OSError:
                continue

    def _renew_edit_token(self, zonal_id, edit_token):
        """Envia POST /api/zonal/:id/renew-token."""
        url = self._api_url(f"/zonal/{zonal_id}/renew-token")
        payload = json.dumps({"editToken": edit_token}).encode("utf-8")
        self._pending_renew_id = self._http.post_json(url, payload)
        self._pending_renew_zonal_id = zonal_id
        QgsMessageLog.logMessage(
            f"Renovando editToken para zonal #{zonal_id}",
            PLUGIN_NAME, Qgis.Info,
        )

    def load_raster_images(self, job_id, metodo_apply):
        """Carrega URLs de tiles raster para um job."""
        if not self._state.is_authenticated:
            return

        url = self._api_url(f"/mapeamento/tilesMetodos?jobId={job_id}")
        self._pending_raster_meta = {"metodo_apply": metodo_apply}
        self._pending_raster_id = self._http.get(url)

    def fetch_conflicts(self, batch_uuid):
        """Busca conflitos de um batch de upload via API assincrona."""
        url = self._api_url(f"/zonal/upload/{batch_uuid}/conflicts")
        self._pending_conflict_fetch_uuid = batch_uuid
        self._pending_conflict_fetch_id = self._http.get(url)

    def resolve_conflicts(self, batch_uuid, decisions):
        """Envia resolucoes de conflitos para o servidor."""
        url = self._api_url(f"/zonal/upload/{batch_uuid}/resolve")
        payload = json.dumps({"decisions": decisions}).encode("utf-8")
        self._pending_conflict_resolve_uuid = batch_uuid
        self._pending_conflict_resolve_id = self._http.post_json(url, payload)

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
                    pagination = {}
                else:
                    items_raw = data.get("data") or data.get("content") or []
                    pagination = data.get("pagination") or {}
                items = [CatalogoItem.from_dict(item) for item in items_raw]
                self._state.catalogo_items = (items, pagination)
                QgsMessageLog.logMessage(
                    f"[Catalogo] {len(items)} zonais carregados"
                    f" (pag {pagination.get('page', '?')}/{pagination.get('totalPages', '?')})",
                    PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear catalogo: {e}\nBody: {body[:500]}",
                    PLUGIN_NAME, Qgis.Warning,
                )
                self._state.set_error("catalogo", f"Erro ao processar catalogo: {e}")

        elif request_id == self._pending_catalogo_homologacao_id:
            self._pending_catalogo_homologacao_id = None
            self._state.set_loading("catalogo_homologacao", False)
            try:
                from ...domain.models.zonal import CatalogoItem
                data = json.loads(body)
                if isinstance(data, list):
                    items_raw = data
                    pagination = {}
                else:
                    items_raw = data.get("data") or data.get("content") or []
                    pagination = data.get("pagination") or {}
                items = [CatalogoItem.from_dict(item) for item in items_raw]
                self._state.catalogo_homologacao_changed.emit(items, pagination)
                QgsMessageLog.logMessage(
                    f"[Homologacao] {len(items)} zonais carregados"
                    f" (pag {pagination.get('page', '?')}/{pagination.get('totalPages', '?')})",
                    PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear catalogo homologacao: {e}",
                    PLUGIN_NAME, Qgis.Warning,
                )
                self._state.set_error("catalogo_homologacao", str(e))

        elif request_id == self._pending_parecer_id:
            self._pending_parecer_id = None
            self._state.set_loading("parecer", False)
            try:
                data = json.loads(body)
                self._state.parecer_emitido.emit(data)
                QgsMessageLog.logMessage(
                    f"[Parecer] Emitido: {data}",
                    PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                self._state.set_error("parecer", str(e))

        elif request_id == self._pending_raster_id:
            self._pending_raster_id = None
            try:
                from ...domain.services.raster_service import build_raster_hierarchy
                data = json.loads(body)
                metodo = self._pending_raster_meta.get("metodo_apply", "")

                # Diagnostico: loga estrutura do primeiro tile
                if isinstance(data, list) and data:
                    sample = data[0]
                    keys = sorted(sample.keys()) if isinstance(sample, dict) else "N/A"
                    QgsMessageLog.logMessage(
                        f"[Raster] tilesMetodos: {len(data)} tiles, "
                        f"metodo={metodo}, keys={keys}",
                        PLUGIN_NAME, Qgis.Info,
                    )

                hierarchy = build_raster_hierarchy(data, metodo)
                self._state.raster_layers_ready.emit(hierarchy)
                total = sum(
                    len(bg.layers)
                    for dg in hierarchy.dates
                    for bg in dg.bands
                )
                QgsMessageLog.logMessage(
                    f"[Raster] {total} camadas em {len(hierarchy.dates)} datas",
                    PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear tiles raster: {e}",
                    PLUGIN_NAME, Qgis.Warning,
                )

        elif request_id == self._pending_conflict_fetch_id:
            self._pending_conflict_fetch_id = None
            batch_uuid = self._pending_conflict_fetch_uuid
            self._pending_conflict_fetch_uuid = None
            self.conflict_data_ready.emit(batch_uuid, body)

        elif request_id == self._pending_conflict_resolve_id:
            self._pending_conflict_resolve_id = None
            batch_uuid = self._pending_conflict_resolve_uuid
            self._pending_conflict_resolve_uuid = None
            QgsMessageLog.logMessage(
                f"[Conflict] Resolucoes enviadas para batch {batch_uuid}",
                PLUGIN_NAME, Qgis.Info,
            )
            self.conflict_resolved.emit(batch_uuid)

        elif request_id == self._pending_upload_history_id:
            self._pending_upload_history_id = None
            self._state.set_loading("upload_history", False)
            try:
                from ...domain.models.upload_batch import UploadHistoryItem
                data = json.loads(body)
                items_raw = data.get("data") or []
                pagination = data.get("pagination") or {}
                items = [UploadHistoryItem.from_dict(item) for item in items_raw]
                self._state.upload_history_changed.emit(items, pagination)
                QgsMessageLog.logMessage(
                    f"[UploadHistory] {len(items)} batches carregados",
                    PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear historico de uploads: {e}",
                    PLUGIN_NAME, Qgis.Warning,
                )
                self._state.set_error("upload_history", str(e))

        elif request_id == self._pending_suprimir_id:
            self._pending_suprimir_id = None
            self._state.set_loading("suprimir", False)
            try:
                data = json.loads(body)
                self._state.mapeamento_suprimido.emit(data)
                QgsMessageLog.logMessage(
                    f"[Suprimir] Mapeamento suprimido: {data}",
                    PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                self._state.set_error("suprimir", str(e))

        elif request_id == self._pending_renew_id:
            self._pending_renew_id = None
            zonal_id = self._pending_renew_zonal_id
            self._pending_renew_zonal_id = None
            try:
                from ...domain.services.gpkg_service import (
                    gpkg_base_dir, gpkg_path_for_zonal, read_sidecar, write_sidecar,
                )
                data = json.loads(body)
                new_expires = data.get("expiresAt")
                if new_expires and zonal_id:
                    base = gpkg_base_dir(self._config.get("gpkg_base_dir"))
                    gpkg = gpkg_path_for_zonal(base, zonal_id)
                    sidecar = read_sidecar(gpkg)
                    sidecar["expiresAt"] = new_expires
                    write_sidecar(gpkg, sidecar)
                    QgsMessageLog.logMessage(
                        f"editToken renovado para zonal #{zonal_id} até {new_expires}",
                        PLUGIN_NAME, Qgis.Info,
                    )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao atualizar sidecar após renovação: {e}",
                    PLUGIN_NAME, Qgis.Warning,
                )

        elif request_id in self._pending_versions_ids:
            zonal_id = self._pending_versions_ids.pop(request_id)
            try:
                data = json.loads(body)
                self.versions_loaded.emit(zonal_id, data)
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear versoes: {e}",
                    PLUGIN_NAME, Qgis.Warning,
                )

        elif request_id in self._pending_compare_ids:
            zonal_id, batch_uuid = self._pending_compare_ids.pop(request_id)
            # body é bytes (FlatGeobuf binário)
            self.compare_fgb_ready.emit(zonal_id, batch_uuid, body)

    def _on_request_error(self, request_id, error_msg):
        if request_id == self._pending_catalogo_id:
            self._pending_catalogo_id = None
            self._state.set_loading("catalogo", False)
            self._state.set_error("catalogo", error_msg)
        elif request_id == self._pending_catalogo_homologacao_id:
            self._pending_catalogo_homologacao_id = None
            self._state.set_loading("catalogo_homologacao", False)
            self._state.set_error("catalogo_homologacao", error_msg)
        elif request_id == self._pending_parecer_id:
            self._pending_parecer_id = None
            self._state.set_loading("parecer", False)
            self._state.set_error("parecer", error_msg)
        elif request_id == self._pending_raster_id:
            self._pending_raster_id = None
            QgsMessageLog.logMessage(
                f"Erro ao carregar tiles raster: {error_msg}",
                PLUGIN_NAME, Qgis.Warning,
            )
        elif request_id == self._pending_conflict_fetch_id:
            self._pending_conflict_fetch_id = None
            self._pending_conflict_fetch_uuid = None
            self._state.set_error("upload", f"Erro ao buscar conflitos: {error_msg}")
        elif request_id == self._pending_conflict_resolve_id:
            self._pending_conflict_resolve_id = None
            self._pending_conflict_resolve_uuid = None
            self._state.set_error("upload", f"Erro ao resolver conflitos: {error_msg}")
        elif request_id == self._pending_suprimir_id:
            self._pending_suprimir_id = None
            self._state.set_loading("suprimir", False)
            self._state.set_error("suprimir", error_msg)
        elif request_id == self._pending_upload_history_id:
            self._pending_upload_history_id = None
            self._state.set_loading("upload_history", False)
            self._state.set_error("upload_history", error_msg)
        elif request_id in self._pending_versions_ids:
            self._pending_versions_ids.pop(request_id)
            self._state.set_error("compare", f"Erro ao buscar versões: {error_msg}")
        elif request_id in self._pending_compare_ids:
            self._pending_compare_ids.pop(request_id)
            self._state.set_error("compare", f"Erro ao baixar versão: {error_msg}")

    # ----------------------------------------------------------------
    # Download Zonal (V2)
    # ----------------------------------------------------------------

    def download_zonal_result(self, zonal_id, catalogo_item=None):
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

        # Metadados do catalogo para enriquecer sidecar
        catalogo_meta = {}
        if catalogo_item:
            catalogo_meta = {
                "mapeamentoId": catalogo_item.mapeamento_id,
                "dataReferencia": catalogo_item.data_referencia,
                "descricao": catalogo_item.descricao,
                "jobId": catalogo_item.job_id,
                "metodoApply": catalogo_item.metodo_apply,
            }

        task = DownloadZonalTask(
            checkout_url=checkout_url,
            download_url=download_url,
            access_token=token,
            gpkg_output_path=output_path,
            zonal_id=zonal_id,
            catalogo_meta=catalogo_meta,
        )

        task.signals.completed.connect(
            lambda success, msg: self._on_zonal_download_completed(
                success, msg, output_path, zonal_id, catalogo_meta
            )
        )
        task.signals.status_message.connect(
            lambda msg: QgsMessageLog.logMessage(msg, PLUGIN_NAME, Qgis.Info)
        )

        self._active_tasks.append(task)
        self._state.set_loading(f"download:{zonal_id}", True)
        QgsApplication.taskManager().addTask(task)

    def _on_zonal_download_completed(self, success, message, gpkg_path, zonal_id,
                                     catalogo_meta=None):
        self._cleanup_finished_tasks()
        self._state.set_loading(f"download:{zonal_id}", False)
        if success:
            self.zonal_download_completed.emit(gpkg_path, zonal_id, catalogo_meta or {})
            QgsMessageLog.logMessage(
                f"Download zonal concluido: {gpkg_path}", PLUGIN_NAME, Qgis.Info,
            )
        else:
            self._state.set_error(f"download:{zonal_id}", message)
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
            layer.dataProvider().forceReload()

    # ----------------------------------------------------------------
    # Edit tracking
    # ----------------------------------------------------------------

    def connect_edit_tracking(self, layer, mapeamento_id=None,
                              metodo_id=None, zonal_id=None):
        """Conecta signals para rastrear edicoes na camada.

        Usa beforeCommitChanges para capturar IDs editados do editBuffer,
        e afterCommitChanges para persistir o _sync_status no GPKG.

        Oculta campos internos (_sync_status, _original_fid, etc.) do
        formulario de atributos do QGIS para evitar que o usuario ou
        o mecanismo "Remember last entered values" sobrescreva valores
        de controle de sync.
        """
        from qgis.core import QgsEditorWidgetSetup
        from ...domain.services.attribute_schema import INTERNAL_FIELDS

        layer_id = layer.id()
        self._pending_edit_fids[layer_id] = {"changed": set()}

        # Oculta campos internos do formulario de atributos
        for field_name in INTERNAL_FIELDS:
            idx = layer.fields().indexOf(field_name)
            if idx >= 0:
                layer.setEditorWidgetSetup(
                    idx, QgsEditorWidgetSetup("Hidden", {})
                )

        layer.beforeCommitChanges.connect(
            lambda: self._capture_edited_fids(layer)
        )
        layer.afterCommitChanges.connect(
            lambda: QTimer.singleShot(0, lambda: self._mark_edited_features(layer))
        )

    def _capture_edited_fids(self, layer):
        """Captura IDs das features alteradas antes do commit.

        Apenas features existentes (FID > 0) sao capturadas aqui.
        Features novas sao detectadas em _mark_edited_features via
        _sync_status NULL, pois os FIDs temporarios negativos do
        editBuffer nao existem apos o commit.

        Acumula FIDs em vez de sobrescrever, para evitar perda de dados
        caso beforeCommitChanges dispare múltiplas vezes antes de
        afterCommitChanges consumir os FIDs.
        """
        layer_id = layer.id()
        changed_fids = set()

        try:
            buf = layer.editBuffer()
            if buf:
                changed_fids.update(buf.changedGeometries().keys())
                changed_fids.update(buf.changedAttributeValues().keys())

                QgsMessageLog.logMessage(
                    f"[EditTrack] beforeCommit: {len(buf.changedGeometries())} geom, "
                    f"{len(buf.changedAttributeValues())} attr, "
                    f"{len(buf.addedFeatures())} added",
                    PLUGIN_NAME, Qgis.Info,
                )
            else:
                QgsMessageLog.logMessage(
                    "[EditTrack] beforeCommit: editBuffer is None",
                    PLUGIN_NAME, Qgis.Warning,
                )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"[EditTrack] erro em _capture_edited_fids: {e}",
                PLUGIN_NAME, Qgis.Warning,
            )

        # Acumula em vez de sobrescrever (previne race condition)
        existing = self._pending_edit_fids.get(layer_id, {}).get("changed", set())
        self._pending_edit_fids[layer_id] = {"changed": existing | changed_fids}

    def _mark_edited_features(self, layer):
        """Marca features editadas como MODIFIED e novas como NEW no GPKG.

        Usa dataProvider().changeAttributeValues() para batch direto no GPKG,
        sem startEditing/commitChanges (evita loop de signals e e O(1) no provider).

        Features novas sao detectadas por dois criterios complementares:
        - _sync_status NULL/vazio (cenario primario apos commit)
        - _original_fid NULL/0 com status != NEW/MODIFIED/UPLOADED (defesa
          contra "Remember last entered values" do QGIS que pode preencher
          _sync_status com valor de feature anterior)
        """
        from ...domain.models.enums import SyncStatusEnum
        from datetime import datetime, timezone

        layer_id = layer.id()
        fid_data = self._pending_edit_fids.pop(layer_id, None)
        changed_fids = fid_data.get("changed", set()) if fid_data else set()

        sync_idx = layer.fields().indexOf("_sync_status")
        ts_idx = layer.fields().indexOf("_sync_timestamp")
        ofid_idx = layer.fields().indexOf("_original_fid")
        if sync_idx < 0:
            QgsMessageLog.logMessage(
                "[EditTrack] campo _sync_status nao encontrado na layer",
                PLUGIN_NAME, Qgis.Warning,
            )
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        trackable = (
            SyncStatusEnum.DOWNLOADED.value,
            SyncStatusEnum.MODIFIED.value,
            SyncStatusEnum.UPLOADED.value,
        )
        already_tracked = (
            SyncStatusEnum.NEW.value,
            SyncStatusEnum.MODIFIED.value,
            SyncStatusEnum.UPLOADED.value,
        )

        # Batch: {fid: {field_idx: new_value, ...}, ...}
        attr_changes = {}
        modified_count = 0
        new_count = 0

        # 1) Features existentes editadas (FIDs capturados no beforeCommit)
        for fid in changed_fids:
            feat = layer.getFeature(fid)
            if not feat.isValid():
                continue
            current_status = feat.attribute(sync_idx)
            if current_status in trackable:
                changes = {sync_idx: SyncStatusEnum.MODIFIED.value}
                if ts_idx >= 0:
                    changes[ts_idx] = now_iso
                attr_changes[fid] = changes
                modified_count += 1

        # 2) Features novas — dois criterios complementares:
        #    a) _sync_status NULL/vazio (cenario primario)
        #    b) _original_fid NULL/0 e status nao e NEW/MODIFIED/UPLOADED
        #       (defesa contra "Remember values" do QGIS preenchendo
        #       _sync_status = DOWNLOADED em features recem-criadas)
        for feat in layer.getFeatures():
            fid = feat.id()
            if fid in attr_changes:
                continue
            status = feat.attribute(sync_idx)
            original_fid = (
                feat.attribute(ofid_idx) if ofid_idx >= 0 else None
            )

            status_is_null = not status
            has_no_server_fid = not original_fid and status not in already_tracked

            if status_is_null or has_no_server_fid:
                changes = {sync_idx: SyncStatusEnum.NEW.value}
                if ts_idx >= 0:
                    changes[ts_idx] = now_iso
                attr_changes[fid] = changes
                new_count += 1

        if attr_changes:
            ok = layer.dataProvider().changeAttributeValues(attr_changes)
            # Invalida cache da layer para refletir mudancas na tabela de atributos
            layer.dataProvider().forceReload()
            layer.triggerRepaint()

            QgsMessageLog.logMessage(
                f"[EditTrack] {modified_count} MODIFIED, {new_count} NEW "
                f"(provider write ok={ok})",
                PLUGIN_NAME, Qgis.Info,
            )
        else:
            QgsMessageLog.logMessage(
                "[EditTrack] nenhuma feature para marcar "
                f"(changed_fids={len(changed_fids)})",
                PLUGIN_NAME, Qgis.Info,
            )

        self._pending_edit_fids[layer_id] = {"changed": set()}
        self.edit_tracking_done.emit()
