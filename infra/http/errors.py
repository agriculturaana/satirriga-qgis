from dataclasses import dataclass
from typing import Optional


@dataclass
class ApiError:
    status_code: int
    message: str
    operation: str = ""
    details: Optional[str] = None

    @property
    def is_auth_error(self):
        return self.status_code in (401, 403)

    @property
    def is_server_error(self):
        return 500 <= self.status_code < 600

    @property
    def is_retryable(self):
        return self.status_code in (429, 502, 503, 504)


def normalize_error(status_code: int, body: bytes, operation: str = "") -> ApiError:
    """Normaliza erro HTTP para ApiError com mensagem amigavel."""
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        text = ""

    messages = {
        400: "Requisicao invalida",
        401: "Sessao expirada. Faca login novamente.",
        403: "Acesso negado",
        404: "Recurso nao encontrado",
        429: "Muitas requisicoes. Tente novamente em instantes.",
        500: "Erro interno do servidor",
        502: "Servidor indisponivel (bad gateway)",
        503: "Servico temporariamente indisponivel",
        504: "Timeout do servidor",
    }

    message = messages.get(status_code, f"Erro HTTP {status_code}")

    return ApiError(
        status_code=status_code,
        message=message,
        operation=operation,
        details=text[:500] if text else None,
    )
