"""Envio idempotente de edições e acompanhamento separado do recálculo."""

import os
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

from qgis.PyQt.QtCore import QLockFile

from .base_task import SatIrrigaTask
from ...domain.models.enums import UploadBatchStatusEnum
from ...domain.services.gpkg_service import update_sidecar
from ...domain.services.upload_feedback import is_terminal_zonal_status
from ...domain.services.upload_package import archive_path, prepare_operation, save_operation

class UploadZonalTask(SatIrrigaTask):
    def __init__(self, upload_url, checkout_url, access_token, gpkg_source_path,
                 zonal_id, edit_token, expected_version,
                 conflict_strategy="REJECT_CONFLICTS", zonal_status_url=None):
        super().__init__(f"Upload zonal {zonal_id}")
        self._url = upload_url
        self._checkout_url = checkout_url
        self._token = access_token
        self._source_path = gpkg_source_path
        self._zonal_id = zonal_id
        self._edit_token = edit_token
        self._expected_version = expected_version
        self._conflict_strategy = conflict_strategy
        self._zonal_status_url = zonal_status_url
        self._batch_uuid = None
        self._operation = None
        self._result = {
            "uploadPersisted": False, "reprocessingStatus": "PENDING",
            "reprocessingError": None, "pendingGeoids": 0, "pending": True,
            "zonalId": zonal_id, "error": None,
        }

    @property
    def batch_uuid(self):
        return self._batch_uuid

    @property
    def result(self):
        return dict(self._result)

    def _update_sidecar(self, checkout_data):
        update_sidecar(self._source_path, lambda sidecar: sidecar.update({
            "editToken": checkout_data["editToken"],
            "expiresAt": checkout_data.get("expiresAt", sidecar.get("expiresAt")),
        }))

    def _renew_checkout(self, headers):
        self.signals.status_message.emit("Obtendo token de edição...")
        try:
            response = requests.post(self._checkout_url, headers=headers, timeout=30)
        except requests.RequestException as error:
            self._log(f"[Upload] Renovação indisponível: {error}")
            return
        if response.status_code == 200:
            data = response.json()
            self._edit_token = data["editToken"]
            self._update_sidecar(data)
        elif response.status_code == 409:
            raise ValueError("Zonal em edição por outro usuário. Aguarde a liberação para enviar.")
        else:
            response.raise_for_status()

    def _save_operation(self, **metadata):
        save_operation(self._source_path, self._operation, **metadata)

    def _poll_url(self):
        poll_url = self._operation.get("pollUrl")
        if not poll_url:
            raise ValueError("Servidor não retornou o endereço de acompanhamento do lote.")
        absolute = urljoin(self._url, poll_url)
        if urlparse(absolute)[:2] != urlparse(self._url)[:2]:
            raise ValueError("Endereço de acompanhamento fora do servidor de upload.")
        return absolute

    def _send(self, headers):
        try:
            self._renew_checkout(headers)
        except (ValueError, requests.HTTPError) as error:
            # O servidor devolve o recibo de uma operação já recebida antes de conferir o token de edição.
            if not self._operation.get("submitted"):
                raise
            self._log(f"[Upload] Renovação recusada; consultando o recibo da operação já enviada: {error}")
        if self.isCanceled():
            raise InterruptedError("Envio cancelado antes da transmissão.")
        self.signals.status_message.emit("Enviando para o servidor...")
        self._operation["submitted"] = True
        self._save_operation()
        data = {
            "protocolVersion": "2", "operationId": self._operation["operationId"],
            "baseVersion": str(self._operation["baseVersion"]),
            "expectedVersion": str(self._operation["baseVersion"]),
            "baseSnapshotHash": self._operation["baseSnapshotHash"],
            "editToken": self._edit_token,
            "conflictStrategy": self._operation["conflictStrategy"],
        }
        with open(archive_path(self._source_path, self._operation), "rb") as stream:
            response = requests.post(
                self._url, headers=headers,
                files={"file": ("upload.zip", stream, "application/zip")},
                data=data, timeout=300,
            )
        if response.status_code not in (200, 202):
            try:
                message = response.json().get("message") or response.text[:200]
            except ValueError:
                message = response.text[:200]
            self._operation["lastHttpError"] = {"status": response.status_code, "message": message}
            if response.status_code in (400, 401, 403, 404, 409, 413, 415, 422):
                self._operation["submitted"] = False
                self._result["pending"] = False
            self._save_operation()
            raise ValueError(f"Envio recusado (HTTP {response.status_code}): {message}")
        receipt = response.json()
        self._batch_uuid = receipt.get("batchUuid")
        self._operation.update({"response": receipt, "batchUuid": self._batch_uuid,
                                "pollUrl": receipt.get("pollUrl")})
        self._result["batchUuid"] = self._batch_uuid
        self._save_operation()
        if not self._batch_uuid:
            raise ValueError("Servidor não retornou a identidade do lote.")

    def _record_status(self, data):
        if data.get("batchUuid") and data["batchUuid"] != self._batch_uuid:
            raise ValueError("O status recebido pertence a outro lote.")
        if data.get("operationId") and data["operationId"] != self._operation["operationId"]:
            raise ValueError("O status recebido pertence a outra operação.")
        status = data.get("status", self._operation.get("status"))
        previous_status = self._operation.get("lastStatus")
        self._operation.update({"status": status, "lastStatus": data})
        persisted = self._result["uploadPersisted"] or status == "COMPLETED"
        self._result.update({
            "batchStatus": status, "uploadPersisted": persisted, "error": None,
            "batchUuid": self._batch_uuid,
            "pendingGeoids": data.get("pendingGeoids") or 0,
            "expectedVersion": data.get("expectedVersion", self._result.get("expectedVersion")),
        })
        if data.get("reprocessingStatus"):
            self._result["reprocessingStatus"] = data["reprocessingStatus"]
            self._result["reprocessingError"] = data.get("reprocessingError")
        if data != previous_status:
            metadata = {"needsRedownload": True, "uploadedAt": datetime.now(timezone.utc).isoformat()} if persisted else {}
            self._save_operation(**metadata)

    def _emit_result(self, phase, message):
        self._result["phase"] = phase
        self._result["message"] = message
        self.signals.status_message.emit(message)
        self.signals.upload_progress.emit(self.result)

    def _pending(self, error=None):
        self._result.update({"pending": True, "error": str(error) if error else None})
        if self._result["uploadPersisted"]:
            self._emit_result("reprocessing_timeout", "Envio persistido; recálculo ainda pendente no servidor")
            return True
        self._emit_result("upload_pending", "Envio pendente de confirmação; retome o acompanhamento do lote")
        self._exception = error or TimeoutError(self._result["message"])
        return False

    def _finish_reprocessing(self, data):
        status = self._result["reprocessingStatus"]
        self._result.update({"pending": False, "lastError": self._result["reprocessingError"]})
        if status == "FAILED":
            self._result["zonalStatus"] = data.get("zonalStatus") or "FAILED"
            message = "Envio persistido; recálculo com falha"
        elif status == "NOT_REQUIRED":
            self._result["zonalStatus"] = "NOT_REQUIRED"
            message = "Envio persistido; recálculo não necessário"
        else:
            self._result["zonalStatus"] = data.get("zonalStatus") or "DONE"
            message = "Envio persistido; recálculo concluído"
        self.setProgress(100)
        self._emit_result("reprocessing_done", message)
        return True

    def _wait_reprocessing(self, headers, initial):
        if not initial.get("reprocessingStatus"):
            legacy = self._poll_reprocessing(headers) if self._zonal_status_url else None
            if legacy is None:
                self._result["reprocessingStatus"] = "PROCESSING"
                return self._pending()
            legacy_status = legacy.get("status")
            self._result.update({
                "reprocessingStatus": "DONE" if legacy_status in ("DONE", "CONSOLIDATED", "AGUARDANDO") else "FAILED",
                "reprocessingError": legacy.get("lastError"), "pendingGeoids": legacy.get("pendingGeoids") or 0,
            })
            return self._finish_reprocessing({"zonalStatus": legacy_status})
        data = initial
        for _ in range(600):
            if self._result["reprocessingStatus"] in ("DONE", "FAILED", "NOT_REQUIRED"):
                return self._finish_reprocessing(data)
            if self.isCanceled():
                return self._pending()
            self._result["zonalStatus"] = data.get("zonalStatus") or "PROCESSING"
            self._emit_result("reprocessing", "Envio persistido; recalculando overlay e estatísticas zonais...")
            time.sleep(3)
            try:
                response = requests.get(self._poll_url(), headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()
                self._record_status(data)
            except (requests.RequestException, ValueError) as error:
                self._result["error"] = str(error)
        if self._result["reprocessingStatus"] in ("DONE", "FAILED", "NOT_REQUIRED"):
            return self._finish_reprocessing(data)
        return self._pending(self._result["error"])

    def run(self):
        lock = QLockFile(os.path.join(os.path.dirname(os.path.realpath(self._source_path)), ".satirriga-upload.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            self._exception = ValueError("Já existe uma operação em andamento para este GeoPackage.")
            return False
        try:
            self.signals.status_message.emit("Preparando envio...")
            self._operation = prepare_operation(
                self._source_path, self._url, self._expected_version,
                self._conflict_strategy, self.isCanceled,
            )
            self._batch_uuid = self._operation.get("batchUuid")
            self._result.update({"operationId": self._operation["operationId"], "batchUuid": self._batch_uuid,
                                 "baseVersion": self._operation["baseVersion"]})
            if self._operation.get("status") == "COMPLETED":
                self._result["uploadPersisted"] = True
            headers = {"Authorization": f"Bearer {self._token}"}
            if not self._batch_uuid:
                self._send(headers)
            self.setProgress(50)
            for _ in range(150):
                if self.isCanceled():
                    return self._pending()
                response = requests.get(self._poll_url(), headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()
                self._record_status(data)
                status = data.get("status")
                self.signals.upload_progress.emit({**data, **self.result})
                if status == "COMPLETED":
                    return self._wait_reprocessing(headers, data)
                if status in ("FAILED", "CANCELLED"):
                    self._result["pending"] = False
                    raise ValueError(f"Envio não persistido: {data.get('errorLog') or status}")
                if status == "CONFLICT_CHECKING" and data.get("conflictCount", 0) > 0:
                    self.signals.conflict_detected.emit(self._batch_uuid)
                try:
                    self.signals.status_message.emit(UploadBatchStatusEnum(status).label)
                except ValueError:
                    self.signals.status_message.emit(str(status or "Aguardando confirmação"))
                self.setProgress(min(95, 50 + int((data.get("progressPct") or 0) * 0.45)))
                time.sleep(2)
            return self._pending()
        except requests.RequestException as error:
            return self._pending(error)
        except Exception as error:
            self._exception = error
            self._result["error"] = str(error)
            return False
        finally:
            lock.unlock()

    def finished(self, result):
        message = self._result.get("message") if result else str(self._exception or "Envio interrompido")
        self.signals.completed.emit(bool(result), message or "Envio persistido; aguardando recálculo")

    def _poll_reprocessing(self, headers):
        """Monitora reprocessamento pos-upload (overlay + zonal stats).

        Faz polling de GET /api/zonal/:id/status ate zonal.status sair dos
        estados intermediarios e devolve o ultimo status recebido (com
        ``lastError`` e ``pendingGeoids``). Devolve None se o limite de 30
        minutos expirar; o servidor continua o recalculo, que pode envolver
        varios ciclos de overlay quando ha muitas feicoes novas ou editadas
        na mesma regiao.
        """
        self.signals.status_message.emit(
            "Recalculando overlay e estatísticas zonais..."
        )
        self.signals.upload_progress.emit({
            "phase": "reprocessing",
            "zonalId": self._zonal_id,
            "zonalStatus": "PROCESSING",
        })
        self.setProgress(96)

        max_polls = 600  # 600 * 3s = 30 min
        poll_count = 0
        last_zonal_status = ""

        while poll_count < max_polls:
            if self.isCanceled():
                return None

            time.sleep(3)
            poll_count += 1

            try:
                resp = requests.get(
                    self._zonal_status_url, headers=headers, timeout=30,
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                zonal_status = data.get("status")

                if not zonal_status:
                    continue

                if zonal_status != last_zonal_status:
                    self._log(
                        f"[Reprocessamento] zonal.status={zonal_status} "
                        f"version={data.get('version')} "
                        f"ciclos={data.get('overlayRetryCount', 0)} "
                        f"pendentes={data.get('pendingGeoids', 0)}"
                    )
                    last_zonal_status = zonal_status

                self.signals.upload_progress.emit({
                    "phase": "reprocessing",
                    "zonalId": self._zonal_id,
                    "zonalStatus": zonal_status,
                    "overlayRetryCount": data.get("overlayRetryCount", 0),
                    "pendingGeoids": data.get("pendingGeoids", 0),
                })

                if is_terminal_zonal_status(zonal_status):
                    self._log(
                        f"[Reprocessamento] Estado terminal: "
                        f"zonal.status={zonal_status} "
                        f"lastError={data.get('lastError')}"
                    )
                    self.setProgress(99)
                    return data

            except (requests.RequestException, ValueError):
                continue

        self._log(
            "[Reprocessamento] Timeout 30min: upload ja esta COMPLETED, "
            "reprocessamento continua no servidor"
        )
        return None
