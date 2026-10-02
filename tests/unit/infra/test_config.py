"""Testes unitarios para ConfigRepository."""

import configparser
import os

import pytest
from unittest.mock import MagicMock, patch


class FakeQgsSettings:
    """Mock de QgsSettings para testes — armazena em dict."""

    def __init__(self):
        self._data = {}

    def value(self, key, default=None):
        return self._data.get(key, default)

    def setValue(self, key, value):
        self._data[key] = value


# Mock modulos QGIS
with patch.dict("sys.modules", {
    "qgis": MagicMock(),
    "qgis.core": MagicMock(),
}):
    import sys
    # Substitui QgsSettings pelo fake
    sys.modules["qgis.core"].QgsSettings = FakeQgsSettings

    from infra.config.repository import ConfigRepository
    from infra.config.settings import DEFAULTS, PLUGIN_VERSION, SETTINGS_NAMESPACE


class TestConfigRepository:
    def setup_method(self):
        self.repo = ConfigRepository()

    def test_get_returns_default_when_not_set(self):
        assert self.repo.get("api_base_url") == DEFAULTS["api_base_url"]
        assert self.repo.get("page_size") == DEFAULTS["page_size"]
        assert self.repo.get("auto_zoom_on_load") == DEFAULTS["auto_zoom_on_load"]

    def test_set_and_get(self):
        self.repo.set("api_base_url", "https://custom.api.com")
        assert self.repo.get("api_base_url") == "https://custom.api.com"

    def test_set_int_value(self):
        self.repo.set("page_size", 25)
        assert self.repo.get("page_size") == 25
        assert isinstance(self.repo.get("page_size"), int)

    def test_set_bool_value(self):
        self.repo.set("auto_zoom_on_load", False)
        assert self.repo.get("auto_zoom_on_load") is False

    def test_bool_string_coercion(self):
        """QgsSettings armazena booleans como strings."""
        self.repo.set("auto_zoom_on_load", "true")
        assert self.repo.get("auto_zoom_on_load") is True

        self.repo.set("auto_zoom_on_load", "false")
        assert self.repo.get("auto_zoom_on_load") is False

        self.repo.set("auto_zoom_on_load", "1")
        assert self.repo.get("auto_zoom_on_load") is True

    def test_int_string_coercion(self):
        """QgsSettings pode retornar int como string."""
        self.repo.set("page_size", "30")
        assert self.repo.get("page_size") == 30

    def test_int_invalid_fallback(self):
        self.repo.set("page_size", "not-a-number")
        # Deve retornar default
        assert self.repo.get("page_size") == DEFAULTS["page_size"]

    def test_get_all(self):
        result = self.repo.get_all()
        assert isinstance(result, dict)
        assert set(result.keys()) == set(DEFAULTS.keys())

    def test_restore_defaults(self):
        self.repo.set("api_base_url", "https://modified.url.com")
        self.repo.set("page_size", 99)
        self.repo.restore_defaults()
        assert self.repo.get("api_base_url") == DEFAULTS["api_base_url"]
        assert self.repo.get("page_size") == DEFAULTS["page_size"]

    def test_key_namespacing(self):
        """Chaves devem ser prefixadas com SETTINGS_NAMESPACE."""
        key = self.repo._key("api_base_url")
        assert key == f"{SETTINGS_NAMESPACE}/api_base_url"


class TestPluginVersion:
    def test_version_matches_metadata(self):
        """A versão exibida no painel é a publicada no repositório de complementos."""
        metadata = configparser.ConfigParser(interpolation=None)
        raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        with open(os.path.join(raiz, "metadata.txt"), encoding="utf-8") as arquivo:
            metadata.read_file(arquivo)
        assert PLUGIN_VERSION == metadata.get("general", "version")
