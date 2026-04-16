from qgis.PyQt.QtCore import QObject, pyqtSignal


class AppState(QObject):
    """Estado centralizado do plugin com pyqtSignals para comunicacao reativa."""

    # Autenticacao
    auth_state_changed = pyqtSignal(bool)           # is_authenticated
    user_changed = pyqtSignal(object)                # UserInfo | None
    session_countdown = pyqtSignal(int)              # segundos restantes

    # Catalogo zonal
    catalogo_changed = pyqtSignal(list, dict)        # List[CatalogoItem], pagination dict
    upload_history_changed = pyqtSignal(list, dict)  # List[UploadHistoryItem], pagination dict
    upload_progress_changed = pyqtSignal(dict)       # UploadBatchStatus dict
    conflict_detected = pyqtSignal(str)              # batchUuid
    upload_batch_completed = pyqtSignal(str, dict)   # batchUuid, summary

    # Raster
    raster_layers_ready = pyqtSignal(object)           # RasterHierarchy

    # Mascara/ROI
    mascara_layer_ready = pyqtSignal(int, object)      # mapeamento_id, geojson_geometry

    # Homologacao
    catalogo_homologacao_changed = pyqtSignal(list, dict)  # List[CatalogoItem], pagination dict
    parecer_emitido = pyqtSignal(dict)                # {parecerId, status, message}
    mapeamento_suprimido = pyqtSignal(dict)           # response data do DELETE
    mapeamento_encerrado = pyqtSignal(dict)           # {mapeamentoId, message}
    reprocess_overlay_done = pyqtSignal(int, str)     # zonal_id, message
    zonal_status_polled = pyqtSignal(int, str)        # zonal_id, status_atual
    zonal_finalizado = pyqtSignal(int, str)           # zonal_id, novo_status

    # UI feedback
    loading_changed = pyqtSignal(str, bool)          # (operation, is_loading)
    error_occurred = pyqtSignal(str, str)             # (operation, message)

    # Configuracao
    config_changed = pyqtSignal(set)                  # chaves alteradas

    def __init__(self, parent=None):
        super().__init__(parent)
        self._authenticated = False
        self._user = None
        self._catalogo_items = []

    @property
    def is_authenticated(self):
        return self._authenticated

    @is_authenticated.setter
    def is_authenticated(self, value):
        if self._authenticated != value:
            self._authenticated = value
            self.auth_state_changed.emit(value)

    @property
    def user(self):
        return self._user

    @user.setter
    def user(self, value):
        self._user = value
        self.user_changed.emit(value)

    @property
    def catalogo_items(self):
        return self._catalogo_items

    @catalogo_items.setter
    def catalogo_items(self, value):
        """Aceita list ou tuple(list, dict) para suportar paginação."""
        if isinstance(value, tuple) and len(value) == 2:
            self._catalogo_items, pagination = value
            self.catalogo_changed.emit(self._catalogo_items, pagination)
        else:
            self._catalogo_items = value
            self.catalogo_changed.emit(value, {})

    def set_loading(self, operation, is_loading):
        self.loading_changed.emit(operation, is_loading)

    def set_error(self, operation, message):
        self.error_occurred.emit(operation, message)

    def reset(self):
        self.is_authenticated = False
        self.user = None
        self.catalogo_items = []
