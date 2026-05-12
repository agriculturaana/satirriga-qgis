"""Servico de consulta das camadas-base (municipios, bacias, empreendimentos).

Encapsula GET /api/bases/:layer?bbox=... e re-emite o resultado parseado
via sinais especificos por camada. Usa HttpClient (que ja injeta Bearer
token via AuthInterceptor) e nao bloqueia a thread principal.
"""

import json

from qgis.PyQt.QtCore import QObject, pyqtSignal


_VALID_LAYERS = ("municipios", "bacias", "empreendimentos")


class BasesService(QObject):
    """Cliente do endpoint REST de camadas-base."""

    layer_loaded = pyqtSignal(str, dict)   # layer_id, feature_collection_dict
    layer_failed = pyqtSignal(str, str)    # layer_id, error_message

    def __init__(self, http_client, config_repo, parent=None):
        super().__init__(parent)
        self._http_client = http_client
        self._config_repo = config_repo
        self._pending = {}  # request_id -> layer_id

        http_client.request_finished.connect(self._on_finished)
        http_client.request_error.connect(self._on_error)

    def fetch(self, layer_id: str, bbox_4674) -> str:
        """Dispara GET /api/bases/{layer_id}?bbox=minX,minY,maxX,maxY.

        ``bbox_4674`` deve ser uma tupla (minX, minY, maxX, maxY) em EPSG:4674.
        Retorna o request_id; o resultado chega via ``layer_loaded`` ou
        ``layer_failed`` referenciando o ``layer_id`` informado.
        """
        if layer_id not in _VALID_LAYERS:
            raise ValueError(f"layer_id invalido: {layer_id}")

        min_x, min_y, max_x, max_y = bbox_4674
        api_base = self._config_repo.get("api_base_url").rstrip("/")
        url = (
            f"{api_base}/bases/{layer_id}"
            f"?bbox={min_x},{min_y},{max_x},{max_y}"
        )

        request_id = self._http_client.get(url)
        self._pending[request_id] = layer_id
        return request_id

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_finished(self, request_id: str, status_code: int, body: bytes):
        layer_id = self._pending.pop(request_id, None)
        if layer_id is None:
            return  # Resposta nao pertence a este servico

        try:
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            payload = json.loads(body) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.layer_failed.emit(
                layer_id, f"Resposta invalida do servidor: {exc}"
            )
            return

        if (
            not isinstance(payload, dict)
            or payload.get("type") != "FeatureCollection"
        ):
            self.layer_failed.emit(
                layer_id, "Formato inesperado: esperava FeatureCollection."
            )
            return

        self.layer_loaded.emit(layer_id, payload)

    def _on_error(self, request_id: str, error_msg: str):
        layer_id = self._pending.pop(request_id, None)
        if layer_id is None:
            return

        # 413 do servidor chega aqui (HttpClient considera nao-2xx como erro).
        # A mensagem normalizada por errors.normalize_error preserva o motivo.
        if "PAYLOAD_TOO_LARGE" in error_msg or "413" in error_msg:
            friendly = (
                "Area visivel grande demais para a camada "
                f"'{layer_id}'. Aproxime o zoom e tente novamente."
            )
            self.layer_failed.emit(layer_id, friendly)
        else:
            self.layer_failed.emit(layer_id, error_msg)

    def cleanup(self):
        """Desconecta sinais do HttpClient para descarregamento do plugin."""
        try:
            self._http_client.request_finished.disconnect(self._on_finished)
            self._http_client.request_error.disconnect(self._on_error)
        except (TypeError, RuntimeError):
            pass
        self._pending.clear()
