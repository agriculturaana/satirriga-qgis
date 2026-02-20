"""Task para download de zonal (checkout + FlatGeobuf -> GPKG)."""

import os
import tempfile
from datetime import datetime, timezone

import requests

from qgis.core import (
    QgsVectorLayer, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext, QgsField, QgsFields, QgsFeature, Qgis,
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

    def _validate_existing_gpkg(self, gpkg_path, expected_count):
        """Verifica se GPKG existente tem features e geometrias validas."""
        if not os.path.exists(gpkg_path):
            self._log("[Download] GPKG nao encontrado para validacao de cache")
            return False
        try:
            layer = QgsVectorLayer(gpkg_path, "cache_check", "ogr")
            if not layer.isValid():
                self._log("[Download] GPKG em cache invalido como layer")
                return False
            actual = layer.featureCount()
            if actual == 0 and expected_count > 0:
                self._log(
                    f"[Download] GPKG em cache vazio "
                    f"(0/{expected_count} features)"
                )
                return False
            # Verifica se a primeira feature tem geometria
            for feat in layer.getFeatures():
                if feat.geometry().isNull():
                    self._log(
                        "[Download] GPKG em cache tem features sem geometria"
                    )
                    return False
                break
            self._log(
                f"[Download] GPKG em cache valido ({actual} features)"
            )
            return True
        except Exception as e:
            self._log(f"[Download] Erro validando GPKG em cache: {e}")
            return False

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

            self._log(f"[HTTP] POST {self._checkout_url} (auth=True)")
            checkout_resp = requests.post(
                self._checkout_url, headers=headers, timeout=30,
            )
            self._log(
                f"[HTTP] {checkout_resp.status_code} {self._checkout_url}"
            )
            if checkout_resp.status_code == 409:
                try:
                    err_body = checkout_resp.json()
                    err_msg = err_body.get("message", "Zonal bloqueado (409)")
                except Exception:
                    err_msg = "Zonal bloqueado (409)"
                self._exception = Exception(err_msg)
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

            self._log(f"[HTTP] GET {self._download_url} (auth=True)")
            dl_resp = requests.get(
                self._download_url, headers=dl_headers,
                stream=True, timeout=120,
            )
            self._log(
                f"[HTTP] {dl_resp.status_code} {self._download_url}"
            )

            # 304 Not Modified — valida GPKG existente antes de aceitar cache
            if dl_resp.status_code == 304:
                expected_count = existing_sidecar.get("featureCount", 0)
                gpkg_valid = self._validate_existing_gpkg(
                    self._gpkg_path, expected_count,
                )
                if gpkg_valid:
                    self.signals.status_message.emit(
                        "Dados em cache, atualizando checkout..."
                    )
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
                    self.signals.status_message.emit(
                        "Download concluido (cache)!"
                    )
                    return True
                # GPKG invalido — forca re-download sem ETag
                self._log(
                    "[Download] GPKG em cache invalido, forcando re-download"
                )
                self.signals.status_message.emit(
                    "Cache invalido, baixando novamente..."
                )
                dl_headers.pop("If-None-Match", None)
                dl_resp = requests.get(
                    self._download_url, headers=dl_headers,
                    stream=True, timeout=120,
                )
                self._log(
                    f"[HTTP] {dl_resp.status_code} {self._download_url} "
                    "(re-download)"
                )

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

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "utf-8"
            writer = QgsVectorFileWriter.create(
                self._gpkg_path, fields, src_layer.wkbType(),
                crs, QgsCoordinateTransformContext(), options,
            )

            if writer is None or writer.hasError() != QgsVectorFileWriter.NoError:
                err_msg = writer.errorMessage() if writer else "writer nulo"
                self._exception = Exception(f"Erro ao criar GPKG: {err_msg}")
                return False

            total_features = src_layer.featureCount()
            self._log(
                f"[Download] FGB: {total_features} features, "
                f"{src_layer.fields().count()} campos, "
                f"CRS={src_layer.crs().authid()}"
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            src_field_count = src_layer.fields().count()

            # Indice do campo 'id' na fonte (ZonalGeometria.id do servidor)
            id_field_idx = src_layer.fields().indexOf("id")

            written_count = 0
            write_errors = 0
            for i, src_feat in enumerate(src_layer.getFeatures()):
                if self.isCanceled():
                    del writer
                    return False

                feat = QgsFeature(fields)
                geom = src_feat.geometry()
                feat.setGeometry(geom)

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

                ok = writer.addFeature(feat)
                if ok:
                    written_count += 1
                else:
                    write_errors += 1
                    if write_errors <= 3:
                        self._log(
                            f"[Download] addFeature falhou para "
                            f"feature {i} (id={original_fid}): "
                            f"{writer.errorMessage()}"
                        )

                # Log diagnostico da primeira feature
                if i == 0:
                    self._log(
                        f"[Download] Primeira feature: "
                        f"geom_null={geom.isNull()}, "
                        f"geom_type={geom.type()}, "
                        f"wkb_type={geom.wkbType()}, "
                        f"attrs={feat.attributeCount()}"
                    )

                if total_features > 0:
                    self.setProgress(55 + int((i + 1) * 35 / total_features))

            del writer  # Flush e fecha GPKG
            self.setProgress(90)

            self._log(
                f"[Download] Resultado conversao: "
                f"{written_count} escritas, {write_errors} erros, "
                f"{total_features} declaradas no FGB"
            )

            if written_count == 0 and total_features > 0:
                self._exception = Exception(
                    f"FlatGeobuf declara {total_features} features mas nenhuma "
                    f"foi escrita no GPKG ({write_errors} erros de escrita). "
                    f"Possivel incompatibilidade de formato."
                )
                return False

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
                f"GPKG V2 criado: {self._gpkg_path} "
                f"({written_count} features escritas)"
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
