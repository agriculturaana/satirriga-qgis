"""Testes unitarios para ConfigController — logica de CRUD config.

Como ConfigController usa imports relativos do package do plugin (QGIS),
testamos a logica equivalente usando FakeConfigRepository que replica
o contrato do ConfigController.save() / restore_defaults().
"""

import pytest

from infra.config.settings import DEFAULTS


class FakeConfigRepository:
    """In-memory ConfigRepository para testes."""

    def __init__(self):
        self._data = dict(DEFAULTS)

    def get(self, name):
        return self._data.get(name, DEFAULTS.get(name))

    def set(self, name, value):
        self._data[name] = value

    def get_all(self):
        return dict(self._data)

    def restore_defaults(self):
        self._data = dict(DEFAULTS)


def _save_config(repo, values):
    """Replica logica do ConfigController.save()."""
    for key, value in values.items():
        if key in DEFAULTS:
            repo.set(key, value)


class TestConfigControllerLogic:
    """Testa logica do controller sem precisar importar o modulo real."""

    def setup_method(self):
        self.repo = FakeConfigRepository()

    def test_get_all_returns_all_keys(self):
        result = self.repo.get_all()
        assert isinstance(result, dict)
        assert set(result.keys()) == set(DEFAULTS.keys())

    def test_save_valid_keys(self):
        _save_config(self.repo, {
            "api_base_url": "https://new-api.example.com",
            "page_size": 25,
        })
        assert self.repo.get("api_base_url") == "https://new-api.example.com"
        assert self.repo.get("page_size") == 25

    def test_save_ignores_invalid_keys(self):
        original = dict(self.repo._data)
        _save_config(self.repo, {"nonexistent_key": "value"})
        assert self.repo._data == original

    def test_save_empty_dict(self):
        original = dict(self.repo._data)
        _save_config(self.repo, {})
        assert self.repo._data == original

    def test_restore_defaults(self):
        self.repo.set("api_base_url", "https://modified.url")
        self.repo.set("page_size", 99)

        self.repo.restore_defaults()

        assert self.repo.get("api_base_url") == DEFAULTS["api_base_url"]
        assert self.repo.get("page_size") == DEFAULTS["page_size"]

    def test_save_all_default_keys(self):
        """Deve aceitar todas as chaves do DEFAULTS."""
        modified = {k: v for k, v in DEFAULTS.items()}
        modified["api_base_url"] = "https://test.api.com"
        _save_config(self.repo, modified)
        assert self.repo.get("api_base_url") == "https://test.api.com"

    def test_defaults_have_required_keys(self):
        """Valida que DEFAULTS contem todas as chaves necessarias."""
        required = [
            "api_base_url", "sso_base_url", "sso_realm", "sso_client_id",
            "environment", "gpkg_base_dir", "page_size",
            "polling_interval_ms", "auto_zoom_on_load", "log_level",
        ]
        for key in required:
            assert key in DEFAULTS, f"Chave '{key}' ausente em DEFAULTS"

    def test_defaults_types(self):
        """Valida tipos dos valores em DEFAULTS."""
        assert isinstance(DEFAULTS["api_base_url"], str)
        assert isinstance(DEFAULTS["page_size"], int)
        assert isinstance(DEFAULTS["auto_zoom_on_load"], bool)
        assert isinstance(DEFAULTS["polling_interval_ms"], int)
