"""Controller de autenticacao — orquestra login/logout/sessao."""

import json
from urllib.parse import urlencode

from qgis.PyQt.QtCore import QObject, QUrl, QByteArray
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsNetworkAccessManager, QgsMessageLog, Qgis

from ...infra.config.settings import PLUGIN_NAME
from ...infra.auth.oidc_pkce import OidcPkceFlow
from ...infra.auth.token_store import TokenStore
from ...infra.auth.session_manager import SessionManager
from ...domain.models.user import UserInfo
from ...app.state.store import AppState


class AuthController(QObject):
    """Orquestra fluxo de autenticacao OIDC PKCE."""

    def __init__(self, state: AppState, config_repo, parent=None):
        super().__init__(parent)
        self._state = state
        self._config = config_repo

        self._token_store = TokenStore()
        self._oidc_flow = None
        self._session_manager = None
        self._nam = QgsNetworkAccessManager.instance()

    @property
    def token_store(self):
        return self._token_store

    def get_access_token(self):
        """Retorna access_token atual (para AuthInterceptor)."""
        return self._token_store.access_token

    def _get_sso_config(self):
        return (
            self._config.get("sso_base_url"),
            self._config.get("sso_realm"),
            self._config.get("sso_client_id"),
        )

    def _get_resource_id(self):
        return self._config.get("sso_resource_id")

    def _token_endpoint(self):
        sso_url, realm, _ = self._get_sso_config()
        return f"{sso_url}/realms/{realm}/protocol/openid-connect/token"

    # ----------------------------------------------------------------
    # Login
    # ----------------------------------------------------------------

    def start_login(self):
        """Inicia fluxo de login via browser."""
        sso_url, realm, client_id = self._get_sso_config()

        self._state.set_loading("auth", True)

        self._oidc_flow = OidcPkceFlow(sso_url, realm, client_id, parent=self)
        self._oidc_flow.auth_code_received.connect(self._on_auth_code_received)
        self._oidc_flow.auth_error.connect(self._on_auth_error)
        self._oidc_flow.start_login()

    def _on_auth_code_received(self, code, redirect_uri):
        """Troca authorization code por tokens."""
        _, _, client_id = self._get_sso_config()

        data = urlencode({
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": self._oidc_flow.code_verifier,
        }).encode("utf-8")

        req = QNetworkRequest(QUrl(self._token_endpoint()))
        req.setRawHeader(b"Content-Type", b"application/x-www-form-urlencoded")

        reply = self._nam.post(req, QByteArray(data))
        reply.finished.connect(lambda: self._on_token_response(reply))

    def _on_token_response(self, reply):
        """Processa resposta do token endpoint."""
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        body = bytes(reply.readAll())
        reply.deleteLater()

        self._state.set_loading("auth", False)

        if status and 200 <= status < 300:
            try:
                token_data = json.loads(body)
                claims = self._token_store.store_tokens(token_data)
                user = UserInfo.from_jwt_claims(claims, self._get_resource_id())

                self._start_session_manager()

                self._state.user = user
                self._state.is_authenticated = True

                QgsMessageLog.logMessage(
                    f"Login bem-sucedido: {user.email}",
                    PLUGIN_NAME, Qgis.Info,
                )
            except Exception as e:
                self._on_auth_error(f"Erro ao processar tokens: {e}")
        else:
            self._on_auth_error(f"Falha na troca de tokens (HTTP {status})")

    def _on_auth_error(self, message):
        self._state.set_loading("auth", False)
        self._state.set_error("auth", message)
        QgsMessageLog.logMessage(
            f"Auth error: {message}", PLUGIN_NAME, Qgis.Warning,
        )

    # ----------------------------------------------------------------
    # Session management
    # ----------------------------------------------------------------

    def _start_session_manager(self):
        """Inicia gerenciamento de sessao (countdown + refresh)."""
        _, _, client_id = self._get_sso_config()

        if self._session_manager:
            self._session_manager.stop()

        self._session_manager = SessionManager(
            token_store=self._token_store,
            token_endpoint=self._token_endpoint(),
            client_id=client_id,
            parent=self,
        )
        self._session_manager.countdown_tick.connect(self._state.session_countdown.emit)
        self._session_manager.session_expired.connect(self._on_session_expired)
        self._session_manager.session_refreshed.connect(self._on_session_refreshed)
        self._session_manager.start()

    def _on_session_expired(self):
        self._state.is_authenticated = False
        self._state.user = None
        self._state.set_error("auth", "Sessao expirada. Faca login novamente.")

    def _on_session_refreshed(self):
        # Atualiza claims (podem ter mudado no refresh)
        claims = TokenStore._decode_jwt_payload(self._token_store.access_token)
        if claims:
            user = UserInfo.from_jwt_claims(claims, self._get_resource_id())
            self._state.user = user

    # ----------------------------------------------------------------
    # Restore session
    # ----------------------------------------------------------------

    def try_restore_session(self):
        """Tenta restaurar sessao com refresh_token persistido."""
        if not self._token_store.has_refresh_token:
            return

        _, _, client_id = self._get_sso_config()

        self._session_manager = SessionManager(
            token_store=self._token_store,
            token_endpoint=self._token_endpoint(),
            client_id=client_id,
            parent=self,
        )
        self._session_manager.countdown_tick.connect(self._state.session_countdown.emit)
        self._session_manager.session_expired.connect(self._on_session_expired)
        self._session_manager.session_refreshed.connect(self._on_session_refreshed)

        self._session_manager.try_restore_session(self._on_restore_result)

    def _on_restore_result(self, success):
        if success:
            claims = TokenStore._decode_jwt_payload(self._token_store.access_token)
            user = UserInfo.from_jwt_claims(claims, self._get_resource_id())
            self._state.user = user
            self._state.is_authenticated = True
            QgsMessageLog.logMessage(
                f"Sessao restaurada: {user.email}", PLUGIN_NAME, Qgis.Info,
            )
        else:
            QgsMessageLog.logMessage(
                "Restauracao de sessao falhou", PLUGIN_NAME, Qgis.Info,
            )

    # ----------------------------------------------------------------
    # Logout
    # ----------------------------------------------------------------

    def logout(self):
        """Executa logout completo."""
        if self._session_manager:
            self._session_manager.do_logout()

        self._token_store.clear()
        self._state.is_authenticated = False
        self._state.user = None

        QgsMessageLog.logMessage("Logout realizado", PLUGIN_NAME, Qgis.Info)

    # ----------------------------------------------------------------
    # Cleanup
    # ----------------------------------------------------------------

    def cleanup(self):
        """Limpeza ao descarregar plugin."""
        if self._session_manager:
            self._session_manager.stop()
        if self._oidc_flow:
            self._oidc_flow.cleanup()
