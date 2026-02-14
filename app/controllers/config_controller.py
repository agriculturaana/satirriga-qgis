"""Controller de configuracoes."""

import json
from urllib.parse import urlparse

from qgis.PyQt.QtCore import QObject, QUrl, QByteArray
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsNetworkAccessManager, QgsMessageLog, Qgis

from ...infra.config.settings import PLUGIN_NAME, DEFAULTS
from ...infra.config.repository import ConfigRepository


class ConfigController(QObject):
    """CRUD de configuracoes do plugin."""

    def __init__(self, config_repo: ConfigRepository, parent=None):
        super().__init__(parent)
        self._config = config_repo

    def get_all(self):
        return self._config.get_all()

    def save(self, values: dict):
        for key, value in values.items():
            if key in DEFAULTS:
                self._config.set(key, value)
        QgsMessageLog.logMessage(
            "Configuracoes salvas", PLUGIN_NAME, Qgis.Info,
        )

    def restore_defaults(self):
        self._config.restore_defaults()
        QgsMessageLog.logMessage(
            "Configuracoes restauradas para defaults", PLUGIN_NAME, Qgis.Info,
        )

    def test_connection(self, callback):
        """Testa conexao com a API. callback(success, message)."""
        url = self._config.get("api_base_url").rstrip("/") + "/actuator/health"
        nam = QgsNetworkAccessManager.instance()

        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"Accept", b"application/json")

        reply = nam.get(req)
        reply.finished.connect(lambda: self._on_test_finished(reply, callback))

    def _on_test_finished(self, reply, callback):
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        body = bytes(reply.readAll())
        reply.deleteLater()

        if status and 200 <= status < 300:
            callback(True, f"Conexao OK (HTTP {status})")
        elif status:
            callback(False, f"Servidor respondeu HTTP {status}")
        else:
            callback(False, f"Erro de rede: {reply.errorString()}")
