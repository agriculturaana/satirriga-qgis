"""Testes unitarios para BasesService."""

import json
import sys
from unittest.mock import MagicMock


class MockQObject:
    def __init__(self, *args, **kwargs):
        pass


class MockSignal:
    def __init__(self, *args):
        self._callbacks = []
        self.emit = MagicMock()

    def connect(self, slot):
        self._callbacks.append(slot)

    def disconnect(self, slot=None):
        if slot is None:
            self._callbacks.clear()
            return
        if slot in self._callbacks:
            self._callbacks.remove(slot)


qgis_mocks = {
    "qgis": MagicMock(),
    "qgis.PyQt": MagicMock(),
    "qgis.PyQt.QtCore": MagicMock(),
}
qgis_mocks["qgis.PyQt.QtCore"].QObject = MockQObject
qgis_mocks["qgis.PyQt.QtCore"].pyqtSignal = MockSignal
for mod, mock in qgis_mocks.items():
    sys.modules[mod] = mock

from infra.services.bases_service import BasesService  # noqa: E402


class FakeHttpClient:
    def __init__(self):
        self.request_finished = MockSignal()
        self.request_error = MockSignal()
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return f"request-{len(self.urls)}"


class FakeConfigRepo:
    def get(self, key):
        assert key == "api_base_url"
        return "https://satirriga.example/api/"


def _service():
    BasesService.layer_loaded.emit.reset_mock()
    BasesService.layer_failed.emit.reset_mock()
    return BasesService(FakeHttpClient(), FakeConfigRepo())


def test_fetch_builds_bases_url_and_tracks_request():
    service = _service()

    request_id = service.fetch("municipios", (1.1, 2.2, 3.3, 4.4))

    assert request_id == "request-1"
    assert service._http_client.urls == [
        "https://satirriga.example/api/bases/municipios?bbox=1.1,2.2,3.3,4.4"
    ]
    assert service._pending == {"request-1": "municipios"}


def test_finished_emits_loaded_feature_collection():
    service = _service()
    request_id = service.fetch("bacias", (-1, -2, 1, 2))
    payload = {"type": "FeatureCollection", "features": []}

    service._on_finished(request_id, 200, json.dumps(payload).encode("utf-8"))

    BasesService.layer_loaded.emit.assert_called_once_with("bacias", payload)
    BasesService.layer_failed.emit.assert_not_called()
    assert service._pending == {}


def test_finished_emits_failed_for_invalid_json():
    service = _service()
    request_id = service.fetch("empreendimentos", (-1, -2, 1, 2))

    service._on_finished(request_id, 200, b"{")

    BasesService.layer_failed.emit.assert_called_once()
    layer_id, message = BasesService.layer_failed.emit.call_args.args
    assert layer_id == "empreendimentos"
    assert "Resposta invalida" in message


def test_error_413_emits_zoom_friendly_message():
    service = _service()
    request_id = service.fetch("empreendimentos", (-10, -10, 10, 10))

    service._on_error(request_id, "Erro HTTP 413")

    BasesService.layer_failed.emit.assert_called_once()
    layer_id, message = BasesService.layer_failed.emit.call_args.args
    assert layer_id == "empreendimentos"
    assert "Aproxime o zoom" in message
    assert service._pending == {}


def test_cleanup_disconnects_http_signals_and_clears_pending():
    service = _service()
    service.fetch("municipios", (1, 2, 3, 4))

    service.cleanup()

    assert service._http_client.request_finished._callbacks == []
    assert service._http_client.request_error._callbacks == []
    assert service._pending == {}
