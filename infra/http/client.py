import uuid

from qgis.PyQt.QtCore import QObject, QUrl, QByteArray, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsNetworkAccessManager, QgsMessageLog, Qgis

from ...infra.config.settings import PLUGIN_NAME
from .auth_interceptor import AuthInterceptor
from .errors import normalize_error


class HttpClient(QObject):
    """Wrapper assincrono sobre QgsNetworkAccessManager.

    Cada request recebe um UUID para correlacao. Resultados sao
    entregues via signals.
    """

    request_finished = pyqtSignal(str, int, bytes)  # request_id, status_code, body
    request_error = pyqtSignal(str, str)             # request_id, error_msg

    def __init__(self, auth_interceptor: AuthInterceptor = None, parent=None):
        super().__init__(parent)
        self._nam = QgsNetworkAccessManager.instance()
        self._interceptor = auth_interceptor
        self._pending = {}  # request_id -> QNetworkReply

    def _make_request(self, url: str, method: str = "GET",
                      data: bytes = None, content_type: str = None) -> str:
        """Envia request e retorna request_id."""
        request_id = str(uuid.uuid4())

        qurl = QUrl(url)
        req = QNetworkRequest(qurl)
        req.setRawHeader(b"Accept", b"application/json")

        if content_type:
            req.setRawHeader(b"Content-Type", content_type.encode("utf-8"))

        if self._interceptor:
            req = self._interceptor.intercept(req)

        if method == "GET":
            reply = self._nam.get(req)
        elif method == "POST":
            reply = self._nam.post(req, QByteArray(data or b""))
        elif method == "PUT":
            reply = self._nam.put(req, QByteArray(data or b""))
        elif method == "DELETE":
            reply = self._nam.deleteResource(req)
        else:
            self.request_error.emit(request_id, f"Metodo HTTP nao suportado: {method}")
            return request_id

        self._pending[request_id] = reply
        reply.finished.connect(lambda: self._on_finished(request_id, reply))

        return request_id

    def _on_finished(self, request_id: str, reply):
        """Processa resposta do NAM."""
        self._pending.pop(request_id, None)

        error = reply.error()
        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)

        if status_code is None:
            status_code = 0

        body = bytes(reply.readAll())
        reply.deleteLater()

        if error and status_code == 0:
            self.request_error.emit(request_id, f"Erro de rede: {reply.errorString()}")
            return

        if 200 <= status_code < 300:
            self.request_finished.emit(request_id, status_code, body)
        else:
            api_error = normalize_error(status_code, body)
            self.request_error.emit(request_id, api_error.message)

            if api_error.is_auth_error:
                QgsMessageLog.logMessage(
                    f"Auth error ({status_code})", PLUGIN_NAME, Qgis.Warning
                )

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def get(self, url: str) -> str:
        return self._make_request(url, "GET")

    def post_json(self, url: str, payload: bytes) -> str:
        return self._make_request(
            url, "POST", data=payload, content_type="application/json"
        )

    def post_form(self, url: str, payload: bytes) -> str:
        return self._make_request(
            url, "POST", data=payload,
            content_type="application/x-www-form-urlencoded",
        )

    def post_multipart(self, url: str, multipart) -> str:
        """Envia multipart/form-data. `multipart` e um QHttpMultiPart."""
        request_id = str(uuid.uuid4())

        qurl = QUrl(url)
        req = QNetworkRequest(qurl)

        if self._interceptor:
            req = self._interceptor.intercept(req)

        reply = self._nam.post(req, multipart)
        multipart.setParent(reply)

        self._pending[request_id] = reply
        reply.finished.connect(lambda: self._on_finished(request_id, reply))

        return request_id

    def cancel(self, request_id: str):
        reply = self._pending.pop(request_id, None)
        if reply:
            reply.abort()
