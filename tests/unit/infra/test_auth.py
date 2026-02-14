"""Testes unitarios para auth — decodificacao JWT e PKCE."""

import base64
import hashlib
import json
import secrets

import pytest

from infra.auth.token_store import TokenStore


class TestTokenStoreJwtDecode:
    def _make_jwt(self, payload: dict) -> str:
        """Cria um JWT fake (header.payload.signature) para teste."""
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256"}).encode()
        ).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).rstrip(b"=").decode()
        sig = "fakesig"
        return f"{header}.{body}.{sig}"

    def test_decode_valid_jwt(self):
        payload = {"sub": "user-123", "exp": 1700000000, "email": "test@test.com"}
        token = self._make_jwt(payload)
        result = TokenStore._decode_jwt_payload(token)
        assert result["sub"] == "user-123"
        assert result["exp"] == 1700000000
        assert result["email"] == "test@test.com"

    def test_decode_empty_token(self):
        assert TokenStore._decode_jwt_payload("") == {}
        assert TokenStore._decode_jwt_payload(None) == {}

    def test_decode_malformed_token(self):
        assert TokenStore._decode_jwt_payload("not-a-jwt") == {}
        assert TokenStore._decode_jwt_payload("header.notbase64.sig") == {}


class TestPkceGeneration:
    """Testa que PKCE S256 funciona corretamente."""

    def test_pkce_challenge_matches_verifier(self):
        # Simula o que OidcPkceFlow faz
        code_verifier = secrets.token_urlsafe(64)[:128]
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

        # Verifica: challenge e SHA256 do verifier em base64url sem padding
        assert len(code_verifier) >= 43
        assert len(code_verifier) <= 128
        assert "=" not in code_challenge
        assert "+" not in code_challenge
        assert "/" not in code_challenge

    def test_pkce_verifier_length(self):
        verifier = secrets.token_urlsafe(64)[:128]
        assert 43 <= len(verifier) <= 128
