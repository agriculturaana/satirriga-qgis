"""Testes unitarios para normalizacao de erros HTTP."""

import json

import pytest

from infra.http.errors import ApiError, normalize_error


class TestApiError:
    def test_is_auth_error(self):
        err = ApiError(status_code=401, message="Unauthorized")
        assert err.is_auth_error is True
        err2 = ApiError(status_code=403, message="Forbidden")
        assert err2.is_auth_error is True
        err3 = ApiError(status_code=500, message="Server Error")
        assert err3.is_auth_error is False

    def test_is_server_error(self):
        err = ApiError(status_code=500, message="Internal Server Error")
        assert err.is_server_error is True
        err2 = ApiError(status_code=200, message="OK")
        assert err2.is_server_error is False

    def test_is_retryable(self):
        for code in (429, 502, 503, 504):
            err = ApiError(status_code=code, message="Error")
            assert err.is_retryable is True
        err = ApiError(status_code=400, message="Bad Request")
        assert err.is_retryable is False


class TestNormalizeError:
    def test_known_status_codes(self):
        err = normalize_error(401, b"")
        assert "login" in err.message.lower() or "sessao" in err.message.lower()

        err = normalize_error(404, b"Not found")
        assert "encontrado" in err.message.lower()

    def test_unknown_status_code(self):
        err = normalize_error(418, b"I'm a teapot")
        assert "418" in err.message

    def test_details_truncated(self):
        long_body = b"x" * 1000
        err = normalize_error(500, long_body)
        assert err.details is not None
        assert len(err.details) <= 500

    def test_business_refusal_shows_server_message(self):
        body = json.dumps({"code": "ZONAL_NOT_READY", "message": "Status alterado durante o encerramento.",
                           "requestId": "req-1"}).encode("utf-8")
        err = normalize_error(409, body)
        assert err.message == "Status alterado durante o encerramento."

    def test_legacy_error_field_is_shown(self):
        body = json.dumps({"error": "Nenhuma geometria encontrada para este Zonal."}).encode("utf-8")
        err = normalize_error(400, body)
        assert err.message == "Nenhuma geometria encontrada para este Zonal."

    def test_expired_session_keeps_login_guidance(self):
        body = json.dumps({"code": "UNAUTHORIZED", "message": "jwt expired"}).encode("utf-8")
        err = normalize_error(401, body)
        assert err.message == "Sessao expirada. Faca login novamente."

    def test_internal_failure_keeps_generic_message(self):
        body = json.dumps({"code": "INTERNAL_ERROR", "message": 'relation "zonais" does not exist'}).encode("utf-8")
        err = normalize_error(500, body)
        assert err.message == "Erro interno do servidor"

    def test_non_json_body_keeps_status_message(self):
        err = normalize_error(409, b"<html>conflict</html>")
        assert err.message == "Erro HTTP 409"
