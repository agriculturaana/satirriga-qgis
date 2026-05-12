"""Task para download de zonal (checkout + GPKG).

Usa osgeo.ogr/gdal para normalizar o GeoPackage em worker thread,
evitando criar QgsVectorLayer fora da main thread.
"""

import os
import shutil
import tempfile
from datetime import datetime, timezone

import requests

from qgis.core import Qgis

from .base_task import SatIrrigaTask
from ...domain.models.enums import SyncStatusEnum, DownloadOrigin
from ...domain.services.gpkg_service import SYNC_FIELDS_V2, write_sidecar, read_sidecar


class DownloadZonalTask(SatIrrigaTask):
    """Checkout + download GeoPackage + campos V2 de sincronizacao."""

    def __init__(self, checkout_url, download_url, access_token,
                 gpkg_output_path, zonal_id, catalogo_meta=None,
                 read_only=False, origin=None):
        super().__init__(f"Download zonal {zonal_id}")
        self._checkout_url = checkout_url
        self._download_url = download_url
        self._token = access_token
        self._gpkg_path = gpkg_output_path
        self._zonal_id = zonal_id
        self._catalogo_meta = catalogo_meta or {}
        self._read_only = read_only
        self._origin = DownloadOrigin.coerce(origin).value

    def _validate_existing_gpkg(self, gpkg_path, expected_count):
        """Verifica se GPKG existente tem features e geometrias validas.

        Usa osgeo.ogr para evitar criar QgsVectorLayer em worker thread.
        """
        if not os.path.exists(gpkg_path):
            self._log("[Download] GPKG nao encontrado para validacao de cache")
            return False
        try:
            from osgeo import ogr
            ds = ogr.Open(gpkg_path, 0)  # read-only
            if ds is None:
                self._log("[Download] GPKG em cache invalido (ogr.Open falhou)")
                return False
            lyr = ds.GetLayer(0)
            if lyr is None:
                ds = None
                self._log("[Download] GPKG em cache sem layer")
                return False
            actual = lyr.GetFeatureCount()
            if actual == 0 and expected_count > 0:
                ds = None
                self._log(
                    f"[Download] GPKG em cache vazio "
                    f"(0/{expected_count} features)"
                )
                return False
            # Verifica se a primeira feature tem geometria
            feat = lyr.GetNextFeature()
            if feat is not None and feat.GetGeometryRef() is None:
                ds = None
                self._log(
                    "[Download] GPKG em cache tem features sem geometria"
                )
                return False
            ds = None  # fecha dataset
            self._log(
                f"[Download] GPKG em cache valido ({actual} features)"
            )
            return True
        except Exception as e:
            self._log(f"[Download] Erro validando GPKG em cache: {e}")
            return False

    def run(self):
        """Executa em worker thread: checkout -> download GPKG -> normalizacao."""
        temp_gpkg = None
        try:
            headers = {"Authorization": f"Bearer {self._token}"}

            # ----------------------------------------------------------
            # 1. Checkout (5-15%) — pulado em modo somente leitura
            # ----------------------------------------------------------
            edit_token = ""
            zonal_version = 0
            feature_count = 0
            snapshot_hash = ""
            expires_at = ""

            if self._read_only:
                self.signals.status_message.emit("Baixando (somente leitura)...")
                self.setProgress(15)
                self._log(f"[Download] Modo somente leitura — checkout ignorado")
            else:
                self.signals.status_message.emit("Realizando checkout...")
                self.setProgress(5)

                self._log(f"[HTTP] POST {self._checkout_url} (auth=True)")
                checkout_resp = requests.post(
                    self._checkout_url, headers=headers, timeout=30,
                )
                self._log(
                    f"[HTTP] {checkout_resp.status_code} {self._checkout_url}"
                )
                if checkout_resp.status_code == 403:
                    try:
                        err_body = checkout_resp.json()
                        server_msg = err_body.get("message", "")
                        self._log(
                            f"[Download] 403 Forbidden - {server_msg or checkout_resp.text[:200]}"
                        )
                    except Exception:
                        server_msg = checkout_resp.text[:200]
                        self._log(f"[Download] 403 Forbidden - {server_msg}")
                    self._exception = Exception(
                        server_msg
                        or "Acesso negado ao checkout. Verifique suas permissões."
                    )
                    return False

                if checkout_resp.status_code == 409:
                    try:
                        err_body = checkout_resp.json()
                        if err_body.get("error") == "EM_EDICAO":
                            usuario = err_body.get("usuario", "outro usuário")
                            desde = err_body.get("desde", "")
                            err_msg = (
                                f"Este mapeamento está sendo editado por {usuario}"
                                f"{' desde ' + desde[:10] if desde else ''}."
                            )
                        else:
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
            # 2. Download GeoPackage (15-55%)
            # ----------------------------------------------------------
            self.signals.status_message.emit("Baixando dados geoespaciais...")

            dl_headers = {
                **headers,
                "Accept": "application/geopackage+sqlite3",
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
                        "origin": self._origin,
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

            header_feature_count = dl_resp.headers.get("X-Feature-Count")
            if header_feature_count is not None:
                try:
                    feature_count = int(header_feature_count)
                except (TypeError, ValueError):
                    pass

            # Stream download GPKG para temp
            temp_fd, temp_gpkg = tempfile.mkstemp(
                suffix=".gpkg", prefix="satirriga_"
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
            # 3. Normalizacao do GPKG (55-90%) via GDAL/OGR
            # ----------------------------------------------------------
            self.signals.status_message.emit("Preparando GeoPackage...")

            from osgeo import ogr, gdal
            gdal.UseExceptions()

            os.makedirs(os.path.dirname(self._gpkg_path), exist_ok=True)

            dst_ds = ogr.Open(temp_gpkg, 1)
            if dst_ds is None:
                self._exception = Exception(
                    f"Falha ao abrir GeoPackage baixado: {temp_gpkg}"
                )
                return False

            dst_lyr = dst_ds.GetLayer(0)
            if dst_lyr is None:
                dst_ds = None
                self._exception = Exception("GeoPackage baixado sem layers")
                return False

            dst_defn = dst_lyr.GetLayerDefn()
            ogr_type_map = {"INTEGER": ogr.OFTInteger, "TEXT": ogr.OFTString}
            for fname, ftype in SYNC_FIELDS_V2:
                if dst_defn.GetFieldIndex(fname) < 0:
                    fd = ogr.FieldDefn(
                        fname, ogr_type_map.get(ftype, ogr.OFTString)
                    )
                    dst_lyr.CreateField(fd)
            dst_defn = dst_lyr.GetLayerDefn()

            id_field_idx = dst_defn.GetFieldIndex("id")
            total_features = dst_lyr.GetFeatureCount()
            self._log(
                f"[Download] GPKG servidor: {total_features} features, "
                f"{dst_defn.GetFieldCount()} campos"
            )

            now_iso = datetime.now(timezone.utc).isoformat()
            written_count = 0
            write_errors = 0
            dst_lyr.StartTransaction()

            try:
                dst_lyr.ResetReading()
                for i, dst_feat in enumerate(dst_lyr):
                    if self.isCanceled():
                        dst_lyr.RollbackTransaction()
                        dst_ds = None
                        return False

                    original_fid = (
                        dst_feat.GetField(id_field_idx)
                        if id_field_idx >= 0 else dst_feat.GetFID()
                    )
                    dst_feat.SetField("_original_fid", original_fid)
                    dst_feat.SetField("_sync_status", SyncStatusEnum.DOWNLOADED.value)
                    dst_feat.SetField("_sync_timestamp", now_iso)
                    dst_feat.SetField("_zonal_id", self._zonal_id)
                    dst_feat.SetField("_edit_token", edit_token)

                    err = dst_lyr.SetFeature(dst_feat)
                    if err == ogr.OGRERR_NONE:
                        written_count += 1
                    else:
                        write_errors += 1
                        if write_errors <= 3:
                            self._log(
                                f"[Download] SetFeature falhou para "
                                f"feature {i} (id={original_fid})"
                            )

                    # Log diagnostico da primeira feature
                    if i == 0:
                        geom = dst_feat.GetGeometryRef()
                        self._log(
                            f"[Download] Primeira feature: "
                            f"geom_null={geom is None}, "
                            f"geom_type={geom.GetGeometryType() if geom else 'N/A'}, "
                            f"attrs={dst_feat.GetFieldCount()}"
                        )

                    if total_features > 0:
                        self.setProgress(
                            min(90, 55 + int((i + 1) * 35 / total_features))
                        )
            except Exception:
                dst_lyr.RollbackTransaction()
                raise

            dst_lyr.CommitTransaction()
            # Flush e fecha GPKG antes de mover para o caminho final
            dst_ds = None

            if os.path.exists(self._gpkg_path):
                os.remove(self._gpkg_path)
            shutil.move(temp_gpkg, self._gpkg_path)
            temp_gpkg = None
            self.setProgress(90)

            self._log(
                f"[Download] Resultado normalizacao: "
                f"{written_count} escritas, {write_errors} erros de escrita, "
                f"{total_features} features no GPKG"
            )

            if written_count == 0 and total_features > 0:
                self._exception = Exception(
                    f"GeoPackage contem {total_features} features mas nenhuma "
                    f"foi preparada para edicao ({write_errors} erros)."
                )
                return False

            # ----------------------------------------------------------
            # 4. Sidecar + Cleanup (90-100%)
            # ----------------------------------------------------------
            self.signals.status_message.emit("Gravando metadados...")

            sidecar_data = {
                "zonalId": self._zonal_id,
                "editToken": edit_token,
                "zonalVersion": zonal_version,
                "snapshotHash": snapshot_hash,
                "featureCount": feature_count,
                "expiresAt": expires_at,
                "etag": response_etag,
                "downloadedAt": now_iso,
                "readOnly": self._read_only,
                "origin": self._origin,
            }
            # Dados enriquecidos do catalogo
            if self._catalogo_meta:
                sidecar_data.update(self._catalogo_meta)
            write_sidecar(self._gpkg_path, sidecar_data)

            self.setProgress(100)
            self.signals.status_message.emit("Download concluido!")
            self._log(
                f"GPKG V2 baixado: {self._gpkg_path} "
                f"({written_count} features preparadas)"
            )
            return True

        except requests.RequestException as e:
            self._exception = Exception(f"Erro de download: {e}")
            return False
        except Exception as e:
            self._exception = e
            return False
        finally:
            # Cleanup temp GPKG
            if temp_gpkg and os.path.exists(temp_gpkg):
                try:
                    os.unlink(temp_gpkg)
                except OSError:
                    pass
