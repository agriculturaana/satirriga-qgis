"""Controller de series temporais — consulta API e emite resultados."""

import json

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsMessageLog, Qgis

from ...infra.config.settings import PLUGIN_NAME
from ...infra.http.client import HttpClient


class TimeSeriesController(QObject):
    """Orquestra consultas de serie temporal via API."""

    timeseries_data_ready = pyqtSignal(list)   # List[TimeSeriesResult]
    timeseries_error = pyqtSignal(str)         # mensagem de erro

    def __init__(self, http_client: HttpClient, config_repo, parent=None):
        super().__init__(parent)
        self._http = http_client
        self._config = config_repo
        self._pending_id = None

        self._http.request_finished.connect(self._on_request_finished)
        self._http.request_error.connect(self._on_request_error)

    def _api_url(self, path):
        base = self._config.get("api_base_url").rstrip("/")
        return f"{base}{path}"

    def fetch_timeseries(self, points, start_date, end_date):
        """POST /api/timeseries/points com pontos e intervalo de datas.

        Args:
            points: Lista de TimeSeriesPoint.
            start_date: Data inicial (YYYY-MM-DD).
            end_date: Data final (YYYY-MM-DD).
        """
        url = self._api_url(
            f"/timeseries/points?start_date={start_date}&end_date={end_date}"
        )
        payload = json.dumps({
            "points": [
                {"id": p.id, "color": p.color, "lon": p.lon, "lat": p.lat}
                for p in points
            ]
        }).encode("utf-8")
        self._pending_id = self._http.post_json(url, payload)
        QgsMessageLog.logMessage(
            f"[TimeSeries] Consultando {len(points)} ponto(s) "
            f"de {start_date} a {end_date}",
            PLUGIN_NAME, Qgis.Info,
        )

    def _on_request_finished(self, request_id, status_code, body):
        if request_id != self._pending_id:
            return
        self._pending_id = None
        try:
            from ...domain.models.timeseries import TimeSeriesResult
            data = json.loads(body)
            if not isinstance(data, list):
                data = [data]
            results = [TimeSeriesResult.from_dict(item) for item in data]
            self.timeseries_data_ready.emit(results)
            QgsMessageLog.logMessage(
                f"[TimeSeries] {len(results)} serie(s) recebida(s)",
                PLUGIN_NAME, Qgis.Info,
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"[TimeSeries] Erro ao parsear resposta: {e}",
                PLUGIN_NAME, Qgis.Warning,
            )
            self.timeseries_error.emit(str(e))

    def _on_request_error(self, request_id, error_msg):
        if request_id != self._pending_id:
            return
        self._pending_id = None
        QgsMessageLog.logMessage(
            f"[TimeSeries] Erro na requisição: {error_msg}",
            PLUGIN_NAME, Qgis.Warning,
        )
        self.timeseries_error.emit(error_msg)
