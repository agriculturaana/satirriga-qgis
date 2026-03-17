import os
import traceback

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsMessageLog, Qgis

from . import resources  # noqa: F401 — registra icone no Qt Resource System
from .infra.config.settings import PLUGIN_NAME


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

        # Instance state — declaracao somente, init em _ensure_initialized
        self.actions = []
        self.menu = self.tr("&SatIrriga")
        self.toolbar = None
        self.plugin_is_active = False
        self.dock = None
        self._attribute_controller = None

        # Lazy-initialized em _ensure_initialized()
        self._config_repo = None
        self._state = None
        self._auth_controller = None
        self._auth_interceptor = None
        self._http_client = None
        self._mapeamento_controller = None
        self._config_controller = None
        self._camadas_badge_original_refresh = None
        self._signal_connections = []  # [(signal, slot), ...] para cleanup
        self._initialized = False

    def _ensure_initialized(self):
        """Inicializa controladores e servicos sob demanda."""
        if self._initialized:
            return

        from .infra.config.repository import ConfigRepository
        from .infra.http.auth_interceptor import AuthInterceptor
        from .infra.http.client import HttpClient
        from .app.state.store import AppState
        from .app.controllers.auth_controller import AuthController
        from .app.controllers.mapeamento_controller import MapeamentoController
        from .app.controllers.config_controller import ConfigController

        self._config_repo = ConfigRepository()
        self._state = AppState()

        self._auth_controller = AuthController(self._state, self._config_repo)
        self._auth_interceptor = AuthInterceptor(
            token_provider=self._auth_controller.get_access_token,
        )
        self._http_client = HttpClient(
            auth_interceptor=self._auth_interceptor,
        )

        self._mapeamento_controller = MapeamentoController(
            state=self._state,
            http_client=self._http_client,
            config_repo=self._config_repo,
            token_provider=self._auth_controller.get_access_token,
        )

        self._config_controller = ConfigController(
            config_repo=self._config_repo,
        )

        self._initialized = True

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
        self.toolbar = self.iface.addToolBar("SatIrriga")
        self.toolbar.setObjectName("SatIrrigaToolbar")

        icon_path = ":/plugins/satirriga_qgis/icon.png"
        self.add_action(
            icon_path,
            text=self.tr("SatIrriga"),
            callback=self.run,
            parent=self.iface.mainWindow(),
        )

        # Inicializa servicos e agenda restauracao de sessao
        try:
            self._ensure_initialized()

            from urllib.parse import urlparse
            api_host = urlparse(self._config_repo.get("api_base_url")).hostname
            sso_host = urlparse(self._config_repo.get("sso_base_url")).hostname
            hosts = [h for h in (api_host, sso_host) if h]
            self._auth_interceptor.update_allowed_hosts(hosts)

            # Adia restauracao de sessao para apos o QGIS finalizar o startup
            QTimer.singleShot(500, self._auth_controller.try_restore_session)
        except Exception as e:
            self._log(
                f"Erro na inicializacao dos servicos: {e}\n"
                f"{traceback.format_exc()}",
                Qgis.Critical,
            )

        self._log("Plugin v2 carregado")

    def unload(self):
        self._disconnect_all_signals()

        for action in self.actions:
            self.iface.removePluginMenu(self.tr("&SatIrriga"), action)
            self.iface.removeToolBarIcon(action)

        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

        if self.toolbar:
            self.toolbar.deleteLater()
            self.toolbar = None

        # Cleanup controllers
        if self._attribute_controller:
            try:
                self._attribute_controller.cleanup()
            except (RuntimeError, TypeError):
                pass
            self._attribute_controller = None

        if self._auth_controller:
            try:
                self._auth_controller.cleanup()
            except (RuntimeError, TypeError):
                pass

        self._initialized = False
        self._log("Plugin v2 descarregado")

    def run(self):
        if not self.plugin_is_active:
            self.plugin_is_active = True

            if self.dock is None:
                try:
                    self._ensure_initialized()

                    from .ui.dock import SatIrrigaDock
                    self.dock = SatIrrigaDock(
                        state=self._state,
                        config_repo=self._config_repo,
                        parent=self.iface.mainWindow(),
                    )
                    self.dock.closed.connect(self._on_dock_closed)

                    self._wire_controllers()
                except Exception as e:
                    self._log(
                        f"Erro ao criar dock: {e}\n"
                        f"{traceback.format_exc()}",
                        Qgis.Critical,
                    )
                    self.plugin_is_active = False
                    return

            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
            self.dock.show()

    def _connect(self, signal, slot):
        """Conecta signal/slot e registra para cleanup em unload."""
        signal.connect(slot)
        self._signal_connections.append((signal, slot))

    def _disconnect_all_signals(self):
        """Desconecta todos os sinais registrados via _connect."""
        for signal, slot in self._signal_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._signal_connections.clear()

    def _on_dock_closed(self):
        self.plugin_is_active = False

    def _on_error_occurred(self, operation, message):
        """Exibe dialog de erro intuitivo para o usuario."""
        from .ui.dialogs.error_dialog import ErrorDialog
        ErrorDialog.show_error(operation, message, parent=self.dock)

    def _wire_controllers(self):
        """Conecta controllers aos widgets do dock."""
        from .ui.dock import SatIrrigaDock
        from .ui.widgets.session_header import SessionHeader
        from .ui.widgets.mapeamentos_tab import MapeamentosTab
        from .ui.widgets.camadas_tab import CamadasTab
        from .ui.widgets.homologacao_tab import HomologacaoTab
        from .ui.widgets.config_tab import ConfigTab
        from .ui.widgets.logs_tab import LogsTab
        from .ui.widgets.home_tab import HomeTab
        from .app.controllers.attribute_controller import AttributeEditController

        # Erros globais -> dialog
        self._connect(self._state.error_occurred, self._on_error_occurred)

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

        # Homologacao: page 3 (visivel apenas para homologadores)
        homologacao_tab = HomologacaoTab(
            state=self._state,
            mapeamento_controller=self._mapeamento_controller,
        )
        self.dock.set_page_widget(SatIrrigaDock.PAGE_HOMOLOGACAO, homologacao_tab)

        # Config: page 4
        config_tab = ConfigTab(config_controller=self._config_controller)
        self.dock.set_page_widget(SatIrrigaDock.PAGE_CONFIG, config_tab)

        # Logs: page 5
        logs_tab = LogsTab()
        self.dock.set_page_widget(SatIrrigaDock.PAGE_LOGS, logs_tab)

        # V2: zonal download -> carregar layer no QGIS
        download_slot = lambda path, zonal_id: self._on_zonal_download_completed(
            path, zonal_id, camadas_tab
        )
        self._connect(
            self._mapeamento_controller.zonal_download_completed, download_slot
        )

        # V2: upload progress bridge -> state
        progress_slot = lambda data: self._state.upload_progress_changed.emit(data)
        self._connect(self._mapeamento_controller.upload_progress, progress_slot)

        # V2: conflict detected -> busca conflitos via controller
        self._connect(
            self._mapeamento_controller.conflict_detected, self._on_conflict_detected
        )

        # V2: conflict data ready -> exibe dialog
        self._connect(
            self._mapeamento_controller.conflict_data_ready, self._on_conflict_data_ready
        )

        # Raster: criar camadas XYZ quando prontas
        self._connect(self._state.raster_layers_ready, self._on_raster_layers_ready)

        # Badge de camadas modificadas
        self._connect_camadas_badge(camadas_tab)

        # Attribute edit: abre dialog ao selecionar 1 feature SatIrriga
        self._attribute_controller = AttributeEditController(
            canvas=self.iface.mapCanvas(),
            parent=self.dock,
        )
        # Dialog save -> atualiza camadas_tab (via edit_tracking_done)
        self._attribute_controller.feature_saved.connect(
            lambda _fid: self._mapeamento_controller.edit_tracking_done.emit()
        )

        # Garante que Home e a pagina inicial apos o wiring
        self.dock.navigate_to(SatIrrigaDock.PAGE_HOME)

    def _connect_camadas_badge(self, camadas_tab):
        """Atualiza badge na NavButton de Camadas quando ha features modificadas."""
        camadas_btn = self.dock.activity_bar.button_at(2)  # index 2 = Camadas
        if not camadas_btn:
            return

        original_refresh = camadas_tab._refresh_list
        self._camadas_badge_original_refresh = original_refresh

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

    def _on_raster_layers_ready(self, configs):
        """Cria camadas raster XYZ no QGIS a partir de RasterLayerConfig."""
        from qgis.core import (
            QgsProject, QgsRasterLayer, QgsColorRampShader,
            QgsRasterShader, QgsSingleBandPseudoColorRenderer,
        )
        from .domain.services.gpkg_service import layer_group_name

        if not configs:
            return

        # Busca ou cria grupo SatIrriga / Raster
        root = QgsProject.instance().layerTreeRoot()
        group_name = "SatIrriga / Imagens"
        group = root.findGroup(group_name)
        if not group:
            group = root.insertGroup(0, group_name)

        for config in configs:
            uri = f"type=xyz&url={config.xyz_url}&zmin=0&zmax=18"
            layer = QgsRasterLayer(uri, config.name, "wms")

            if not layer.isValid():
                self._log(
                    f"Camada raster invalida: {config.name} ({config.xyz_url[:80]}...)",
                    Qgis.Warning,
                )
                continue

            # Simbologia divergente para difImg
            if config.layer_type == "DIF_IMG":
                try:
                    shader = QgsRasterShader()
                    color_ramp = QgsColorRampShader()
                    color_ramp.setColorRampType(QgsColorRampShader.Interpolated)
                    color_ramp.setColorRampItemList([
                        QgsColorRampShader.ColorRampItem(-1, QColor("#C62828"), "-1"),
                        QgsColorRampShader.ColorRampItem(0, QColor("#FFFFFF"), "0"),
                        QgsColorRampShader.ColorRampItem(1, QColor("#1565C0"), "+1"),
                    ])
                    shader.setRasterShaderFunction(color_ramp)
                    renderer = QgsSingleBandPseudoColorRenderer(
                        layer.dataProvider(), 1, shader
                    )
                    layer.setRenderer(renderer)
                except Exception as e:
                    self._log(f"Erro ao aplicar simbologia difImg: {e}", Qgis.Warning)

            QgsProject.instance().addMapLayer(layer, False)
            node = group.addLayer(layer)

            # Visibilidade padrao
            if not config.is_visible and node:
                node.setItemVisibilityChecked(False)

            self._log(f"Camada raster carregada: {config.name} ({config.layer_type})")

    def _on_conflict_detected(self, batch_uuid):
        """Handler para conflitos detectados durante upload."""
        self._log(f"Conflitos detectados no batch {batch_uuid}")
        self._mapeamento_controller.fetch_conflicts(batch_uuid)

    def _on_conflict_data_ready(self, batch_uuid, body):
        """Exibe dialog de resolucao quando dados de conflito chegam."""
        import json

        try:
            data = json.loads(body)
        except Exception as e:
            self._log(f"Erro ao parsear conflitos: {e}", Qgis.Warning)
            return

        from .domain.models.conflict import ConflictSet
        from .ui.dialogs.conflict_dialog import ConflictResolutionDialog

        conflict_set = ConflictSet.from_dict(data)

        dialog = ConflictResolutionDialog(
            conflict_set, parent=self.iface.mainWindow()
        )
        dialog.resolved.connect(
            lambda decisions: self._mapeamento_controller.resolve_conflicts(
                batch_uuid, decisions
            )
        )
        dialog.exec_()
