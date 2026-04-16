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

    def __init__(self, config_repo: ConfigRepository, state=None, parent=None):
        super().__init__(parent)
        self._config = config_repo
        self._state = state

    def get_all(self):
        return self._config.get_all()

    def save(self, values: dict):
        changed_keys = set()
        for key, value in values.items():
            if key not in DEFAULTS:
                continue
            if self._config.get(key) != value:
                changed_keys.add(key)
            self._config.set(key, value)
        QgsMessageLog.logMessage(
            "Configuracoes salvas", PLUGIN_NAME, Qgis.Info,
        )
        if changed_keys and self._state is not None:
            self._state.config_changed.emit(changed_keys)

    def restore_defaults(self):
        previous = self._config.get_all()
        self._config.restore_defaults()
        QgsMessageLog.logMessage(
            "Configuracoes restauradas para defaults", PLUGIN_NAME, Qgis.Info,
        )
        if self._state is None:
            return
        current = self._config.get_all()
        changed_keys = {k for k, v in current.items() if previous.get(k) != v}
        if changed_keys:
            self._state.config_changed.emit(changed_keys)

    def test_connection(self, callback):
        """Testa conexao com a API. callback(success, message)."""
        url = self._config.get("api_base_url").rstrip("/") + "/actuator/health"
        nam = QgsNetworkAccessManager.instance()

        QgsMessageLog.logMessage(
            f"[HTTP] GET {url} (auth=False)", PLUGIN_NAME, Qgis.Info,
        )
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"Accept", b"application/json")

        reply = nam.get(req)
        # Guarda referencia para evitar GC do wrapper Python antes do signal
        self._test_reply = reply
        reply.finished.connect(lambda: self._on_test_finished(reply, callback))

    def _on_test_finished(self, reply, callback):
        self._test_reply = None
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        body = bytes(reply.readAll())
        url = reply.url().toString()
        error_string = reply.errorString()
        reply.deleteLater()

        if status and 200 <= status < 300:
            QgsMessageLog.logMessage(
                f"[HTTP] {status} {url}", PLUGIN_NAME, Qgis.Info,
            )
            callback(True, f"Conexao OK (HTTP {status})")
        elif status:
            QgsMessageLog.logMessage(
                f"[HTTP] {status} {url}", PLUGIN_NAME, Qgis.Warning,
            )
            callback(False, f"Servidor respondeu HTTP {status}")
        else:
            QgsMessageLog.logMessage(
                f"[HTTP] ERRO DE REDE {url} -> {error_string}",
                PLUGIN_NAME, Qgis.Warning,
            )
            callback(False, f"Erro de rede: {error_string}")
