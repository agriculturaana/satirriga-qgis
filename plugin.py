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
        self._timeseries_controller = None
        self._timeseries_map_tool = None
        self._timeseries_tab = None
        self._config_controller = None
        self._camadas_tab = None
        self._upload_history_tab = None
        self._camadas_badge_original_refresh = None
        self._signal_connections = []  # [(signal, slot), ...] para cleanup
        self._pending_raster_group = None  # Grupo-alvo para rasters do download
        self._vis_action = None            # Acao de contexto "Ajustar visualizacao"
        self._tile_auth_set = False        # Preprocessor de auth para tiles base
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

        from .app.controllers.timeseries_controller import TimeSeriesController
        self._timeseries_controller = TimeSeriesController(
            http_client=self._http_client,
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

        # Cleanup camadas tab
        if self._camadas_tab:
            try:
                self._camadas_tab.cleanup()
            except (RuntimeError, AttributeError):
                pass
            self._camadas_tab = None

        # Cleanup histórico de envios (temporários de comparação)
        if self._upload_history_tab:
            try:
                self._upload_history_tab.cleanup()
            except (RuntimeError, AttributeError):
                pass
            self._upload_history_tab = None

        # Cleanup acao de contexto raster
        if hasattr(self, "_vis_action") and self._vis_action:
            try:
                self.iface.removeCustomActionForLayerType(self._vis_action)
            except (RuntimeError, TypeError):
                pass
            self._vis_action = None

        # Cleanup map tool de serie temporal
        if self._timeseries_map_tool:
            try:
                self._timeseries_map_tool.cleanup()
            except (RuntimeError, AttributeError):
                pass
            self._timeseries_map_tool = None
        self._timeseries_tab = None

        # Cleanup controllers
        if self._mapeamento_controller:
            try:
                self._mapeamento_controller.cleanup_polling()
            except (RuntimeError, AttributeError):
                pass

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

        # Remove interceptor de tiles base
        if self._tile_auth_set:
            try:
                from qgis.core import QgsNetworkAccessManager
                QgsNetworkAccessManager.setRequestPreprocessor(None)
            except Exception:
                pass
            self._tile_auth_set = False

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
        from .ui.widgets.upload_history_widget import UploadHistoryWidget
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
        self._mapeamentos_tab = MapeamentosTab(
            state=self._state,
            mapeamento_controller=self._mapeamento_controller,
        )
        self.dock.set_page_widget(SatIrrigaDock.PAGE_MAPEAMENTOS, self._mapeamentos_tab)

        # Camadas: page 2
        self._camadas_tab = CamadasTab(
            state=self._state,
            mapeamento_controller=self._mapeamento_controller,
        )
        self.dock.set_page_widget(SatIrrigaDock.PAGE_CAMADAS, self._camadas_tab)

        # Homologacao: page 3 (visivel apenas para homologadores)
        homologacao_tab = HomologacaoTab(
            state=self._state,
            mapeamento_controller=self._mapeamento_controller,
        )
        self.dock.set_page_widget(SatIrrigaDock.PAGE_HOMOLOGACAO, homologacao_tab)

        # Histórico de envios: page 4
        self._upload_history_tab = UploadHistoryWidget(
            state=self._state,
            mapeamento_controller=self._mapeamento_controller,
        )
        self.dock.set_page_widget(SatIrrigaDock.PAGE_HISTORICO, self._upload_history_tab)

        # Config: page 5
        config_tab = ConfigTab(config_controller=self._config_controller)
        self.dock.set_page_widget(SatIrrigaDock.PAGE_CONFIG, config_tab)

        # Logs: page 6
        logs_tab = LogsTab()
        self.dock.set_page_widget(SatIrrigaDock.PAGE_LOGS, logs_tab)

        # Série Temporal: page 7
        from .ui.tools.timeseries_map_tool import TimeSeriesMapTool
        from .ui.widgets.timeseries_tab import TimeSeriesTab

        self._timeseries_map_tool = TimeSeriesMapTool(self.iface.mapCanvas())
        self._timeseries_tab = TimeSeriesTab(
            controller=self._timeseries_controller,
            map_tool=self._timeseries_map_tool,
            canvas=self.iface.mapCanvas(),
        )
        self.dock.set_page_widget(SatIrrigaDock.PAGE_TIMESERIES, self._timeseries_tab)

        # Histórico: carregar ao autenticar e atualizar após upload
        self._connect(
            self._state.auth_state_changed,
            lambda auth: self._upload_history_tab.load() if auth else None,
        )
        self._connect(
            self._mapeamento_controller.zonal_upload_completed,
            lambda _path, _zid: self._upload_history_tab.load(),
        )
        # Catálogo: recarregar lista de mapeamentos após sincronização
        self._connect(
            self._mapeamento_controller.zonal_upload_completed,
            lambda _path, _zid: self._mapeamentos_tab._on_catalogo_refresh(),
        )

        # V2: zonal download -> carregar layer no QGIS
        download_slot = lambda path, zonal_id, meta: self._on_zonal_download_completed(
            path, zonal_id, meta, self._camadas_tab
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

        # Mascara/ROI: criar camada vetorial quando geometria chegar
        self._pending_mascara_groups = {}
        self._connect(self._state.mascara_layer_ready, self._on_mascara_layer_ready)

        # Série temporal: desativar map tool ao sair da aba
        self._connect(
            self.dock._activity_bar.page_changed,
            lambda page: (
                self._timeseries_tab.deactivate_tool()
                if page != SatIrrigaDock.PAGE_TIMESERIES else None
            ),
        )

        # Acao de contexto: "Ajustar visualização..." em camadas raster SatIrriga
        self._setup_raster_context_action()

        # Badge de camadas modificadas
        self._connect_camadas_badge(self._camadas_tab)

        # Attribute edit: abre dialog ao selecionar 1 feature SatIrriga
        self._attribute_controller = AttributeEditController(
            canvas=self.iface.mapCanvas(),
            parent=self.dock,
        )
        # Dialog save -> atualiza camadas_tab (via edit_tracking_done)
        self._attribute_controller.feature_saved.connect(
            lambda _fid: self._mapeamento_controller.edit_tracking_done.emit()
        )
        # Overlay data -> attribute controller
        self._connect(
            self._mapeamento_controller.overlay_data_ready,
            lambda _zid, data: self._attribute_controller.set_overlay_data(data),
        )

        # Reconecta edit tracking de camadas SatIrriga já presentes no projeto
        self._reconnect_existing_layers()

        # Garante que Home e a pagina inicial apos o wiring
        self.dock.navigate_to(SatIrrigaDock.PAGE_HOME)

    def _reconnect_existing_layers(self):
        """Reconecta edit tracking de camadas SatIrriga já presentes no projeto.

        Ao reabrir um projeto QGIS, camadas vetoriais e GPKGs são restauradas
        nativamente, mas os signals de edit tracking precisam ser reconectados.
        """
        from qgis.core import QgsProject, QgsVectorLayer
        from .domain.services.gpkg_service import read_sidecar, sidecar_path, count_features_by_sync_status
        import os

        pending_count = 0
        reconnected = 0

        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            source = layer.source().split("|")[0]
            if not source.endswith(".gpkg"):
                continue
            sc_path = sidecar_path(source)
            if not os.path.exists(sc_path):
                continue
            meta = read_sidecar(source)
            zonal_id = meta.get("zonalId")
            if not zonal_id:
                continue

            self._mapeamento_controller.connect_edit_tracking(
                layer, zonal_id=zonal_id,
            )
            self._mapeamento_controller.fetch_overlay_data(zonal_id)
            reconnected += 1

            counts = count_features_by_sync_status(source)
            pending = (counts.get("MODIFIED", 0)
                       + counts.get("NEW", 0)
                       + counts.get("DELETED", 0))
            if pending > 0:
                pending_count += 1

        if pending_count > 0:
            self._log(
                f"{pending_count} camada(s) com edicoes pendentes detectada(s)",
                Qgis.Info,
            )
        if reconnected > 0:
            self._log(f"Reconexao de {reconnected} camada(s) SatIrriga concluida")

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
                + entry.get("sync_counts", {}).get("DELETED", 0)
                for entry in camadas_tab._gpkg_list
            )
            camadas_btn.set_badge(modified_total)

        camadas_tab._refresh_list = refresh_with_badge

    def _setup_raster_context_action(self):
        """Registra acao 'Ajustar visualizacao' no menu de contexto da layer tree.

        A acao e registrada para todas as camadas raster (limitacao da API
        addCustomActionForLayerType), mas e habilitada/desabilitada
        dinamicamente via currentLayerChanged para aparecer apenas em
        camadas SatIrriga (que possuem custom property satirriga/image_id).
        """
        from qgis.core import QgsMapLayerType

        self._vis_action = QAction(
            "Ajustar visualização...", self.iface.mainWindow()
        )
        self._vis_action.setEnabled(False)
        self._vis_action.triggered.connect(self._on_vis_action_triggered)
        self.iface.addCustomActionForLayerType(
            self._vis_action,
            "",
            QgsMapLayerType.RasterLayer,
            allLayers=True,
        )

        # Habilita acao apenas quando camada ativa e raster SatIrriga
        self._connect(
            self.iface.layerTreeView().currentLayerChanged,
            self._on_current_layer_changed_for_vis,
        )

    def _on_current_layer_changed_for_vis(self, layer):
        """Habilita/desabilita acao de visualizacao conforme camada ativa."""
        is_satirriga_raster = (
            layer is not None
            and layer.customProperty("satirriga/image_id")
        )
        self._vis_action.setEnabled(bool(is_satirriga_raster))

    def _on_vis_action_triggered(self):
        """Handler da acao de contexto — identifica layer ativa e abre dialogo."""
        layer = self.iface.activeLayer()
        if not layer or not layer.customProperty("satirriga/image_id"):
            return
        self.customize_raster_vis(layer)

    # ------------------------------------------------------------------
    # Camadas Base (Google Satellite + Vector Tiles MVT)
    # ------------------------------------------------------------------

    def _setup_tile_auth(self):
        """Registra interceptor global para injetar Bearer token em tiles base.

        Usa QgsNetworkAccessManager.setRequestPreprocessor() para adicionar
        Authorization header em requisicoes para /bases/tiles/ no host da API.
        """
        if self._tile_auth_set:
            return

        from urllib.parse import urlparse
        from qgis.core import QgsNetworkAccessManager

        api_host = urlparse(self._config_repo.get("api_base_url")).hostname
        token_provider = self._auth_controller.get_access_token

        def _inject_bearer(request):
            url = request.url()
            if url.host() == api_host and "/bases/tiles/" in url.path():
                token = token_provider()
                if token:
                    request.setRawHeader(
                        b"Authorization",
                        f"Bearer {token}".encode("utf-8"),
                    )

        try:
            QgsNetworkAccessManager.setRequestPreprocessor(_inject_bearer)
            self._tile_auth_set = True
            self._log("[Auth] Interceptor de tiles base registrado")
        except Exception as e:
            self._log(
                f"[Auth] Falha ao registrar interceptor de tiles: {e}",
                Qgis.Warning,
            )

    def _remove_zonal_group(self, parent_group, zonal_id):
        """Remove subgrupo do zonal informado dentro de ``parent_group``.

        Remove tambem as camadas associadas (``QgsProject.removeMapLayer``)
        para evitar orfaos. A identificacao usa ``customProperty``
        ``satirriga/zonal_id`` — imune a renomeacoes de descricao.
        """
        from qgis.core import QgsProject
        try:
            target_id = int(zonal_id)
        except (TypeError, ValueError):
            return
        project = QgsProject.instance()
        for child in list(parent_group.children()):
            prop = child.customProperty("satirriga/zonal_id")
            if prop is None:
                continue
            try:
                if int(prop) != target_id:
                    continue
            except (TypeError, ValueError):
                continue
            # Remove camadas contidas no subgrupo antes de remover o no
            for leaf in child.findLayers():
                layer = leaf.layer()
                if layer is not None:
                    project.removeMapLayer(layer.id())
            parent_group.removeChildNode(child)

    def _add_base_layers(self, group):
        """Adiciona camadas base ao grupo do mapeamento.

        Cria subgrupo 'Camadas Base' com Google Satellite (XYZ) e
        limites geograficos (Vector Tiles MVT autenticados).
        Todas as camadas sao adicionadas invisiveis por padrao.
        """
        from qgis.core import QgsProject, QgsRasterLayer

        # Evita duplicatas
        for child in group.children():
            if hasattr(child, "name") and child.name() == "Camadas Base":
                return

        base_group = group.addGroup("Camadas Base")

        # Google Satellite (XYZ, sem auth)
        sat_url = "https://mt1.google.com/vt/lyrs%3Ds%26x%3D{x}%26y%3D{y}%26z%3D{z}"
        uri = f"type=xyz&url={sat_url}&zmin=0&zmax=19"
        satellite = QgsRasterLayer(uri, "Google Satellite", "wms")
        if satellite.isValid():
            QgsProject.instance().addMapLayer(satellite, False)
            node = base_group.addLayer(satellite)
            node.setItemVisibilityChecked(False)

        # Vector tiles (limites geograficos)
        self._setup_tile_auth()
        self._add_vector_tile_layers(base_group)

        base_group.setExpanded(False)

    def _add_vector_tile_layers(self, base_group):
        """Adiciona camadas de limites via Vector Tiles MVT autenticados."""
        try:
            from qgis.core import (
                QgsProject,
                QgsVectorTileLayer,
                QgsVectorTileBasicRenderer,
                QgsVectorTileBasicRendererStyle,
            )
            from qgis.core import QgsFillSymbol, QgsWkbTypes
        except ImportError:
            self._log(
                "QgsVectorTileLayer nao disponivel nesta versao do QGIS",
                Qgis.Warning,
            )
            return

        api_base = self._config_repo.get("api_base_url").rstrip("/")

        configs = [
            {
                "id": "municipios",
                "name": "Municípios",
                "zmin": 4, "zmax": 14,
                "stroke_color": "#7f8c8d",
                "stroke_width": "0.4",
                "stroke_style": "dash",
                "fill": False,
            },
            {
                "id": "bacias",
                "name": "Bacias Hidrográficas",
                "zmin": 4, "zmax": 6,
                "stroke_color": "#2980b9",
                "stroke_width": "0.6",
                "stroke_style": "solid",
                "fill": False,
            },
            {
                "id": "empreendimentos",
                "name": "Empreendimentos",
                "zmin": 6, "zmax": 8,
                "stroke_color": "#e67e22",
                "stroke_width": "0.5",
                "stroke_style": "solid",
                "fill": True,
                "fill_color": "230,126,34,38",
            },
        ]

        for cfg in configs:
            tile_url = (
                f"{api_base}/bases/tiles/{cfg['id']}"
                "/{z}/{x}/{y}.pbf"
            )
            uri = f"type=xyz&url={tile_url}&zmin={cfg['zmin']}&zmax={cfg['zmax']}"

            vtl = QgsVectorTileLayer(uri, cfg["name"])
            if not vtl.isValid():
                self._log(
                    f"Falha ao criar camada base: {cfg['name']}",
                    Qgis.Warning,
                )
                continue

            # Estilo: poligono com borda colorida
            props = {
                "color": cfg.get("fill_color", "0,0,0,0") if cfg["fill"] else "0,0,0,0",
                "outline_color": cfg["stroke_color"],
                "outline_width": cfg["stroke_width"],
                "outline_style": cfg["stroke_style"],
            }
            symbol = QgsFillSymbol.createSimple(props)

            style = QgsVectorTileBasicRendererStyle()
            style.setGeometryType(QgsWkbTypes.PolygonGeometry)
            style.setLayerName(cfg["id"])
            style.setSymbol(symbol)
            style.setEnabled(True)
            style.setMinZoomLevel(cfg["zmin"])
            style.setMaxZoomLevel(18)

            renderer = QgsVectorTileBasicRenderer()
            renderer.setStyles([style])
            vtl.setRenderer(renderer)

            QgsProject.instance().addMapLayer(vtl, False)
            node = base_group.addLayer(vtl)
            node.setItemVisibilityChecked(False)

    def _on_zonal_download_completed(self, gpkg_path, zonal_id, catalogo_meta,
                                     camadas_tab):
        """Carrega GPKG V2 (zonal) no projeto QGIS apos download.

        Cria grupo aninhado ``SatIrriga / <Origem> / #... - <desc>`` e, caso
        ja exista um grupo para o mesmo ``zonal_id`` dentro da mesma origem,
        remove-o (e suas camadas) antes de recriar, garantindo estado limpo
        a cada redownload. Origens distintas (Mapeamentos vs Homologacao)
        sao mantidas lado a lado.
        """
        from qgis.core import QgsProject, QgsVectorLayer
        from .domain.services.gpkg_service import (
            SATIRRIGA_ROOT_GROUP,
            origin_group_label,
            read_sidecar,
        )
        from .domain.models.enums import DownloadOrigin

        # Origem: prioridade meta do download, fallback para sidecar no disco
        origin_raw = (catalogo_meta or {}).get("origin")
        if not origin_raw:
            origin_raw = read_sidecar(gpkg_path).get("origin")
        origin_enum = DownloadOrigin.coerce(origin_raw)
        origin_key = origin_enum.value
        origin_label = origin_group_label(origin_key)

        mapeamento_id = catalogo_meta.get("mapeamentoId")
        descricao = catalogo_meta.get("descricao", "")
        job_id = catalogo_meta.get("jobId")
        metodo_apply = catalogo_meta.get("metodoApply")

        if mapeamento_id:
            from qgis.PyQt.QtGui import QTextDocument
            if descricao:
                doc = QTextDocument()
                doc.setHtml(descricao)
                plain = doc.toPlainText().strip()
                short_desc = (plain[:60] + "...") if len(plain) > 60 else plain
            else:
                short_desc = ""
            suffix = f"#{mapeamento_id} - {short_desc}" if short_desc else f"#{mapeamento_id}"
        else:
            suffix = f"Zonal {zonal_id}"

        root = QgsProject.instance().layerTreeRoot()
        parent = root.findGroup(SATIRRIGA_ROOT_GROUP)
        if not parent:
            parent = root.addGroup(SATIRRIGA_ROOT_GROUP)
        origin_group = parent.findGroup(origin_label)
        if not origin_group:
            origin_group = parent.addGroup(origin_label)

        # Remove grupo anterior do MESMO zonal na MESMA origem (se existir)
        self._remove_zonal_group(origin_group, zonal_id)

        group = origin_group.addGroup(suffix)
        group.setCustomProperty("satirriga/zonal_id", int(zonal_id))
        group.setCustomProperty("satirriga/origin", origin_key)

        metodo_label = self._format_metodo(metodo_apply)
        layer_name = (
            f"Zonal #{zonal_id} - {metodo_label}"
            if metodo_label else f"Zonal #{zonal_id}"
        )
        layer = QgsVectorLayer(gpkg_path, layer_name, "ogr")
        if layer.isValid():
            # Estilo: somente borda laranja, sem preenchimento
            # Aplicado ANTES de addMapLayer para que a legenda já reflita
            from qgis.core import QgsFillSymbol
            symbol = QgsFillSymbol.createSimple({})
            sl = symbol.symbolLayer(0)
            sl.setBrushStyle(Qt.NoBrush)
            sl.setStrokeColor(QColor("#FF6600"))
            sl.setStrokeWidth(0.8)
            layer.renderer().setSymbol(symbol)

            QgsProject.instance().addMapLayer(layer, False)
            group.insertLayer(0, layer)
            layer.triggerRepaint()

            self._log(f"Camada V2 carregada: {gpkg_path}")

            self._mapeamento_controller.connect_edit_tracking(
                layer, zonal_id=zonal_id,
            )

            if self._config_repo.get("auto_zoom_on_load"):
                self.iface.mapCanvas().setExtent(layer.extent())
                self.iface.mapCanvas().refresh()
        else:
            self._log(f"Falha ao carregar GPKG V2: {gpkg_path}", Qgis.Warning)

        # Dispara carregamento automatico de rasters de referencia
        if job_id and metodo_apply:
            self._pending_raster_group = group
            self._mapeamento_controller.load_raster_images(
                job_id, metodo_apply, gpkg_path=gpkg_path,
            )

        # Dispara carregamento da camada Mascara/ROI
        if mapeamento_id:
            self._pending_mascara_groups[mapeamento_id] = group
            self._mapeamento_controller.load_mascara(mapeamento_id)

        # Camadas base (Google Satellite + limites geograficos)
        self._add_base_layers(group)

        camadas_tab.refresh()

        # Auto-preenche datas da serie temporal a partir do mapeamento
        data_ref = catalogo_meta.get("dataReferencia")
        if data_ref and self._timeseries_tab:
            self._timeseries_tab.set_data_referencia(data_ref)

        # Busca dados de overlay para enriquecer dialog de atributos
        self._mapeamento_controller.fetch_overlay_data(zonal_id)

    def _on_raster_layers_ready(self, hierarchy):
        """Cria arvore hierarquica de camadas raster XYZ no QGIS.

        Hierarquia: Datas > Bandas > Cenas (tiles individuais).
        """
        import json as _json
        from dataclasses import asdict
        from qgis.core import QgsProject, QgsRasterLayer

        if not hierarchy or not hierarchy.dates:
            return

        # Usa grupo-alvo do download (mesmo grupo do vetor) ou fallback
        group = self._pending_raster_group
        self._pending_raster_group = None

        if not group:
            root = QgsProject.instance().layerTreeRoot()
            group_name = "SatIrriga / Imagens"
            group = root.findGroup(group_name)
            if not group:
                group = root.insertGroup(0, group_name)

        dates_group = group.addGroup("Cenas")

        for date_group in hierarchy.dates:
            date_node = dates_group.addGroup(date_group.date_label)

            for band_group in date_group.bands:
                band_node = date_node.addGroup(band_group.band_name)
                band_has_visible = False

                for config in band_group.layers:
                    # Escapa & na URL do tile para que o WMS provider
                    # não confunda params do tile com params do provider
                    safe_url = config.xyz_url.replace("&", "%26")
                    uri = f"type=xyz&url={safe_url}&zmin=0&zmax=18"
                    layer = QgsRasterLayer(uri, config.name, "wms")

                    if not layer.isValid():
                        self._log(
                            f"Camada raster invalida: {config.name}",
                            Qgis.Warning,
                        )
                        continue

                    # Persiste contexto como custom properties para customizacao posterior
                    if config.image_id:
                        layer.setCustomProperty("satirriga/image_id", config.image_id)
                        layer.setCustomProperty(
                            "satirriga/vis_params",
                            _json.dumps(asdict(config.vis_params)),
                        )
                        layer.setCustomProperty("satirriga/band_key", band_group.band_key)

                    QgsProject.instance().addMapLayer(layer, False)
                    band_node.addLayer(layer)

                    if config.is_visible:
                        band_has_visible = True

                # Grupo de banda invisivel por padrao se nenhuma camada e visivel
                if not band_has_visible:
                    band_node.setItemVisibilityChecked(False)

        self._log(
            f"Arvore raster criada: {len(hierarchy.dates)} datas, "
            f"{sum(len(dg.bands) for dg in hierarchy.dates)} bandas"
        )

    @staticmethod
    def _format_metodo(metodo_apply):
        """Converte metodoApply em label legivel."""
        if not metodo_apply:
            return ""
        labels = {
            "METODO_1": "Fatiamento do índice de Vegetação",
            "METODO_2_DISCRETO": "Detecção de mudança (discreto)",
            "METODO_2_FUZZY": "Detecção de mudança (fuzzy)",
            "METODO_3": "Método 3",
            "AUTOMATICO": "Automático",
        }
        return labels.get(metodo_apply, metodo_apply)

    def _on_mascara_layer_ready(self, mapeamento_id, geojson):
        """Cria camada vetorial Mascara/ROI a partir da geometria do mapeamento."""
        import json as _json
        from qgis.core import QgsProject, QgsVectorLayer, QgsFillSymbol

        group = self._pending_mascara_groups.pop(mapeamento_id, None)
        if not group or not geojson:
            return

        # Monta GeoJSON FeatureCollection
        fc = _json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": geojson,
                "properties": {"name": "Área de Interesse"},
            }],
        })

        # Usa GDAL virtual filesystem para evitar arquivos temporarios
        from osgeo import gdal
        vsimem_path = f"/vsimem/satirriga_mascara_{mapeamento_id}.geojson"
        gdal.FileFromMemBuffer(vsimem_path, fc.encode("utf-8"))

        layer = QgsVectorLayer(vsimem_path, "Máscara", "ogr")
        if not layer.isValid():
            gdal.Unlink(vsimem_path)
            self._log("Falha ao criar camada Máscara/ROI", Qgis.Warning)
            return

        # Estilo: sem preenchimento, borda amarela tracejada (stroke fino)
        # Aplicado ANTES de addMapLayer para que a legenda já reflita
        symbol = QgsFillSymbol.createSimple({})
        sl = symbol.symbolLayer(0)
        sl.setBrushStyle(Qt.NoBrush)
        sl.setStrokeColor(QColor("#ffcc66"))
        sl.setStrokeWidth(0.5)
        sl.setStrokeStyle(Qt.DashLine)
        layer.renderer().setSymbol(symbol)

        layer.setReadOnly(True)
        QgsProject.instance().addMapLayer(layer, False)
        group.addLayer(layer)
        layer.triggerRepaint()

        self._log(f"Camada Máscara/ROI criada para mapeamento #{mapeamento_id}")

    def customize_raster_vis(self, layer):
        """Abre dialogo de customizacao para uma camada raster SatIrriga."""
        import json as _json
        from dataclasses import asdict

        image_id = layer.customProperty("satirriga/image_id")
        vis_json = layer.customProperty("satirriga/vis_params")
        if not image_id or not vis_json:
            return

        from .domain.models.raster import VisParams
        from .domain.services.raster_service import build_xyz_url
        from .ui.dialogs.vis_params_dialog import VisParamsDialog

        vis_params = VisParams(**_json.loads(vis_json))

        dialog = VisParamsDialog(vis_params, parent=self.dock)
        if dialog.exec_() == VisParamsDialog.Accepted:
            new_params = dialog.get_params()
            new_url = build_xyz_url(image_id, new_params)
            self._replace_raster_layer(layer, new_url, new_params)

    def _replace_raster_layer(self, old_layer, new_url, new_params):
        """Substitui camada raster XYZ mantendo posicao na arvore.

        QgsRasterLayer XYZ nao suporta alterar URL apos criacao.
        Estrategia: captura posicao -> remove -> cria novo -> insere na mesma posicao.
        """
        import json as _json
        from dataclasses import asdict
        from qgis.core import QgsProject, QgsRasterLayer

        root = QgsProject.instance().layerTreeRoot()
        old_node = root.findLayer(old_layer.id())
        if not old_node:
            return

        parent_group = old_node.parent()
        layer_name = old_layer.name()
        image_id = old_layer.customProperty("satirriga/image_id")
        band_key = old_layer.customProperty("satirriga/band_key")

        # Captura indice na lista de filhos do grupo pai
        children = parent_group.children()
        insert_idx = children.index(old_node) if old_node in children else -1

        # Remove layer antigo
        QgsProject.instance().removeMapLayer(old_layer.id())

        # Cria novo layer — encoda & como %26 na URL para evitar que o
        # parser de URI do QGIS (WMS data provider) confunda query params
        # da URL do tile com parametros do proprio URI
        safe_url = new_url.replace("&", "%26")
        uri = f"type=xyz&url={safe_url}&zmin=0&zmax=18"
        new_layer = QgsRasterLayer(uri, layer_name, "wms")
        if not new_layer.isValid():
            self._log(f"Falha ao recriar camada raster: {layer_name}", Qgis.Warning)
            return

        # Custom properties
        if image_id:
            new_layer.setCustomProperty("satirriga/image_id", image_id)
        new_layer.setCustomProperty(
            "satirriga/vis_params", _json.dumps(asdict(new_params))
        )
        if band_key:
            new_layer.setCustomProperty("satirriga/band_key", band_key)

        QgsProject.instance().addMapLayer(new_layer, False)

        if insert_idx >= 0:
            parent_group.insertLayer(insert_idx, new_layer)
        else:
            parent_group.addLayer(new_layer)

        self._log(f"Camada raster atualizada: {layer_name}")

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
