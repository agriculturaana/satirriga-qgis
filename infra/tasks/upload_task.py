"""Task para upload de edicoes zonais (export + POST + polling).

Usa osgeo.ogr para export GPKG em worker thread,
evitando criar QgsVectorLayer fora da main thread.
"""

import os
import shutil
import tempfile
import time
import zipfile

from urllib.parse import urlparse

import requests

from qgis.core import Qgis

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
            # 1. Export GPKG via GDAL/OGR (0-25%)
            # ----------------------------------------------------------
            from osgeo import ogr, gdal
            gdal.UseExceptions()

            src_ds = ogr.Open(self._source_path, 0)
            if src_ds is None:
                self._exception = Exception(f"GPKG invalido: {self._source_path}")
                return False

            src_lyr = src_ds.GetLayer(0)
            if src_lyr is None:
                src_ds = None
                self._exception = Exception(f"GPKG sem layers: {self._source_path}")
                return False

            temp_dir = tempfile.mkdtemp(prefix="satirriga_upload_")
            temp_gpkg = os.path.join(temp_dir, "upload.gpkg")

            # Remove campos internos do export (_edit_token, _sync_timestamp, _zonal_id)
            # Preserva _original_fid e _sync_status (servidor usa para classificar)
            internal_fields = {"_edit_token", "_sync_timestamp", "_zonal_id",
                               "_mapeamento_id", "_metodo_id"}

            src_defn = src_lyr.GetLayerDefn()
            field_mapping = []  # (src_idx, field_defn) para campos a copiar
            for i in range(src_defn.GetFieldCount()):
                fd = src_defn.GetFieldDefn(i)
                if fd.GetName() not in internal_fields:
                    field_mapping.append((i, fd))

            src_srs = src_lyr.GetSpatialRef()
            if src_srs is None:
                from osgeo import osr
                src_srs = osr.SpatialReference()
                src_srs.ImportFromEPSG(4326)

            gpkg_drv = ogr.GetDriverByName("GPKG")
            dst_ds = gpkg_drv.CreateDataSource(temp_gpkg)
            if dst_ds is None:
                src_ds = None
                self._exception = Exception(f"Erro ao criar GPKG temp: {temp_gpkg}")
                return False

            dst_lyr = dst_ds.CreateLayer(
                "upload", srs=src_srs, geom_type=src_lyr.GetGeomType(),
                options=["FID=fid"],
            )
            for _, fd in field_mapping:
                dst_lyr.CreateField(fd)

            dst_defn = dst_lyr.GetLayerDefn()
            total_features = src_lyr.GetFeatureCount()
            dst_lyr.StartTransaction()

            for i, src_feat in enumerate(src_lyr):
                if self.isCanceled():
                    dst_lyr.RollbackTransaction()
                    src_ds = None
                    dst_ds = None
                    return False
                dst_feat = ogr.Feature(dst_defn)
                geom = src_feat.GetGeometryRef()
                if geom is not None:
                    dst_feat.SetGeometry(geom.Clone())
                for new_idx, (old_idx, _) in enumerate(field_mapping):
                    dst_feat.SetField(new_idx, src_feat.GetField(old_idx))
                dst_lyr.CreateFeature(dst_feat)
                if total_features > 0:
                    self.setProgress(int((i + 1) * 25 / total_features))

            dst_lyr.CommitTransaction()
            src_ds = None
            dst_ds = None
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

            self._log(f"[HTTP] POST {self._url} (auth=True, multipart)")
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
            self._log(f"[HTTP] {response.status_code} {self._url}")

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

            # pollUrl pode ser relativo ("/api/..."), precisa de URL absoluta
            if poll_url.startswith("/"):
                parsed = urlparse(self._url)
                poll_url = f"{parsed.scheme}://{parsed.netloc}{poll_url}"

            self.setProgress(50)

            # ----------------------------------------------------------
            # 4. Polling (50-95%)
            # ----------------------------------------------------------
            self.signals.status_message.emit("Processando no servidor...")

            max_polls = 150  # 150 * 2s = 5 min timeout
            poll_count = 0
            last_status = ""

            while poll_count < max_polls:
                if self.isCanceled():
                    return False

                time.sleep(2)
                poll_count += 1

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

                # Log apenas quando status muda
                if batch_status != last_status:
                    self._log(f"[HTTP] {poll_resp.status_code} {poll_url}")
                    last_status = batch_status

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
            else:
                self._exception = Exception(
                    f"Timeout: servidor nao concluiu em 5 minutos "
                    f"(ultimo status: {batch_status})"
                )
                return False

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
