import os

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt
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
from .ui.widgets.sessao_tab import SessaoTab
from .ui.widgets.mapeamentos_tab import MapeamentosTab
from .ui.widgets.camadas_tab import CamadasTab
from .ui.widgets.config_tab import ConfigTab
from .ui.widgets.logs_tab import LogsTab
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
        icon_path = ":/plugins/satirriga_cliente/icon.png"
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

        # Tenta restaurar sessao anterior
        self._auth_controller.try_restore_session()

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
        # Substitui o _user_label no header pelo SessionHeader
        old_label = self.dock._user_label
        self.dock._header.replaceWidget(old_label, session_header)
        old_label.deleteLater()
        self.dock._user_label = session_header

        # Auth: SessaoTab na aba "Sessao" (index 3)
        sessao_tab = SessaoTab(
            state=self._state,
            auth_controller=self._auth_controller,
        )
        self.dock.replace_tab(3, sessao_tab, "Sessao")

        # Mapeamentos: MapeamentosTab na aba "Mapeamentos" (index 0)
        mapeamentos_tab = MapeamentosTab(
            state=self._state,
            mapeamento_controller=self._mapeamento_controller,
        )
        self.dock.replace_tab(0, mapeamentos_tab, "Mapeamentos")

        # Camadas: CamadasTab na aba "Camadas" (index 1)
        camadas_tab = CamadasTab(
            state=self._state,
            mapeamento_controller=self._mapeamento_controller,
        )
        self.dock.replace_tab(1, camadas_tab, "Camadas")

        # Config: ConfigTab na aba "Config" (index 2)
        config_tab = ConfigTab(config_controller=self._config_controller)
        self.dock.replace_tab(2, config_tab, "Config")

        # Logs: LogsTab na aba "Logs" (index 4)
        logs_tab = LogsTab()
        self.dock.replace_tab(4, logs_tab, "Logs")

        # Conecta download -> carregar layer no QGIS + atualizar camadas tab
        self._mapeamento_controller.download_completed.connect(
            lambda path, m_id, met_id: self._on_download_completed(
                path, m_id, met_id, camadas_tab
            )
        )

    def _on_download_completed(self, gpkg_path, mapeamento_id, metodo_id, camadas_tab):
        """Carrega GPKG no projeto QGIS apos download."""
        from qgis.core import QgsProject, QgsVectorLayer
        from .domain.services.gpkg_service import layer_group_name

        # Cria grupo no layer tree
        root = QgsProject.instance().layerTreeRoot()
        mapeamento = self._state.selected_mapeamento
        group_name = layer_group_name(
            mapeamento.descricao if mapeamento else f"Mapeamento {mapeamento_id}"
        )
        group = root.findGroup(group_name)
        if not group:
            group = root.addGroup(group_name)

        # Carrega layer editavel
        layer = QgsVectorLayer(gpkg_path, f"Metodo {metodo_id}", "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer, False)
            group.addLayer(layer)
            self._log(f"Camada carregada: {gpkg_path}")

            # Conecta edit tracking
            self._mapeamento_controller.connect_edit_tracking(
                layer, mapeamento_id, metodo_id,
            )

            if self._config_repo.get("auto_zoom_on_load"):
                self.iface.mapCanvas().setExtent(layer.extent())
                self.iface.mapCanvas().refresh()
        else:
            self._log(f"Falha ao carregar GPKG: {gpkg_path}", Qgis.Warning)

        # Atualiza lista de camadas locais
        camadas_tab.refresh()
