"""Testes unitarios para AppState — testa contrato de signals e estado.

Nota: Como AppState depende de PyQt5 (QObject + pyqtSignal), e os testes
rodam sem QGIS instalado, testamos somente a logica de estado com mock.
"""

import pytest


class MockSignal:
    """Simula pyqtSignal com tracking de emit calls."""

    def __init__(self, *args):
        self._emits = []

    def emit(self, *args):
        self._emits.append(args)

    def connect(self, slot):
        pass

    def disconnect(self, slot=None):
        pass

    @property
    def call_count(self):
        return len(self._emits)

    @property
    def last_args(self):
        return self._emits[-1] if self._emits else None


class FakeAppState:
    """Reimplementa AppState sem dependencia Qt para testes.

    Replica exatamente a logica de store.py.
    """

    def __init__(self):
        self.auth_state_changed = MockSignal(bool)
        self.user_changed = MockSignal(object)
        self.session_countdown = MockSignal(int)
        self.catalogo_changed = MockSignal(list)
        self.upload_progress_changed = MockSignal(dict)
        self.conflict_detected = MockSignal(str)
        self.upload_batch_completed = MockSignal(str, dict)
        self.loading_changed = MockSignal(str, bool)
        self.error_occurred = MockSignal(str, str)

        self._authenticated = False
        self._user = None
        self._catalogo_items = []

    @property
    def is_authenticated(self):
        return self._authenticated

    @is_authenticated.setter
    def is_authenticated(self, value):
        if self._authenticated != value:
            self._authenticated = value
            self.auth_state_changed.emit(value)

    @property
    def user(self):
        return self._user

    @user.setter
    def user(self, value):
        self._user = value
        self.user_changed.emit(value)

    @property
    def catalogo_items(self):
        return self._catalogo_items

    @catalogo_items.setter
    def catalogo_items(self, value):
        self._catalogo_items = value
        self.catalogo_changed.emit(value)

    def set_loading(self, operation, is_loading):
        self.loading_changed.emit(operation, is_loading)

    def set_error(self, operation, message):
        self.error_occurred.emit(operation, message)

    def reset(self):
        self.is_authenticated = False
        self.user = None
        self._catalogo_items = []


class TestAppState:
    def setup_method(self):
        self.state = FakeAppState()

    def test_initial_state(self):
        assert self.state.is_authenticated is False
        assert self.state.user is None
        assert self.state.catalogo_items == []

    def test_set_authenticated_emits_signal(self):
        self.state.is_authenticated = True
        assert self.state.is_authenticated is True
        assert self.state.auth_state_changed.call_count == 1
        assert self.state.auth_state_changed.last_args == (True,)

    def test_set_authenticated_no_emit_on_same_value(self):
        # Valor inicial e False, setar False nao deve emitir
        self.state.is_authenticated = False
        assert self.state.auth_state_changed.call_count == 0

    def test_toggle_authenticated(self):
        self.state.is_authenticated = True
        self.state.is_authenticated = False
        assert self.state.auth_state_changed.call_count == 2
        assert self.state.auth_state_changed.last_args == (False,)

    def test_set_user_emits_signal(self):
        class FakeUser:
            name = "Test User"

        user = FakeUser()
        self.state.user = user
        assert self.state.user == user
        assert self.state.user_changed.call_count == 1
        assert self.state.user_changed.last_args == (user,)

    def test_set_user_none_emits_signal(self):
        self.state.user = None
        assert self.state.user_changed.call_count == 1
        assert self.state.user_changed.last_args == (None,)

    def test_set_loading(self):
        self.state.set_loading("download", True)
        assert self.state.loading_changed.call_count == 1
        assert self.state.loading_changed.last_args == ("download", True)

    def test_set_error(self):
        self.state.set_error("auth", "Token expirado")
        assert self.state.error_occurred.call_count == 1
        assert self.state.error_occurred.last_args == ("auth", "Token expirado")

    def test_reset_clears_all_state(self):
        self.state.is_authenticated = True
        self.state.user = {"name": "Test"}
        self.state.catalogo_items = [{"id": 42}]

        self.state.reset()

        assert self.state.is_authenticated is False
        assert self.state.user is None
        assert self.state._catalogo_items == []

    def test_reset_emits_auth_changed(self):
        self.state.is_authenticated = True
        emit_count_before = self.state.auth_state_changed.call_count
        self.state.reset()
        assert self.state.auth_state_changed.call_count > emit_count_before


class TestCatalogoState:
    def setup_method(self):
        self.state = FakeAppState()

    def test_set_catalogo_items_emits_signal(self):
        items = [{"id": 1}, {"id": 2}]
        self.state.catalogo_items = items
        assert self.state.catalogo_items == items
        assert self.state.catalogo_changed.call_count == 1
        assert self.state.catalogo_changed.last_args == (items,)

    def test_set_empty_catalogo(self):
        self.state.catalogo_items = []
        assert self.state.catalogo_items == []
        assert self.state.catalogo_changed.call_count == 1

    def test_catalogo_reset_on_full_reset(self):
        self.state.catalogo_items = [{"id": 99}]
        self.state.reset()
        assert self.state._catalogo_items == []

    def test_v2_signals_exist(self):
        """Verifica que os signals V2 existem no state."""
        assert hasattr(self.state, "catalogo_changed")
        assert hasattr(self.state, "upload_progress_changed")
        assert hasattr(self.state, "conflict_detected")
        assert hasattr(self.state, "upload_batch_completed")
