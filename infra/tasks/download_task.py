"""Task para download de zonal (checkout + FlatGeobuf -> GPKG)."""

import os
import tempfile
from datetime import datetime, timezone

import requests

from qgis.core import (
    QgsVectorLayer, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsField, QgsFields, QgsFeature, Qgis,
)
from qgis.PyQt.QtCore import QVariant

from .base_task import SatIrrigaTask
from ...domain.models.enums import SyncStatusEnum
from ...domain.services.gpkg_service import SYNC_FIELDS_V2, write_sidecar, read_sidecar


class DownloadZonalTask(SatIrrigaTask):
    """Checkout + download FlatGeobuf + conversao para GPKG com campos V2."""

    def __init__(self, checkout_url, download_url, access_token,
                 gpkg_output_path, zonal_id):
        super().__init__(f"Download zonal {zonal_id}")
        self._checkout_url = checkout_url
        self._download_url = download_url
        self._token = access_token
        self._gpkg_path = gpkg_output_path
        self._zonal_id = zonal_id

    def run(self):
        """Executa em worker thread: checkout -> download FGB -> GPKG."""
        temp_fgb = None
        try:
            headers = {"Authorization": f"Bearer {self._token}"}

            # ----------------------------------------------------------
            # 1. Checkout (5-15%)
            # ----------------------------------------------------------
            self.signals.status_message.emit("Realizando checkout...")
            self.setProgress(5)

            checkout_resp = requests.post(
                self._checkout_url, headers=headers, timeout=30,
            )
            if checkout_resp.status_code == 409:
                self._exception = Exception(
                    "Zonal em edicao por outro usuario"
                )
                return False
            checkout_resp.raise_for_status()

            checkout_data = checkout_resp.json()
            edit_token = checkout_data["editToken"]
            zonal_version = checkout_data["zonalVersion"]
            feature_count = checkout_data.get("featureCount", 0)
            snapshot_hash = checkout_data.get("snapshotHash", "")
            expires_at = checkout_data.get("expiresAt", "")

            self.setProgress(15)

            if self.isCanceled():
                return False

            # ----------------------------------------------------------
            # 2. Download FlatGeobuf (15-55%)
            # ----------------------------------------------------------
            self.signals.status_message.emit("Baixando dados geoespaciais...")

            dl_headers = {
                **headers,
                "Accept": "application/flatgeobuf",
            }

            # ETag para cache condicional
            existing_sidecar = read_sidecar(self._gpkg_path)
            existing_etag = existing_sidecar.get("etag")
            if existing_etag:
                dl_headers["If-None-Match"] = existing_etag

            dl_resp = requests.get(
                self._download_url, headers=dl_headers,
                stream=True, timeout=120,
            )

            # 304 Not Modified — apenas atualiza sidecar com novo checkout
            if dl_resp.status_code == 304:
                self.signals.status_message.emit("Dados em cache, atualizando checkout...")
                sidecar_data = existing_sidecar.copy()
                sidecar_data.update({
                    "editToken": edit_token,
                    "zonalVersion": zonal_version,
                    "snapshotHash": snapshot_hash,
                    "expiresAt": expires_at,
                    "downloadedAt": datetime.now(timezone.utc).isoformat(),
                })
                write_sidecar(self._gpkg_path, sidecar_data)
                self.setProgress(100)
                self.signals.status_message.emit("Download concluido (cache)!")
                return True

            dl_resp.raise_for_status()

            # Stream download FGB para temp
            temp_fd, temp_fgb = tempfile.mkstemp(
                suffix=".fgb", prefix="satirriga_"
            )
            total = int(dl_resp.headers.get("content-length", 0))
            downloaded = 0

            with os.fdopen(temp_fd, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=8192):
                    if self.isCanceled():
                        return False
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        self.setProgress(15 + int(downloaded * 40 / total))

            response_etag = dl_resp.headers.get("ETag", "")
            self.setProgress(55)

            if self.isCanceled():
                return False

            # ----------------------------------------------------------
            # 3. Conversao FGB -> GPKG (55-90%)
            # ----------------------------------------------------------
            self.signals.status_message.emit("Convertendo para GeoPackage...")

            src_layer = QgsVectorLayer(temp_fgb, "fgb_src", "ogr")
            if not src_layer.isValid():
                self._exception = Exception(
                    f"Falha ao abrir FlatGeobuf: {temp_fgb}"
                )
                return False

            os.makedirs(os.path.dirname(self._gpkg_path), exist_ok=True)

            # Build fields: originais + sync V2
            fields = QgsFields()
            for field in src_layer.fields():
                fields.append(field)

            sync_type_map = {
                "INTEGER": QVariant.Int,
                "TEXT": QVariant.String,
            }
            for fname, ftype in SYNC_FIELDS_V2:
                fields.append(QgsField(fname, sync_type_map.get(ftype, QVariant.String)))

            crs = src_layer.crs()
            if not crs.isValid():
                crs = QgsCoordinateReferenceSystem("EPSG:4326")

            writer = QgsVectorFileWriter(
                self._gpkg_path,
                "utf-8",
                fields,
                src_layer.wkbType(),
                crs,
                "GPKG",
            )

            if writer.hasError() != QgsVectorFileWriter.NoError:
                self._exception = Exception(
                    f"Erro ao criar GPKG: {writer.errorMessage()}"
                )
                return False

            total_features = src_layer.featureCount()
            now_iso = datetime.now(timezone.utc).isoformat()
            src_field_count = src_layer.fields().count()

            # Indice do campo 'id' na fonte (ZonalGeometria.id do servidor)
            id_field_idx = src_layer.fields().indexOf("id")

            for i, src_feat in enumerate(src_layer.getFeatures()):
                if self.isCanceled():
                    del writer
                    return False

                feat = QgsFeature(fields)
                feat.setGeometry(src_feat.geometry())

                # Copiar todos os atributos originais
                for j in range(src_field_count):
                    feat.setAttribute(j, src_feat.attribute(j))

                # Campos de sync V2
                base_idx = src_field_count
                original_fid = src_feat.attribute(id_field_idx) if id_field_idx >= 0 else src_feat.id()
                feat.setAttribute(base_idx + 0, original_fid)            # _original_fid
                feat.setAttribute(base_idx + 1, SyncStatusEnum.DOWNLOADED.value)
                feat.setAttribute(base_idx + 2, now_iso)                  # _sync_timestamp
                feat.setAttribute(base_idx + 3, self._zonal_id)           # _zonal_id
                feat.setAttribute(base_idx + 4, edit_token)               # _edit_token

                writer.addFeature(feat)

                if total_features > 0:
                    self.setProgress(55 + int((i + 1) * 35 / total_features))

            del writer  # Flush e fecha GPKG
            self.setProgress(90)

            # ----------------------------------------------------------
            # 4. Sidecar + Cleanup (90-100%)
            # ----------------------------------------------------------
            self.signals.status_message.emit("Gravando metadados...")

            write_sidecar(self._gpkg_path, {
                "zonalId": self._zonal_id,
                "editToken": edit_token,
                "zonalVersion": zonal_version,
                "snapshotHash": snapshot_hash,
                "featureCount": feature_count,
                "expiresAt": expires_at,
                "etag": response_etag,
                "downloadedAt": now_iso,
            })

            self.setProgress(100)
            self.signals.status_message.emit("Download concluido!")
            self._log(
                f"GPKG V2 criado: {self._gpkg_path} ({total_features} features)"
            )
            return True

        except requests.RequestException as e:
            self._exception = Exception(f"Erro de download: {e}")
            return False
        except Exception as e:
            self._exception = e
            return False
        finally:
            # Cleanup temp FGB
            if temp_fgb and os.path.exists(temp_fgb):
                try:
                    os.unlink(temp_fgb)
                except OSError:
                    pass
