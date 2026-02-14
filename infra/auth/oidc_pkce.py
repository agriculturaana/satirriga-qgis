"""OIDC PKCE Authorization Code Flow via browser externo + loopback HTTP."""

import base64
import hashlib
import secrets
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

from qgis.PyQt.QtCore import QObject, QUrl, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.core import QgsMessageLog, Qgis

from ..config.settings import PLUGIN_NAME

# Range de portas para o loopback server
_PORT_RANGE = range(8400, 8411)


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handler HTTP para receber o callback do Keycloak."""

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        if error:
            html = (
                "<html><body><h2>Erro no login</h2>"
                f"<p>{error}: {params.get('error_description', [''])[0]}</p>"
                "<p>Pode fechar esta janela.</p></body></html>"
            )
        else:
            html = (
                "<html><body><h2>Login concluido</h2>"
                "<p>Pode fechar esta janela e voltar ao QGIS.</p></body></html>"
            )

        self.wfile.write(html.encode("utf-8"))

        # Armazena resultado no servidor para OidcPkceFlow consumir
        self.server.auth_code = code
        self.server.auth_state = state
        self.server.auth_error = error

        # Agenda shutdown (nao pode chamar direto do handler)
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, format, *args):
        """Suprime logs do HTTPServer."""
        pass


class OidcPkceFlow(QObject):
    """Gerencia o fluxo OIDC Authorization Code + PKCE via browser."""

    # Signals
    auth_code_received = pyqtSignal(str, str)  # (code, redirect_uri)
    auth_error = pyqtSignal(str)               # error message

    def __init__(self, sso_base_url, realm, client_id, parent=None):
        super().__init__(parent)
        self._sso_base_url = sso_base_url.rstrip("/")
        self._realm = realm
        self._client_id = client_id

        self._code_verifier = None
        self._code_challenge = None
        self._state = None
        self._server = None
        self._server_thread = None
        self._redirect_uri = None

    @property
    def code_verifier(self):
        return self._code_verifier

    def _generate_pkce(self):
        """Gera code_verifier e code_challenge (S256)."""
        self._code_verifier = secrets.token_urlsafe(64)[:128]
        digest = hashlib.sha256(self._code_verifier.encode("ascii")).digest()
        self._code_challenge = (
            base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        )

    def _generate_state(self):
        self._state = secrets.token_urlsafe(32)

    def _start_loopback_server(self) -> bool:
        """Tenta iniciar servidor HTTP em uma porta do range."""
        for port in _PORT_RANGE:
            try:
                self._server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
                self._server.auth_code = None
                self._server.auth_state = None
                self._server.auth_error = None
                self._redirect_uri = f"http://127.0.0.1:{port}/callback"

                self._server_thread = threading.Thread(
                    target=self._server.serve_forever, daemon=True
                )
                self._server_thread.start()

                QgsMessageLog.logMessage(
                    f"Loopback server iniciado na porta {port}",
                    PLUGIN_NAME, Qgis.Info,
                )
                return True
            except OSError:
                continue

        QgsMessageLog.logMessage(
            "Falha ao iniciar loopback server em todas as portas",
            PLUGIN_NAME, Qgis.Critical,
        )
        return False

    def start_login(self):
        """Inicia o fluxo de login: abre browser para autenticacao."""
        self._generate_pkce()
        self._generate_state()

        if not self._start_loopback_server():
            self.auth_error.emit("Falha ao iniciar servidor de callback local.")
            return

        auth_endpoint = (
            f"{self._sso_base_url}/realms/{self._realm}"
            f"/protocol/openid-connect/auth"
        )
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": "openid profile email",
            "code_challenge": self._code_challenge,
            "code_challenge_method": "S256",
            "state": self._state,
        }
        auth_url = f"{auth_endpoint}?{urlencode(params)}"

        QgsMessageLog.logMessage(
            "Abrindo browser para autenticacao...",
            PLUGIN_NAME, Qgis.Info,
        )
        QDesktopServices.openUrl(QUrl(auth_url))

        # Aguarda callback em thread separada, despacha para main thread
        threading.Thread(target=self._wait_for_callback, daemon=True).start()

    def _wait_for_callback(self):
        """Aguarda o server thread encerrar (callback recebido) e despacha."""
        if self._server_thread:
            self._server_thread.join(timeout=300)  # 5 min timeout

        if self._server is None:
            return

        code = self._server.auth_code
        state = self._server.auth_state
        error = self._server.auth_error

        # Despacha para main thread via QTimer
        if error:
            QTimer.singleShot(0, lambda: self.auth_error.emit(f"Erro SSO: {error}"))
        elif state != self._state:
            QTimer.singleShot(
                0, lambda: self.auth_error.emit("Falha de seguranca: state invalido.")
            )
        elif code:
            redirect_uri = self._redirect_uri
            QTimer.singleShot(
                0, lambda: self.auth_code_received.emit(code, redirect_uri)
            )
        else:
            QTimer.singleShot(
                0, lambda: self.auth_error.emit("Timeout aguardando autenticacao.")
            )

    def token_endpoint(self) -> str:
        return (
            f"{self._sso_base_url}/realms/{self._realm}"
            f"/protocol/openid-connect/token"
        )

    def logout_endpoint(self) -> str:
        return (
            f"{self._sso_base_url}/realms/{self._realm}"
            f"/protocol/openid-connect/logout"
        )

    def cleanup(self):
        """Desliga o loopback server se ainda estiver rodando."""
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass
            self._server = None
