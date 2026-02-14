"""Armazenamento seguro de tokens via QgsSettings."""

import base64
import json
import time

from qgis.core import QgsSettings

from ..config.settings import AUTH_NAMESPACE


class TokenStore:
    """Gerencia tokens OAuth2.

    - access_token: somente em memoria (nunca persistido)
    - refresh_token: persistido em QgsSettings
    - NUNCA logar tokens
    """

    def __init__(self):
        self._settings = QgsSettings()
        self._access_token = None
        self._token_exp = None

    @property
    def access_token(self):
        return self._access_token

    @access_token.setter
    def access_token(self, value):
        self._access_token = value

    @property
    def token_exp(self):
        return self._token_exp

    @token_exp.setter
    def token_exp(self, value):
        self._token_exp = value

    @property
    def refresh_token(self):
        return self._settings.value(f"{AUTH_NAMESPACE}/refresh_token", None)

    @refresh_token.setter
    def refresh_token(self, value):
        if value:
            self._settings.setValue(f"{AUTH_NAMESPACE}/refresh_token", value)
        else:
            self._settings.remove(f"{AUTH_NAMESPACE}/refresh_token")

    @property
    def has_refresh_token(self):
        return bool(self.refresh_token)

    @property
    def token_lifetime_remaining(self) -> int:
        """Segundos restantes ate expiracao do access_token."""
        if not self._token_exp:
            return 0
        return max(0, int(self._token_exp - time.time()))

    def store_tokens(self, token_response: dict):
        """Armazena tokens de uma resposta do token endpoint."""
        self.access_token = token_response.get("access_token")
        self.refresh_token = token_response.get("refresh_token")

        # Decodifica exp do JWT (sem verificar assinatura — feito pelo server)
        claims = self._decode_jwt_payload(self.access_token)
        self._token_exp = claims.get("exp")

        return claims

    def clear(self):
        """Remove todos os tokens."""
        self._access_token = None
        self._token_exp = None
        self.refresh_token = None

    @staticmethod
    def _decode_jwt_payload(token: str) -> dict:
        """Decodifica o payload de um JWT sem verificar assinatura."""
        if not token:
            return {}
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return {}
            # Adiciona padding se necessario
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            decoded = base64.urlsafe_b64decode(payload)
            return json.loads(decoded)
        except Exception:
            return {}
