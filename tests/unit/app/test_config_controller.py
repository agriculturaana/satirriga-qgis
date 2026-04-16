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


class MockSignal:
    """Simula pyqtSignal com tracking de emit calls."""

    def __init__(self):
        self._emits = []

    def emit(self, *args):
        self._emits.append(args)

    @property
    def call_count(self):
        return len(self._emits)

    @property
    def last_args(self):
        return self._emits[-1] if self._emits else None


class FakeAppState:
    def __init__(self):
        self.config_changed = MockSignal()


def _save_config(repo, values, state=None):
    """Replica logica do ConfigController.save()."""
    changed_keys = set()
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        if repo.get(key) != value:
            changed_keys.add(key)
        repo.set(key, value)
    if changed_keys and state is not None:
        state.config_changed.emit(changed_keys)


def _restore_defaults(repo, state=None):
    """Replica logica do ConfigController.restore_defaults()."""
    previous = repo.get_all()
    repo.restore_defaults()
    if state is None:
        return
    current = repo.get_all()
    changed_keys = {k for k, v in current.items() if previous.get(k) != v}
    if changed_keys:
        state.config_changed.emit(changed_keys)


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


class TestConfigChangedSignal:
    """Garante que save/restore_defaults notificam AppState.config_changed."""

    def setup_method(self):
        self.repo = FakeConfigRepository()
        self.state = FakeAppState()

    def test_save_emits_only_changed_keys(self):
        _save_config(
            self.repo,
            {
                "api_base_url": "https://nova-api.example.com",
                "page_size": DEFAULTS["page_size"],  # inalterado
            },
            state=self.state,
        )
        assert self.state.config_changed.call_count == 1
        (changed,) = self.state.config_changed.last_args
        assert changed == {"api_base_url"}

    def test_save_no_changes_does_not_emit(self):
        _save_config(
            self.repo,
            {"api_base_url": DEFAULTS["api_base_url"]},
            state=self.state,
        )
        assert self.state.config_changed.call_count == 0

    def test_save_invalid_keys_do_not_emit(self):
        _save_config(
            self.repo,
            {"nonexistent_key": "foo"},
            state=self.state,
        )
        assert self.state.config_changed.call_count == 0

    def test_save_without_state_does_not_raise(self):
        _save_config(
            self.repo,
            {"api_base_url": "https://nova-api.example.com"},
            state=None,
        )
        assert self.repo.get("api_base_url") == "https://nova-api.example.com"

    def test_restore_defaults_emits_changed_keys(self):
        self.repo.set("api_base_url", "https://modificada.example.com")
        self.repo.set("page_size", 99)

        _restore_defaults(self.repo, state=self.state)

        assert self.state.config_changed.call_count == 1
        (changed,) = self.state.config_changed.last_args
        assert "api_base_url" in changed
        assert "page_size" in changed

    def test_restore_defaults_without_changes_does_not_emit(self):
        _restore_defaults(self.repo, state=self.state)
        assert self.state.config_changed.call_count == 0
