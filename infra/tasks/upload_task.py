"""Task para upload de edicoes zonais (export + POST + polling)."""

import os
import shutil
import tempfile
import time
import zipfile

import requests

from qgis.core import (
    QgsVectorLayer, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsFields, QgsField, QgsFeature, Qgis,
)
from qgis.PyQt.QtCore import QVariant

from .base_task import SatIrrigaTask
from ...domain.models.enums import UploadBatchStatusEnum


class UploadZonalTask(SatIrrigaTask):
    """Exporta todas as features, envia via POST multipart, faz polling."""

    def __init__(self, upload_url, access_token, gpkg_source_path,
                 zonal_id, edit_token, expected_version,
                 conflict_strategy="REJECT_CONFLICTS"):
        super().__init__(f"Upload zonal {zonal_id}")
        self._url = upload_url
        self._token = access_token
        self._source_path = gpkg_source_path
        self._zonal_id = zonal_id
        self._edit_token = edit_token
        self._expected_version = expected_version
        self._conflict_strategy = conflict_strategy
        self._batch_uuid = None

    @property
    def batch_uuid(self):
        return self._batch_uuid

    def run(self):
        temp_dir = None
        try:
            self.signals.status_message.emit("Preparando upload...")
            self.setProgress(5)

            # ----------------------------------------------------------
            # 1. Export GPKG (0-25%)
            # ----------------------------------------------------------
            src_layer = QgsVectorLayer(self._source_path, "upload_src", "ogr")
            if not src_layer.isValid():
                self._exception = Exception(f"GPKG invalido: {self._source_path}")
                return False

            temp_dir = tempfile.mkdtemp(prefix="satirriga_upload_")
            temp_gpkg = os.path.join(temp_dir, "upload.gpkg")

            # Remove campos internos do export (_edit_token, _sync_timestamp, _zonal_id)
            # Preserva _original_fid e _sync_status (servidor usa para classificar)
            internal_fields = {"_edit_token", "_sync_timestamp", "_zonal_id",
                               "_mapeamento_id", "_metodo_id"}
            clean_fields = QgsFields()
            field_mapping = []
            for field in src_layer.fields():
                if field.name() not in internal_fields:
                    clean_fields.append(field)
                    field_mapping.append(src_layer.fields().indexOf(field.name()))

            crs = src_layer.crs()
            if not crs.isValid():
                crs = QgsCoordinateReferenceSystem("EPSG:4326")

            writer = QgsVectorFileWriter(
                temp_gpkg, "utf-8", clean_fields,
                src_layer.wkbType(), crs, "GPKG",
            )

            if writer.hasError() != QgsVectorFileWriter.NoError:
                self._exception = Exception(
                    f"Erro ao criar GPKG temp: {writer.errorMessage()}"
                )
                return False

            total_features = src_layer.featureCount()
            for i, feat in enumerate(src_layer.getFeatures()):
                if self.isCanceled():
                    del writer
                    return False
                clean_feat = QgsFeature(clean_fields)
                clean_feat.setGeometry(feat.geometry())
                for new_idx, old_idx in enumerate(field_mapping):
                    clean_feat.setAttribute(new_idx, feat.attribute(old_idx))
                writer.addFeature(clean_feat)
                if total_features > 0:
                    self.setProgress(int((i + 1) * 25 / total_features))

            del writer
            self.setProgress(25)

            if self.isCanceled():
                return False

            # ----------------------------------------------------------
            # 2. ZIP (25-30%)
            # ----------------------------------------------------------
            self.signals.status_message.emit("Compactando...")
            temp_zip = os.path.join(temp_dir, "upload.zip")
            with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(temp_gpkg, "upload.gpkg")
            self.setProgress(30)

            if self.isCanceled():
                return False

            # ----------------------------------------------------------
            # 3. POST multipart (30-50%)
            # ----------------------------------------------------------
            self.signals.status_message.emit("Enviando para servidor...")
            headers = {"Authorization": f"Bearer {self._token}"}

            with open(temp_zip, "rb") as f:
                files = {"file": ("upload.zip", f, "application/zip")}
                data = {
                    "editToken": self._edit_token,
                    "expectedVersion": str(self._expected_version),
                    "conflictStrategy": self._conflict_strategy,
                }
                response = requests.post(
                    self._url, headers=headers,
                    files=files, data=data, timeout=300,
                )

            if response.status_code == 403:
                self._exception = Exception(
                    "Token de edicao invalido ou expirado. "
                    "Faca novo download do zonal."
                )
                return False
            elif response.status_code == 409:
                self._exception = Exception(
                    "Upload concorrente detectado. Tente novamente."
                )
                return False
            elif response.status_code != 202:
                self._exception = Exception(
                    f"Servidor retornou HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )
                return False

            resp_data = response.json()
            self._batch_uuid = resp_data.get("batchUuid", "")
            poll_url = resp_data.get("pollUrl", "")

            if not poll_url:
                self._exception = Exception("Servidor nao retornou pollUrl")
                return False

            self.setProgress(50)

            # ----------------------------------------------------------
            # 4. Polling (50-95%)
            # ----------------------------------------------------------
            self.signals.status_message.emit("Processando no servidor...")

            while True:
                if self.isCanceled():
                    return False

                time.sleep(2)

                poll_resp = requests.get(
                    poll_url, headers=headers, timeout=30,
                )
                poll_resp.raise_for_status()
                status_data = poll_resp.json()

                # Emite progresso para UI
                self.signals.upload_progress.emit(status_data)

                batch_status = status_data.get("status", "")
                progress_pct = status_data.get("progressPct", 0)
                conflict_count = status_data.get("conflictCount", 0)

                # Atualiza progresso: 50 + progressPct * 0.45
                self.setProgress(50 + int(progress_pct * 0.45))

                try:
                    status_enum = UploadBatchStatusEnum(batch_status)
                    self.signals.status_message.emit(status_enum.label)
                except ValueError:
                    self.signals.status_message.emit(batch_status)

                # Conflitos detectados
                if batch_status == "CONFLICT_CHECKING" and conflict_count > 0:
                    self.signals.conflict_detected.emit(self._batch_uuid)

                # Status terminal
                try:
                    status_enum = UploadBatchStatusEnum(batch_status)
                    if status_enum.is_terminal:
                        break
                except ValueError:
                    pass

            # ----------------------------------------------------------
            # 5. Resultado (95-100%)
            # ----------------------------------------------------------
            self.setProgress(95)

            if batch_status == UploadBatchStatusEnum.COMPLETED.value:
                self.setProgress(100)
                self.signals.status_message.emit("Upload concluido!")
                self._log(f"Upload zonal {self._zonal_id} concluido: batch {self._batch_uuid}")
                return True
            elif batch_status == UploadBatchStatusEnum.FAILED.value:
                error_log = status_data.get("errorLog", "Erro desconhecido")
                self._exception = Exception(f"Upload falhou: {error_log}")
                return False
            elif batch_status == UploadBatchStatusEnum.CANCELLED.value:
                self._exception = Exception("Upload cancelado pelo servidor")
                return False
            else:
                self._exception = Exception(f"Status inesperado: {batch_status}")
                return False

        except requests.RequestException as e:
            self._exception = Exception(f"Erro de upload: {e}")
            return False
        except Exception as e:
            self._exception = e
            return False
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass
