from urllib.parse import urlparse

from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsMessageLog, Qgis

from ..config.settings import PLUGIN_NAME


class AuthInterceptor:
    """Injeta Bearer token em requests para hosts autorizados."""

    def __init__(self, token_provider, allowed_hosts=None):
        """
        :param token_provider: callable que retorna access_token ou None
        :param allowed_hosts: lista de hostnames autorizados para receber o token
        """
        self._token_provider = token_provider
        self._allowed_hosts = set(allowed_hosts or [])

    def update_allowed_hosts(self, hosts):
        self._allowed_hosts = set(hosts)
        QgsMessageLog.logMessage(
            f"[Auth] Hosts autorizados: {hosts}",
            PLUGIN_NAME, Qgis.Info,
        )

    def intercept(self, request: QNetworkRequest) -> QNetworkRequest:
        """Adiciona header Authorization se host e permitido."""
        url = request.url().toString()
        host = urlparse(url).hostname

        if host not in self._allowed_hosts:
            QgsMessageLog.logMessage(
                f"[Auth] Host '{host}' nao autorizado (permitidos: {self._allowed_hosts})",
                PLUGIN_NAME, Qgis.Warning,
            )
            return request

        token = self._token_provider()
        if token:
            request.setRawHeader(
                b"Authorization",
                f"Bearer {token}".encode("utf-8"),
            )
        else:
            QgsMessageLog.logMessage(
                f"[Auth] Token nulo para {host} — request sem autorizacao",
                PLUGIN_NAME, Qgis.Warning,
            )

        return request
