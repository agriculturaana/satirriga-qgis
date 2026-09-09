"""Monitoramento pós-upload da UploadZonalTask: status final com motivo e expiração."""

import importlib
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest


class _FakeSignal:
    def __init__(self, *args):
        self.emit = MagicMock()

    def connect(self, slot):
        pass


class _FakeQgsTask:
    CanCancel = 1

    def __init__(self, *args, **kwargs):
        pass

    def setProgress(self, value):
        pass

    def isCanceled(self):
        return False


@pytest.fixture(scope="module")
def upload_task_module():
    """Importa infra.tasks.upload_task como parte do pacote do plugin, com QGIS simulado."""
    fake_core = MagicMock()
    fake_core.QgsTask = _FakeQgsTask
    fake_qtcore = MagicMock()
    fake_qtcore.QObject = type("QObject", (), {"__init__": lambda self, *a, **k: None})
    fake_qtcore.pyqtSignal = _FakeSignal
    mocks = {
        "qgis": MagicMock(), "qgis.core": fake_core,
        "qgis.PyQt": MagicMock(), "qgis.PyQt.QtCore": fake_qtcore,
    }
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    tmp = tempfile.mkdtemp()
    os.symlink(root, os.path.join(tmp, "satirriga_qgis"))
    with patch.dict(sys.modules, mocks):
        sys.path.insert(0, tmp)
        try:
            yield importlib.import_module("satirriga_qgis.infra.tasks.upload_task")
        finally:
            sys.path.remove(tmp)


def _task(module):
    return module.UploadZonalTask(
        upload_url="http://sat/api/zonal/1/upload", checkout_url="http://sat/api/zonal/1/checkout",
        access_token="t", gpkg_source_path="/tmp/x.gpkg", zonal_id=1, edit_token="e",
        expected_version=1, zonal_status_url="http://sat/api/zonal/1/status",
    )


def _response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


def test_devolve_status_final_com_motivo(upload_task_module):
    task = _task(upload_task_module)
    sequence = [
        _response({"status": "PROCESSING", "overlayRetryCount": 0, "pendingGeoids": 3}),
        _response({"status": "PROCESSING", "overlayRetryCount": 1, "pendingGeoids": 2}),
        _response({"status": "OVERLAY_FAILED", "lastError": "2 feição(ões) sem geoid após 25 ciclos", "pendingGeoids": 2}),
    ]
    with patch.object(upload_task_module.requests, "get", side_effect=sequence), \
         patch.object(upload_task_module.time, "sleep"):
        final = task._poll_reprocessing({})

    assert final["status"] == "OVERLAY_FAILED"
    assert "25 ciclos" in final["lastError"]
    fases = [c.args[0] for c in task.signals.upload_progress.emit.call_args_list]
    assert fases[0]["phase"] == "reprocessing"
    assert fases[-1]["overlayRetryCount"] == 0 or fases[-1]["zonalStatus"] == "OVERLAY_FAILED"
    assert any(f.get("overlayRetryCount") == 1 and f.get("pendingGeoids") == 2 for f in fases)


def test_expira_apos_trinta_minutos_sem_status_terminal(upload_task_module):
    task = _task(upload_task_module)
    with patch.object(upload_task_module.requests, "get",
                      return_value=_response({"status": "PROCESSING"})) as get, \
         patch.object(upload_task_module.time, "sleep"):
        final = task._poll_reprocessing({})

    assert final is None
    assert get.call_count == 600
