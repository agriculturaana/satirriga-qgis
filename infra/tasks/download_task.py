"""Task para download de classificacao (SHP ZIP -> GPKG)."""

import os
import tempfile

import requests

from qgis.core import (
    QgsVectorLayer, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsField, QgsFields, QgsFeature, Qgis,
)
from qgis.PyQt.QtCore import QVariant

from .base_task import SatIrrigaTask
from ...domain.models.enums import SyncStatusEnum
from ...domain.services.gpkg_service import SYNC_FIELDS


class DownloadClassificationTask(SatIrrigaTask):
    """Baixa SHP via HTTP, converte para GPKG com campos de sync."""

    def __init__(self, download_url, access_token, gpkg_output_path,
                 mapeamento_id, metodo_id):
        super().__init__(f"Download classificacao metodo {metodo_id}")
        self._url = download_url
        self._token = access_token
        self._gpkg_path = gpkg_output_path
        self._mapeamento_id = mapeamento_id
        self._metodo_id = metodo_id

    def run(self):
        """Executa em worker thread: download + conversao."""
        try:
            self.signals.status_message.emit("Baixando arquivo...")
            self.setProgress(5)

            # 1. Download ZIP (usa requests pois estamos em worker thread)
            headers = {"Authorization": f"Bearer {self._token}"}
            response = requests.get(self._url, headers=headers, stream=True, timeout=120)
            response.raise_for_status()

            # Salva em temp
            temp_zip = tempfile.NamedTemporaryFile(
                delete=False, suffix=".zip", prefix="satirriga_"
            )
            temp_path = temp_zip.name

            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if self.isCanceled():
                    temp_zip.close()
                    os.unlink(temp_path)
                    return False
                temp_zip.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    self.setProgress(5 + int(downloaded * 45 / total))

            temp_zip.close()
            self.setProgress(50)

            # 2. Carregar via /vsizip/
            self.signals.status_message.emit("Convertendo para GPKG...")
            zip_path = f"/vsizip/{temp_path}"
            src_layer = QgsVectorLayer(zip_path, "temp_src", "ogr")

            if not src_layer.isValid():
                self._exception = Exception(
                    f"Falha ao abrir SHP do ZIP: {temp_path}"
                )
                os.unlink(temp_path)
                return False

            self.setProgress(60)

            # 3. Criar GPKG de saida com campos adicionais de sync
            os.makedirs(os.path.dirname(self._gpkg_path), exist_ok=True)

            # Build fields: campos originais + sync fields
            fields = QgsFields()
            for field in src_layer.fields():
                fields.append(field)

            sync_type_map = {
                "INTEGER": QVariant.Int,
                "TEXT": QVariant.String,
                "REAL": QVariant.Double,
            }
            for fname, ftype in SYNC_FIELDS:
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
                os.unlink(temp_path)
                return False

            # 4. Copiar features com campos de sync
            total_features = src_layer.featureCount()
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()

            for i, src_feat in enumerate(src_layer.getFeatures()):
                if self.isCanceled():
                    del writer
                    os.unlink(temp_path)
                    return False

                feat = QgsFeature(fields)
                feat.setGeometry(src_feat.geometry())

                # Copiar atributos originais
                for j in range(src_layer.fields().count()):
                    feat.setAttribute(j, src_feat.attribute(j))

                # Adicionar campos de sync
                base_idx = src_layer.fields().count()
                feat.setAttribute(base_idx + 0, src_feat.id())      # _original_fid
                feat.setAttribute(base_idx + 1, SyncStatusEnum.DOWNLOADED.value)
                feat.setAttribute(base_idx + 2, now_iso)             # _sync_timestamp
                feat.setAttribute(base_idx + 3, self._mapeamento_id)
                feat.setAttribute(base_idx + 4, self._metodo_id)

                writer.addFeature(feat)

                if total_features > 0:
                    self.setProgress(60 + int((i + 1) * 35 / total_features))

            del writer  # Flush e fecha GPKG

            # Cleanup temp
            try:
                os.unlink(temp_path)
            except OSError:
                pass

            self.setProgress(100)
            self.signals.status_message.emit("Download concluido!")
            self._log(
                f"GPKG criado: {self._gpkg_path} ({total_features} features)"
            )
            return True

        except requests.RequestException as e:
            self._exception = Exception(f"Erro de download: {e}")
            return False
        except Exception as e:
            self._exception = e
            return False
