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
    overlay_data_ready = pyqtSignal(int, dict)        # zonal_id, overlay_data
    notifications_loaded = pyqtSignal(list)           # List[dict] notificações
    pareceres_loaded = pyqtSignal(int, list)          # mapeamento_id, List[dict] pareceres

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
        self._pending_encerrar_id = None
        self._pending_encerrar_mapeamento_id = None
        self._pending_reprocess_id = None
        self._pending_reprocess_zonal_id = None
        self._pending_finalizar_zonal_request_id = None
        self._pending_finalizar_zonal_id = None
        self._pending_poll_ids = {}      # request_id -> zonal_id
        self._polling_zonals = {}        # zonal_id -> {"request_id": None, "errors": 0}
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(3000)
        self._poll_timer.timeout.connect(self._poll_active_zonals)
        self._pending_overlay_ids = {}   # request_id -> zonal_id
        self._pending_versions_ids = {}   # request_id -> zonal_id
        self._pending_compare_ids = {}    # request_id -> (zonal_id, batch_uuid)
        self._pending_mascara_ids = {}   # request_id -> mapeamento_id
        self._pending_notifications_id = None
        self._pending_mark_read_id = None
        self._pending_pareceres_id = None
        self._pending_pareceres_mapeamento_id = None
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
                      sort="", direction="", only_mine=False):
        """Carrega catalogo de zonais com paginação, filtros e ordenação server-side."""
        if not self._state.is_authenticated:
            return

        params = f"status={status}&page={page}&size={size}"
        if only_mine:
            params += "&onlyMine=true"
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

    def load_notifications(self, size=10):
        """Carrega notificações recentes do usuário."""
        if not self._state.is_authenticated:
            return
        url = self._api_url(f"/notificacoes?page=1&size={size}")
        self._pending_notifications_id = self._http.get(url)

    def mark_notification_read(self, notif_id):
        """Marca notificação como lida."""
        if not self._state.is_authenticated:
            return
        url = self._api_url(f"/notificacoes/{notif_id}/lida")
        self._pending_mark_read_id = self._http.patch(url)

    def load_pareceres(self, mapeamento_id):
        """Busca histórico de pareceres de um mapeamento."""
        if not self._state.is_authenticated:
            return
        url = self._api_url(f"/parecer/by-mapeamento/{mapeamento_id}")
        self._pending_pareceres_mapeamento_id = mapeamento_id
        self._pending_pareceres_id = self._http.get(url)

    # ----------------------------------------------------------------
    # Request handlers
    # ----------------------------------------------------------------

    def load_catalogo_homologacao(self, status_filter="AGUARDANDO",
                                  mapeamento_id="", author="", descricao="",
                                  page=1, size=20,
                                  sort="processedAt", direction="desc"):
        """Carrega catalogo de zonais para homologação com filtros e paginação."""
        if not self._state.is_authenticated:
            return

        params = f"status={status_filter}&page={page}&size={size}&sort={sort}&direction={direction}"
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

    def fetch_overlay_data(self, zonal_id):
        """Busca dados de overlay (municipio, UF, bacia, empreendimentos) para um zonal."""
        if not self._state.is_authenticated:
            return
        url = self._api_url(f"/zonal/{zonal_id}/overlay-data")
        req_id = self._http.get(url)
        self._pending_overlay_ids[req_id] = zonal_id

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
        self._pending_encerrar_mapeamento_id = mapeamento_id
        self._pending_encerrar_id = self._http.post_json(url, b"{}")

    def reprocess_overlay(self, zonal_id):
        """Dispara reprocessamento de overlay (POST /api/zonal/:id/reprocess-overlay)."""
        if not self._state.is_authenticated:
            self._state.set_error("reprocess", "Nao autenticado")
            return

        url = self._api_url(f"/zonal/{zonal_id}/reprocess-overlay")
        self._state.set_loading("reprocess", True)
        self._pending_reprocess_id = self._http.post_json(url, b"{}")
        self._pending_reprocess_zonal_id = zonal_id

    # ----------------------------------------------------------------
    # Polling de status do zonal (reprocessamento)
    # ----------------------------------------------------------------

    def start_polling_zonal(self, zonal_id):
        """Inicia polling de status para um zonal em reprocessamento."""
        if zonal_id not in self._polling_zonals:
            self._polling_zonals[zonal_id] = {"request_id": None, "errors": 0}
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def stop_polling_zonal(self, zonal_id):
        """Para polling de um zonal específico."""
        self._polling_zonals.pop(zonal_id, None)
        # Remove request pendente associada
        stale = [rid for rid, zid in self._pending_poll_ids.items() if zid == zonal_id]
        for rid in stale:
            self._pending_poll_ids.pop(rid, None)
        if not self._polling_zonals and self._poll_timer.isActive():
            self._poll_timer.stop()

    def is_polling(self, zonal_id):
        """Retorna True se o zonal está sendo monitorado."""
        return zonal_id in self._polling_zonals

    def _poll_active_zonals(self):
        """Slot do QTimer: dispara GET /api/zonal/:id/status para cada zonal ativo."""
        if not self._state.is_authenticated:
            return
        for zonal_id, entry in list(self._polling_zonals.items()):
            if entry["request_id"] is not None:
                continue  # request em voo, aguardar resposta
            url = self._api_url(f"/zonal/{zonal_id}/status")
            request_id = self._http.get(url)
            entry["request_id"] = request_id
            self._pending_poll_ids[request_id] = zonal_id

    def cleanup_polling(self):
        """Para todo polling. Chamado no unload do plugin."""
        if self._poll_timer.isActive():
            self._poll_timer.stop()
        self._polling_zonals.clear()
        self._pending_poll_ids.clear()

    # ----------------------------------------------------------------
    # Finalizar zonal (enviar para homologação)
    # ----------------------------------------------------------------

    def finalizar_zonal(self, zonal_id):
        """Finaliza zonal (POST /api/zonal/:id/finalizar) para enviar à homologação."""
        if not self._state.is_authenticated:
            self._state.set_error("finalizar_zonal", "Nao autenticado")
            return

        url = self._api_url(f"/zonal/{zonal_id}/finalizar")
        self._state.set_loading("finalizar_zonal", True)
        self._pending_finalizar_zonal_request_id = self._http.post_json(url, b"{}")
        self._pending_finalizar_zonal_id = zonal_id

    # ----------------------------------------------------------------
    # Token renewal
    # ----------------------------------------------------------------

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

    def load_raster_images(self, job_id, metodo_apply, gpkg_path=None):
        """Carrega URLs de tiles raster para um job."""
        if not self._state.is_authenticated:
            return

        url = self._api_url(f"/mapeamento/tilesMetodos?jobId={job_id}")
        self._pending_raster_meta = {
            "metodo_apply": metodo_apply,
            "gpkg_path": gpkg_path,
        }
        self._pending_raster_id = self._http.get(url)

    def load_mascara(self, mapeamento_id):
        """Busca geometria do mapeamento para camada Mascara/ROI."""
        if not self._state.is_authenticated:
            return
        url = self._api_url(f"/mapeamento/{mapeamento_id}")
        req_id = self._http.get(url)
        self._pending_mascara_ids[req_id] = mapeamento_id

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
                from ...domain.services.gpkg_service import read_sidecar
                data = json.loads(body)
                metodo = self._pending_raster_meta.get("metodo_apply", "")
                gpkg_path = self._pending_raster_meta.get("gpkg_path")

                # Lê sidecar para config de visualização por mapeamento
                sidecar = read_sidecar(gpkg_path) if gpkg_path else {}

                # Diagnostico: loga estrutura do primeiro tile
                if isinstance(data, list) and data:
                    sample = data[0]
                    keys = sorted(sample.keys()) if isinstance(sample, dict) else "N/A"
                    QgsMessageLog.logMessage(
                        f"[Raster] tilesMetodos: {len(data)} tiles, "
                        f"metodo={metodo}, keys={keys}",
                        PLUGIN_NAME, Qgis.Info,
                    )

                hierarchy = build_raster_hierarchy(data, metodo, sidecar)
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

        elif request_id == self._pending_encerrar_id:
            self._pending_encerrar_id = None
            mid = self._pending_encerrar_mapeamento_id
            self._pending_encerrar_mapeamento_id = None
            try:
                data = json.loads(body)
                if status_code < 300:
                    msg = data.get("message", "Mapeamento encerrado")
                    self._state.mapeamento_encerrado.emit(
                        {"mapeamentoId": mid, "message": msg}
                    )
                    QgsMessageLog.logMessage(
                        f"[Encerrar] Mapeamento #{mid} encerrado: {msg}",
                        PLUGIN_NAME, Qgis.Info,
                    )
                else:
                    detail = data.get("message") or data.get("error") or body[:200]
                    self._state.set_error("encerrar", detail)
            except Exception as e:
                self._state.set_error("encerrar", str(e))

        elif request_id == self._pending_reprocess_id:
            self._pending_reprocess_id = None
            zid = self._pending_reprocess_zonal_id
            self._pending_reprocess_zonal_id = None
            self._state.set_loading("reprocess", False)
            try:
                data = json.loads(body)
                if status_code < 300:
                    msg = data.get("message", "Reprocessamento iniciado")
                    self.start_polling_zonal(zid)
                    self._state.reprocess_overlay_done.emit(zid, msg)
                    QgsMessageLog.logMessage(
                        f"[Reprocess] Overlay zonal {zid}: {msg} (polling iniciado)",
                        PLUGIN_NAME, Qgis.Info,
                    )
                else:
                    detail = data.get("message") or data.get("error") or body[:200]
                    self._state.set_error("reprocess", detail)
            except Exception as e:
                self._state.set_error("reprocess", str(e))

        elif request_id == self._pending_finalizar_zonal_request_id:
            self._pending_finalizar_zonal_request_id = None
            zid = self._pending_finalizar_zonal_id
            self._pending_finalizar_zonal_id = None
            self._state.set_loading("finalizar_zonal", False)
            try:
                data = json.loads(body)
                if status_code < 300:
                    new_status = data.get("status", "AGUARDANDO")
                    self._state.zonal_finalizado.emit(zid, new_status)
                    QgsMessageLog.logMessage(
                        f"[Finalizar] Zonal {zid} → {new_status}",
                        PLUGIN_NAME, Qgis.Info,
                    )
                else:
                    detail = data.get("message") or data.get("error") or body[:200]
                    self._state.set_error("finalizar_zonal", detail)
            except Exception as e:
                self._state.set_error("finalizar_zonal", str(e))

        elif request_id in self._pending_poll_ids:
            zid = self._pending_poll_ids.pop(request_id)
            if zid in self._polling_zonals:
                self._polling_zonals[zid]["request_id"] = None
                self._polling_zonals[zid]["errors"] = 0
            try:
                data = json.loads(body)
                zonal_status = data.get("status", "")
                self._state.zonal_status_polled.emit(zid, zonal_status)
                # Parar polling se saiu dos estados intermediários
                _intermediate = {"PROCESSING", "OVERLAID", "CREATED", "CONSOLIDATING"}
                if zonal_status not in _intermediate:
                    self.stop_polling_zonal(zid)
                    QgsMessageLog.logMessage(
                        f"[Poll] Zonal {zid} finalizou reprocessamento: {zonal_status}",
                        PLUGIN_NAME, Qgis.Info,
                    )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"[Poll] Erro ao parsear status do zonal {zid}: {e}",
                    PLUGIN_NAME, Qgis.Warning,
                )

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

        elif request_id in self._pending_overlay_ids:
            zonal_id = self._pending_overlay_ids.pop(request_id)
            try:
                data = json.loads(body)
                # A API pode retornar {data: {geomId: {...}}} ou diretamente {geomId: {...}}
                overlay = data.get("data", data) if isinstance(data, dict) else {}
                QgsMessageLog.logMessage(
                    f"[Overlay] zonal {zonal_id}: {len(overlay)} chaves, "
                    f"keys_sample={list(overlay.keys())[:5]}",
                    PLUGIN_NAME, Qgis.Info,
                )
                self.overlay_data_ready.emit(zonal_id, overlay)
            except Exception as e:
                body_preview = body[:300].decode("utf-8", errors="replace") if body else "(vazio)"
                QgsMessageLog.logMessage(
                    f"Erro ao parsear overlay data para zonal {zonal_id}: {e}\n"
                    f"Body preview: {body_preview}",
                    PLUGIN_NAME, Qgis.Warning,
                )

        elif request_id in self._pending_mascara_ids:
            mapeamento_id = self._pending_mascara_ids.pop(request_id)
            try:
                from ...domain.models.mapeamento import Mapeamento
                data = json.loads(body)
                mapeamento = Mapeamento.from_dict(data)
                if mapeamento.geom:
                    self._state.mascara_layer_ready.emit(mapeamento_id, mapeamento.geom)
                    QgsMessageLog.logMessage(
                        f"[Mascara] Geometria carregada para mapeamento #{mapeamento_id}",
                        PLUGIN_NAME, Qgis.Info,
                    )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear mascara do mapeamento #{mapeamento_id}: {e}",
                    PLUGIN_NAME, Qgis.Warning,
                )

        elif request_id == self._pending_notifications_id:
            self._pending_notifications_id = None
            try:
                data = json.loads(body)
                items = data.get("data") or []
                self.notifications_loaded.emit(items)
                QgsMessageLog.logMessage(
                    f"[Notificacoes] {len(items)} notificação(ões) carregada(s)",
                    PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear notificacoes: {e}",
                    PLUGIN_NAME, Qgis.Warning,
                )

        elif request_id == self._pending_pareceres_id:
            self._pending_pareceres_id = None
            mid = self._pending_pareceres_mapeamento_id
            self._pending_pareceres_mapeamento_id = None
            try:
                data = json.loads(body)
                items = data.get("data") or data if isinstance(data, list) else []
                self.pareceres_loaded.emit(mid, items)
                QgsMessageLog.logMessage(
                    f"[Pareceres] {len(items)} parecer(es) para mapeamento #{mid}",
                    PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao parsear pareceres: {e}",
                    PLUGIN_NAME, Qgis.Warning,
                )

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
        elif request_id == self._pending_encerrar_id:
            self._pending_encerrar_id = None
            self._pending_encerrar_mapeamento_id = None
            self._state.set_error("encerrar", error_msg)
        elif request_id == self._pending_reprocess_id:
            self._pending_reprocess_id = None
            self._pending_reprocess_zonal_id = None
            self._state.set_loading("reprocess", False)
            self._state.set_error("reprocess", error_msg)
        elif request_id == self._pending_finalizar_zonal_request_id:
            self._pending_finalizar_zonal_request_id = None
            self._pending_finalizar_zonal_id = None
            self._state.set_loading("finalizar_zonal", False)
            self._state.set_error("finalizar_zonal", error_msg)
        elif request_id in self._pending_poll_ids:
            zid = self._pending_poll_ids.pop(request_id)
            if zid in self._polling_zonals:
                self._polling_zonals[zid]["request_id"] = None
                self._polling_zonals[zid]["errors"] += 1
                if self._polling_zonals[zid]["errors"] >= 5:
                    self.stop_polling_zonal(zid)
                    self._state.set_error(
                        "reprocess",
                        f"Polling do zonal {zid} falhou 5 vezes consecutivas."
                    )
                    QgsMessageLog.logMessage(
                        f"[Poll] Zonal {zid}: 5 erros consecutivos, polling encerrado",
                        PLUGIN_NAME, Qgis.Warning,
                    )
        elif request_id == self._pending_pareceres_id:
            self._pending_pareceres_id = None
            self._pending_pareceres_mapeamento_id = None
            QgsMessageLog.logMessage(
                f"Erro ao buscar pareceres: {error_msg}",
                PLUGIN_NAME, Qgis.Warning,
            )
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
        elif request_id in self._pending_overlay_ids:
            zonal_id = self._pending_overlay_ids.pop(request_id)
            QgsMessageLog.logMessage(
                f"Erro ao buscar overlay data para zonal {zonal_id}: {error_msg}",
                PLUGIN_NAME, Qgis.Warning,
            )
        elif request_id in self._pending_mascara_ids:
            self._pending_mascara_ids.pop(request_id)
            QgsMessageLog.logMessage(
                f"Erro ao carregar mascara: {error_msg}",
                PLUGIN_NAME, Qgis.Warning,
            )

    # ----------------------------------------------------------------
    # Download Zonal (V2)
    # ----------------------------------------------------------------

    def download_zonal_result(self, zonal_id, catalogo_item=None,
                             read_only=False):
        """Inicia download do resultado zonal via checkout + FlatGeobuf.

        Se read_only=True, pula checkout (sem lock de edição) e marca o
        GPKG como somente leitura no sidecar.
        """
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
            read_only=read_only,
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

        expires_at = sidecar.get("expiresAt", "?")
        QgsMessageLog.logMessage(
            f"[Upload] zonal={zonal_id} version={zonal_version} "
            f"token={edit_token[:8]}... expires={expires_at}",
            PLUGIN_NAME, Qgis.Info,
        )

        upload_url = self._api_url(f"/zonal/{zonal_id}/upload")
        checkout_url = self._api_url(f"/zonal/{zonal_id}/checkout")

        # URL para monitorar reprocessamento pos-upload (status leve do zonal)
        zonal_status_url = self._api_url(f"/zonal/{zonal_id}/status")

        task = UploadZonalTask(
            upload_url=upload_url,
            checkout_url=checkout_url,
            access_token=token,
            gpkg_source_path=gpkg_path,
            zonal_id=zonal_id,
            edit_token=edit_token,
            expected_version=zonal_version,
            conflict_strategy=conflict_strategy,
            zonal_status_url=zonal_status_url,
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
        deleted_fids = []
        for feat in layer.getFeatures():
            status = feat.attribute(sync_idx)
            if status in (SyncStatusEnum.MODIFIED.value, SyncStatusEnum.NEW.value):
                changes = {sync_idx: SyncStatusEnum.UPLOADED.value}
                if ts_idx >= 0:
                    changes[ts_idx] = now_iso
                attr_changes[feat.id()] = changes
            elif status == SyncStatusEnum.DELETED.value:
                # Tombstones ja processados pelo servidor — remover do GPKG
                deleted_fids.append(feat.id())

        provider = layer.dataProvider()
        if attr_changes:
            provider.changeAttributeValues(attr_changes)
        if deleted_fids:
            provider.deleteFeatures(deleted_fids)
        if attr_changes or deleted_fids:
            provider.forceReload()

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
        self._pending_edit_fids[layer_id] = {"changed": set(), "deleted_originals": []}

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
        """Captura IDs das features alteradas e deletadas antes do commit.

        Apenas features existentes (FID > 0) sao capturadas aqui.
        Features novas sao detectadas em _mark_edited_features via
        _sync_status NULL, pois os FIDs temporarios negativos do
        editBuffer nao existem apos o commit.

        Features deletadas sao capturadas aqui (antes do commit) pois
        apos o commit elas deixam de existir no GeoPackage. Apenas
        features com _original_fid valido sao rastreadas (features
        novas deletadas nunca existiram no servidor).

        Acumula FIDs em vez de sobrescrever, para evitar perda de dados
        caso beforeCommitChanges dispare múltiplas vezes antes de
        afterCommitChanges consumir os FIDs.
        """
        layer_id = layer.id()
        changed_fids = set()
        deleted_originals = []  # lista de _original_fid de features deletadas

        try:
            buf = layer.editBuffer()
            if buf:
                changed_fids.update(buf.changedGeometries().keys())
                changed_fids.update(buf.changedAttributeValues().keys())

                # Captura _original_fid de features a serem deletadas.
                # Usa dataProvider().getFeatures() para ler direto do GPKG,
                # pois layer.getFeature() retorna feature invalida quando
                # o edit buffer ja marcou a feature como deletada.
                deleted_fids = buf.deletedFeatureIds()
                if deleted_fids:
                    from qgis.core import QgsFeatureRequest
                    ofid_idx = layer.fields().indexOf("_original_fid")
                    if ofid_idx >= 0:
                        req = QgsFeatureRequest().setFilterFids(deleted_fids)
                        for feat in layer.dataProvider().getFeatures(req):
                            original_fid = feat.attribute(ofid_idx)
                            # So rastreia deleções de features do servidor
                            # (original_fid > 0; features novas tem 0 ou NULL)
                            if original_fid is not None and original_fid != 0:
                                deleted_originals.append(original_fid)

                QgsMessageLog.logMessage(
                    f"[EditTrack] beforeCommit: {len(buf.changedGeometries())} geom, "
                    f"{len(buf.changedAttributeValues())} attr, "
                    f"{len(buf.addedFeatures())} added, "
                    f"{len(deleted_fids)} deleted (fids={list(deleted_fids)}, "
                    f"{len(deleted_originals)} do servidor, "
                    f"original_fids={deleted_originals})",
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
        existing = self._pending_edit_fids.get(layer_id, {})
        prev_changed = existing.get("changed", set())
        prev_deleted = existing.get("deleted_originals", [])
        self._pending_edit_fids[layer_id] = {
            "changed": prev_changed | changed_fids,
            "deleted_originals": prev_deleted + deleted_originals,
        }

    def _mark_edited_features(self, layer):
        """Marca features editadas como MODIFIED, novas como NEW,
        e insere tombstones DELETED para features removidas.

        Usa dataProvider() para batch direto no GPKG,
        sem startEditing/commitChanges (evita loop de signals).

        Features novas: _sync_status NULL ou _original_fid NULL/0.
        Features deletadas: tombstones sem geometria inseridos via
        dataProvider().addFeatures() com _sync_status=DELETED e
        _original_fid preservado para o servidor processar a remoção.
        """
        from ...domain.models.enums import SyncStatusEnum
        from datetime import datetime, timezone
        from qgis.core import QgsFeature

        layer_id = layer.id()
        fid_data = self._pending_edit_fids.pop(layer_id, None)
        changed_fids = fid_data.get("changed", set()) if fid_data else set()
        deleted_originals = fid_data.get("deleted_originals", []) if fid_data else []

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
            layer.dataProvider().forceReload()
            layer.triggerRepaint()

            QgsMessageLog.logMessage(
                f"[EditTrack] {modified_count} MODIFIED, {new_count} NEW "
                f"(provider write ok={ok})",
                PLUGIN_NAME, Qgis.Info,
            )

        # 3) Tombstones para features deletadas
        #    Insere features sem geometria com _sync_status=DELETED
        #    e _original_fid preservado. O servidor usa _original_fid
        #    para identificar qual feature remover.
        deleted_count = 0
        if deleted_originals and ofid_idx >= 0:
            provider = layer.dataProvider()
            fields = layer.fields()
            tombstones = []

            for original_fid in deleted_originals:
                tomb = QgsFeature(fields)
                tomb.setAttribute(sync_idx, SyncStatusEnum.DELETED.value)
                tomb.setAttribute(ofid_idx, original_fid)
                if ts_idx >= 0:
                    tomb.setAttribute(ts_idx, now_iso)
                tombstones.append(tomb)

            ok, added = provider.addFeatures(tombstones)
            if ok:
                deleted_count = len(tombstones)
                provider.forceReload()
                layer.triggerRepaint()

            QgsMessageLog.logMessage(
                f"[EditTrack] {deleted_count} tombstones DELETED inseridos "
                f"(original_fids={deleted_originals}, provider write ok={ok})",
                PLUGIN_NAME, Qgis.Info,
            )

        if not attr_changes and not deleted_originals:
            QgsMessageLog.logMessage(
                "[EditTrack] nenhuma feature para marcar "
                f"(changed_fids={len(changed_fids)})",
                PLUGIN_NAME, Qgis.Info,
            )

        self._pending_edit_fids[layer_id] = {
            "changed": set(), "deleted_originals": [],
        }
        self.edit_tracking_done.emit()
