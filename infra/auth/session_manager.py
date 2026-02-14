"""Gerenciamento de sessao: refresh automatico, countdown, restauracao."""

import json
from urllib.parse import urlencode

from qgis.PyQt.QtCore import QObject, QTimer, QByteArray, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsNetworkAccessManager, QgsMessageLog, Qgis

from ..config.settings import PLUGIN_NAME
from .token_store import TokenStore


class SessionManager(QObject):
    """Orquestra refresh automatico e countdown de sessao."""

    session_refreshed = pyqtSignal()
    session_expired = pyqtSignal()
    countdown_tick = pyqtSignal(int)  # segundos restantes

    def __init__(self, token_store: TokenStore, token_endpoint: str,
                 client_id: str, parent=None):
        super().__init__(parent)
        self._store = token_store
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._nam = QgsNetworkAccessManager.instance()

        # Timer de countdown (1s)
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)

        # Timer de refresh (singleshot, agendado no 75% do lifetime)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)

    def start(self):
        """Inicia timers apos login bem-sucedido."""
        self._schedule_refresh()
        self._countdown_timer.start()

    def stop(self):
        """Para todos os timers."""
        self._countdown_timer.stop()
        self._refresh_timer.stop()

    def _schedule_refresh(self):
        """Agenda refresh no 75% do lifetime do token."""
        remaining = self._store.token_lifetime_remaining
        if remaining <= 0:
            return

        refresh_in_ms = int(remaining * 0.75 * 1000)
        self._refresh_timer.start(max(refresh_in_ms, 5000))

        QgsMessageLog.logMessage(
            f"Refresh agendado em {refresh_in_ms // 1000}s",
            PLUGIN_NAME, Qgis.Info,
        )

    def _on_countdown_tick(self):
        remaining = self._store.token_lifetime_remaining
        self.countdown_tick.emit(remaining)

        if remaining <= 0:
            self.stop()
            self.session_expired.emit()

    def _do_refresh(self):
        """Executa refresh do token via QgsNetworkAccessManager."""
        refresh_token = self._store.refresh_token
        if not refresh_token:
            self.session_expired.emit()
            return

        data = urlencode({
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "refresh_token": refresh_token,
        }).encode("utf-8")

        req = QNetworkRequest(QUrl(self._token_endpoint))
        req.setRawHeader(b"Content-Type", b"application/x-www-form-urlencoded")

        reply = self._nam.post(req, QByteArray(data))
        reply.finished.connect(lambda: self._on_refresh_finished(reply))

    def _on_refresh_finished(self, reply):
        """Processa resposta do refresh."""
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        body = bytes(reply.readAll())
        reply.deleteLater()

        if status and 200 <= status < 300:
            try:
                token_data = json.loads(body)
                self._store.store_tokens(token_data)
                self._schedule_refresh()
                self.session_refreshed.emit()
                QgsMessageLog.logMessage(
                    "Sessao renovada com sucesso", PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Erro ao processar refresh: {e}", PLUGIN_NAME, Qgis.Warning,
                )
                self.session_expired.emit()
        else:
            QgsMessageLog.logMessage(
                f"Refresh falhou (HTTP {status})", PLUGIN_NAME, Qgis.Warning,
            )
            self.stop()
            self.session_expired.emit()

    def try_restore_session(self, callback):
        """Tenta restaurar sessao usando refresh_token persistido.

        :param callback: callable(success: bool) chamado com resultado
        """
        if not self._store.has_refresh_token:
            callback(False)
            return

        refresh_token = self._store.refresh_token
        data = urlencode({
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "refresh_token": refresh_token,
        }).encode("utf-8")

        req = QNetworkRequest(QUrl(self._token_endpoint))
        req.setRawHeader(b"Content-Type", b"application/x-www-form-urlencoded")

        reply = self._nam.post(req, QByteArray(data))
        reply.finished.connect(lambda: self._on_restore_finished(reply, callback))

    def _on_restore_finished(self, reply, callback):
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        body = bytes(reply.readAll())
        reply.deleteLater()

        if status and 200 <= status < 300:
            try:
                token_data = json.loads(body)
                self._store.store_tokens(token_data)
                self.start()
                callback(True)
                return
            except Exception:
                pass

        self._store.clear()
        callback(False)

    def do_logout(self):
        """Envia logout ao SSO (best-effort) e limpa sessao."""
        refresh_token = self._store.refresh_token
        self.stop()

        if refresh_token:
            data = urlencode({
                "client_id": self._client_id,
                "refresh_token": refresh_token,
            }).encode("utf-8")

            logout_url = self._token_endpoint.replace("/token", "/logout")
            req = QNetworkRequest(QUrl(logout_url))
            req.setRawHeader(b"Content-Type", b"application/x-www-form-urlencoded")

            # Best-effort: nao trata resposta
            self._nam.post(req, QByteArray(data))

        self._store.clear()
