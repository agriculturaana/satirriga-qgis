import os

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsMessageLog, Qgis

from . import resources  # noqa: F401 — registra icone no Qt Resource System
from .infra.config.settings import PLUGIN_NAME
from .infra.config.repository import ConfigRepository
from .infra.http.auth_interceptor import AuthInterceptor
from .infra.http.client import HttpClient
from .app.state.store import AppState
from .app.controllers.auth_controller import AuthController
from .ui.dock import SatIrrigaDock
from .app.controllers.mapeamento_controller import MapeamentoController
from .ui.widgets.session_header import SessionHeader
from .ui.widgets.mapeamentos_tab import MapeamentosTab
from .ui.widgets.camadas_tab import CamadasTab
from .ui.widgets.config_tab import ConfigTab
from .ui.widgets.logs_tab import LogsTab
from .ui.widgets.home_tab import HomeTab
from .app.controllers.config_controller import ConfigController


class SatIrrigaPlugin:
    """Plugin controller — ponto de entrada do QGIS (initGui/unload/run)."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)

        # Locale / i18n
        locale = QSettings().value("locale/userLocale", "pt_BR")
        if locale:
            locale = locale[0:2]
        locale_path = os.path.join(self.plugin_dir, "i18n", f"SatIrriga_{locale}.qm")
        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Instance state
        self.actions = []
        self.menu = self.tr("&SatIrriga")
        self.toolbar = self.iface.addToolBar("SatIrriga")
        self.toolbar.setObjectName("SatIrrigaToolbar")
        self.plugin_is_active = False
        self.dock = None

        # DI: shared objects
        self._config_repo = ConfigRepository()
        self._state = AppState()

        # Auth
        self._auth_controller = AuthController(self._state, self._config_repo)
        self._auth_interceptor = AuthInterceptor(
            token_provider=self._auth_controller.get_access_token,
        )
        self._http_client = HttpClient(
            auth_interceptor=self._auth_interceptor,
        )

        # Mapeamento controller
        self._mapeamento_controller = MapeamentoController(
            state=self._state,
            http_client=self._http_client,
            config_repo=self._config_repo,
            token_provider=self._auth_controller.get_access_token,
        )

        # Config controller
        self._config_controller = ConfigController(
            config_repo=self._config_repo,
        )

    def tr(self, message):
        return QCoreApplication.translate("SatIrrigaPlugin", message)

    def _log(self, message, level=Qgis.Info):
        QgsMessageLog.logMessage(message, PLUGIN_NAME, level)

    def add_action(self, icon_path, text, callback, enabled_flag=True,
                   add_to_menu=True, add_to_toolbar=True,
                   status_tip=None, whats_this=None, parent=None):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip:
            action.setStatusTip(status_tip)
        if whats_this:
            action.setWhatsThis(whats_this)
        if add_to_toolbar:
            self.toolbar.addAction(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    # ------------------------------------------------------------------
    # QGIS Lifecycle
    # ------------------------------------------------------------------

    def initGui(self):
        icon_path = ":/plugins/satirriga_qgis/icon.png"
        self.add_action(
            icon_path,
            text=self.tr("SatIrriga"),
            callback=self.run,
            parent=self.iface.mainWindow(),
        )

        # Configura hosts autorizados para bearer token
        from urllib.parse import urlparse
        api_host = urlparse(self._config_repo.get("api_base_url")).hostname
        sso_host = urlparse(self._config_repo.get("sso_base_url")).hostname
        hosts = [h for h in (api_host, sso_host) if h]
        self._auth_interceptor.update_allowed_hosts(hosts)

        # Adia restauracao de sessao para apos o QGIS finalizar o startup
        QTimer.singleShot(500, self._auth_controller.try_restore_session)

        self._log("Plugin v2 carregado")

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.tr("&SatIrriga"), action)
            self.iface.removeToolBarIcon(action)

        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

        if self.toolbar:
            del self.toolbar

        # Cleanup controllers
        if self._auth_controller:
            self._auth_controller.cleanup()

        self._log("Plugin v2 descarregado")

    def run(self):
        if not self.plugin_is_active:
            self.plugin_is_active = True

            if self.dock is None:
                self.dock = SatIrrigaDock(
                    state=self._state,
                    config_repo=self._config_repo,
                    parent=self.iface.mainWindow(),
                )
                self.dock.closed.connect(self._on_dock_closed)

                self._wire_controllers()

            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
            self.dock.show()

    def _on_dock_closed(self):
        self.plugin_is_active = False

    def _wire_controllers(self):
        """Conecta controllers aos widgets do dock."""
        # Auth: SessionHeader no header do dock
        session_header = SessionHeader(
            state=self._state,
            auth_controller=self._auth_controller,
        )
        old_label = self.dock._user_label
        self.dock._header.replaceWidget(old_label, session_header)
        old_label.deleteLater()
        self.dock._user_label = session_header

        # Home: page 0
        home_tab = HomeTab()
        self.dock.set_page_widget(SatIrrigaDock.PAGE_HOME, home_tab)

        # Mapeamentos: page 1
        mapeamentos_tab = MapeamentosTab(
            state=self._state,
            mapeamento_controller=self._mapeamento_controller,
        )
        self.dock.set_page_widget(SatIrrigaDock.PAGE_MAPEAMENTOS, mapeamentos_tab)

        # Camadas: page 2
        camadas_tab = CamadasTab(
            state=self._state,
            mapeamento_controller=self._mapeamento_controller,
        )
        self.dock.set_page_widget(SatIrrigaDock.PAGE_CAMADAS, camadas_tab)

        # Config: page 3
        config_tab = ConfigTab(config_controller=self._config_controller)
        self.dock.set_page_widget(SatIrrigaDock.PAGE_CONFIG, config_tab)

        # Logs: page 4
        logs_tab = LogsTab()
        self.dock.set_page_widget(SatIrrigaDock.PAGE_LOGS, logs_tab)

        # V2: zonal download -> carregar layer no QGIS
        self._mapeamento_controller.zonal_download_completed.connect(
            lambda path, zonal_id: self._on_zonal_download_completed(
                path, zonal_id, camadas_tab
            )
        )

        # V2: upload progress bridge -> state
        self._mapeamento_controller.upload_progress.connect(
            lambda data: self._state.upload_progress_changed.emit(data)
        )

        # V2: conflict detected -> placeholder
        self._mapeamento_controller.conflict_detected.connect(
            self._on_conflict_detected
        )

        # Badge de camadas modificadas
        self._connect_camadas_badge(camadas_tab)

        # Garante que Home e a pagina inicial apos o wiring
        self.dock.navigate_to(SatIrrigaDock.PAGE_HOME)

    def _connect_camadas_badge(self, camadas_tab):
        """Atualiza badge na NavButton de Camadas quando ha features modificadas."""
        camadas_btn = self.dock.activity_bar.button_at(2)  # index 2 = Camadas
        if not camadas_btn:
            return

        original_refresh = camadas_tab._refresh_list

        def refresh_with_badge():
            original_refresh()
            modified_total = sum(
                entry.get("sync_counts", {}).get("MODIFIED", 0)
                + entry.get("sync_counts", {}).get("NEW", 0)
                for entry in camadas_tab._gpkg_list
            )
            camadas_btn.set_badge(modified_total)

        camadas_tab._refresh_list = refresh_with_badge

    def _on_zonal_download_completed(self, gpkg_path, zonal_id, camadas_tab):
        """Carrega GPKG V2 (zonal) no projeto QGIS apos download."""
        from qgis.core import QgsProject, QgsVectorLayer
        from .domain.services.gpkg_service import layer_group_name

        root = QgsProject.instance().layerTreeRoot()
        group_name = layer_group_name(f"Zonal {zonal_id}")
        group = root.findGroup(group_name)
        if not group:
            group = root.addGroup(group_name)

        layer = QgsVectorLayer(gpkg_path, f"Zonal {zonal_id}", "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer, False)
            group.addLayer(layer)
            self._log(f"Camada V2 carregada: {gpkg_path}")

            self._mapeamento_controller.connect_edit_tracking(
                layer, zonal_id=zonal_id,
            )

            if self._config_repo.get("auto_zoom_on_load"):
                self.iface.mapCanvas().setExtent(layer.extent())
                self.iface.mapCanvas().refresh()
        else:
            self._log(f"Falha ao carregar GPKG V2: {gpkg_path}", Qgis.Warning)

        camadas_tab.refresh()

    def _on_conflict_detected(self, batch_uuid):
        """Handler para conflitos detectados durante upload."""
        self._log(f"Conflitos detectados no batch {batch_uuid}")

        # Busca conflitos via API
        url = self._mapeamento_controller._api_url(
            f"/zonal/upload/{batch_uuid}/conflicts"
        )
        token = self._auth_controller.get_access_token()
        if not token:
            self._log("Token nao disponivel para buscar conflitos", Qgis.Warning)
            return

        import requests
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self._log(f"Erro ao buscar conflitos: {e}", Qgis.Warning)
            return

        from .domain.models.conflict import ConflictSet
        from .ui.dialogs.conflict_dialog import ConflictResolutionDialog

        conflict_set = ConflictSet.from_dict(data)

        dialog = ConflictResolutionDialog(
            conflict_set, parent=self.iface.mainWindow()
        )
        dialog.resolved.connect(
            lambda decisions: self._resolve_conflicts(batch_uuid, decisions)
        )
        dialog.exec_()

    def _resolve_conflicts(self, batch_uuid, decisions):
        """Envia resolucoes de conflitos para o servidor."""
        import json
        import requests

        url = self._mapeamento_controller._api_url(
            f"/zonal/upload/{batch_uuid}/resolve"
        )
        token = self._auth_controller.get_access_token()
        if not token:
            self._log("Token nao disponivel para resolver conflitos", Qgis.Warning)
            return

        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps({"decisions": decisions}),
                timeout=30,
            )
            resp.raise_for_status()
            self._log(
                f"Conflitos resolvidos para batch {batch_uuid}: "
                f"{len(decisions)} decisoes enviadas"
            )
        except Exception as e:
            self._log(f"Erro ao resolver conflitos: {e}", Qgis.Warning)
            self._state.set_error(
                "upload", f"Erro ao resolver conflitos: {e}"
            )
