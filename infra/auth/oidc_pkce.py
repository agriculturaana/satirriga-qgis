"""OIDC PKCE Authorization Code Flow via browser externo + loopback HTTP."""

import base64
import hashlib
import secrets
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

from qgis.PyQt.QtCore import QObject, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.core import QgsMessageLog, Qgis

from ..config.settings import PLUGIN_NAME

# Range de portas para o loopback server
_PORT_RANGE = range(8400, 8411)


def _build_callback_html(success: bool, error_msg: str = "") -> str:
    """Gera HTML de callback no padrao visual do SatIrriga."""
    if success:
        title = "Autenticacao bem-sucedida!"
        subtitle = "Pode fechar esta janela e voltar ao QGIS."
        icon_svg = (
            '<svg width="64" height="64" viewBox="0 0 24 24" fill="none" '
            'xmlns="http://www.w3.org/2000/svg" style="margin:0 auto 16px">'
            '<circle cx="12" cy="12" r="11" stroke="#4CAF50" stroke-width="2"/>'
            '<path d="M7 12.5L10.5 16L17 8" stroke="#4CAF50" stroke-width="2.5" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>'
        )
    else:
        title = "Erro na autenticacao"
        subtitle = f"{error_msg}<br>Pode fechar esta janela e tentar novamente."
        icon_svg = (
            '<svg width="64" height="64" viewBox="0 0 24 24" fill="none" '
            'xmlns="http://www.w3.org/2000/svg" style="margin:0 auto 16px">'
            '<circle cx="12" cy="12" r="11" stroke="#F44336" stroke-width="2"/>'
            '<path d="M8 8L16 16M16 8L8 16" stroke="#F44336" stroke-width="2.5" '
            'stroke-linecap="round"/></svg>'
        )

    # Logo SVG do SatIrriga (simplificado das formas principais)
    logo_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="3500 400 12500 9000" '
        'style="height:6rem;width:auto;margin:0 auto">'
        '<defs><style>'
        '.fil0{fill:#91BBE3}.fil1{fill:#223079}.fil2{fill:#2892D0}'
        '.fil4{fill:#2B94CE}.fil5{fill:#8EB9DB}.fil6{fill:#1D3478}'
        '</style></defs>'
        '<path class="fil0" d="M8080.2 4590.4c21.57,11.88 48.68,27.16 80.29,'
        '45.17l1298.64 719.58c-181.2,-653.2 152.38,-1378.18 472.38,-1934.66 '
        '174.42,-303.32 765.42,-1368.76 977.49,-1564.4 179.09,142.35 836.38,'
        '1294.98 980.92,1561.41 362.26,667.7 622.91,1190.62 469.46,1971.69l'
        '2175.47 -1225.77 354.31 -203.27c107.41,-59.58 216.54,-122.19 320.83,'
        '-181.4 197.01,-111.84 446.24,-268.25 647.76,-362.63l-4900.52 -2794.18 '
        '-2654.45 1499.26c225.97,673.99 214.2,1452.22 -89.06,2185.76 -40.41,'
        '97.74 -85.08,192.22 -133.52,283.44z"/>'
        '<path class="fil1" d="M6221.48 6095.67l-101.56 43.98 4837.59 2754.16 '
        '4883.01 -2810.86 -1008.09 -574.04c-3.42,-0.55 -24.81,-13.89 -38.09,'
        '-20.2l-904.74 516.52c-12.67,7.52 -23.67,13.83 -32.73,18.69 -685.41,'
        '367.65 -2382.35,1414.25 -2895.13,1652.45l-1866.79 -1062.9c-201.68,'
        '-121.55 -1564.97,-930.45 -1839.41,-1033.85 -312.02,244.1 -664.59,'
        '419.75 -1034.06,516.05z"/>'
        '<path class="fil2" d="M12359.38 5389.19c-130.89,273.27 -218.46,486.92 '
        '-449.55,673.34 -221.21,178.45 -488.09,335.81 -787.11,352.9l4.11 '
        '-279.85 153.83 0c2.84,0 5.63,-0.31 8.31,-0.88 11.26,-0.74 20.88,'
        '-7.77 25.35,-17.58 4.01,-6.23 6.34,-13.62 6.34,-21.54l0 -251.32c0,'
        '-22 -18,-40 -40,-40l-133.48 0 -23.22 -1.17 0 -72.06c0,-22 -18,-40 '
        '-40,-40l-292.6 0c-22,0 -40,18 -40,40l0 73.23 -158.57 0c-13.09,0 '
        '-24.77,6.37 -32.08,16.17 -5.23,5.43 -8.46,12.81 -8.46,20.88l0 '
        '263.46c0,16.5 13.5,30 30,30l2.55 0c2.58,0.53 5.26,0.81 7.99,0.81l'
        '156.29 0 0.49 290.2c-581.75,-42.84 -1149.89,-512.71 -1290.44,'
        '-1070.63l-1379.21 -764.23c-211.07,397.26 -495.14,731.08 -824.38,'
        '988.7 274.44,103.4 1637.73,912.3 1839.41,1033.85l1866.79 1062.9c'
        '512.78,-238.2 2209.72,-1284.8 2895.13,-1652.45l1464.65 -836.18 '
        '502.05 -311.4 -1288.72 -712.92 -2175.47 1225.77z"/></svg>'
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SatIrriga - Autenticacao</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#f5f5f5;overflow:hidden}}
.wave{{position:fixed;bottom:-10rem;left:0;width:100%;height:auto;z-index:0}}
.card{{position:relative;z-index:1;text-align:center;padding:48px 40px}}
.title{{font-size:28px;font-weight:700;color:#223079;margin:16px 0 8px}}
.subtitle{{font-size:16px;color:#546e7a;line-height:1.5}}
</style>
</head>
<body>
<svg class="wave" viewBox="0 0 960 540" preserveAspectRatio="none"
xmlns="http://www.w3.org/2000/svg">
<defs><linearGradient id="wg" x1="0%" y1="0%" x2="100%" y2="0%">
<stop offset="0%" style="stop-color:#1D3478"/><stop offset="50%" style="stop-color:#2892D0"/>
<stop offset="100%" style="stop-color:#91BBE3"/></linearGradient></defs>
<rect width="960" height="540" fill="#f5f5f5"/>
<path d="M0 331L26.7 321C53.3 311 106.7 291 160 291C213.3 291 266.7 311 320
329.5C373.3 348 426.7 365 480 373.2C533.3 381.3 586.7 380.7 640 373.8C693.3
367 746.7 354 800 341.2C853.3 328.3 906.7 315.7 933.3 309.3L960 303L960
541L0 541Z" fill="url(#wg)"/></svg>
<div class="card">
{logo_svg}
{icon_svg}
<div class="title">{title}</div>
<p class="subtitle">{subtitle}</p>
</div>
</body></html>"""


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
            error_desc = params.get("error_description", [""])[0]
            html = _build_callback_html(
                success=False,
                error_msg=f"{error}: {error_desc}" if error_desc else error,
            )
        else:
            html = _build_callback_html(success=True)

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

        # Emite signals direto — cross-thread emit usa QueuedConnection
        # automaticamente (OidcPkceFlow tem afinidade com a main thread).
        # QTimer.singleShot nao funciona de threading.Thread (sem event loop Qt).
        if error:
            self.auth_error.emit(f"Erro SSO: {error}")
        elif state != self._state:
            self.auth_error.emit("Falha de seguranca: state invalido.")
        elif code:
            self.auth_code_received.emit(code, self._redirect_uri)
        else:
            self.auth_error.emit("Timeout aguardando autenticacao.")

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
                self._server.server_close()
            except Exception:
                pass
            self._server = None
