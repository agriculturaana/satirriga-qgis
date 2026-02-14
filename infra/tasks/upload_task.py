"""Task para upload de classificacoes editadas."""

import os
import tempfile
import zipfile

import requests

from qgis.core import (
    QgsVectorLayer, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
    QgsFields, QgsField, QgsFeature, Qgis,
)
from qgis.PyQt.QtCore import QVariant

from .base_task import SatIrrigaTask
from ...domain.models.enums import SyncStatusEnum


class UploadClassificationTask(SatIrrigaTask):
    """Exporta features MODIFIED para GPKG temp, compacta e envia via POST."""

    def __init__(self, upload_url, access_token, gpkg_source_path,
                 mapeamento_id, metodo_id):
        super().__init__(f"Upload classificacao metodo {metodo_id}")
        self._url = upload_url
        self._token = access_token
        self._source_path = gpkg_source_path
        self._mapeamento_id = mapeamento_id
        self._metodo_id = metodo_id
        self._uploaded_count = 0

    @property
    def uploaded_count(self):
        return self._uploaded_count

    def run(self):
        try:
            self.signals.status_message.emit("Preparando upload...")
            self.setProgress(5)

            # 1. Abrir source GPKG
            src_layer = QgsVectorLayer(self._source_path, "upload_src", "ogr")
            if not src_layer.isValid():
                self._exception = Exception(f"GPKG invalido: {self._source_path}")
                return False

            # 2. Filtrar features MODIFIED
            modified_features = []
            sync_idx = src_layer.fields().indexOf("_sync_status")
            for feat in src_layer.getFeatures():
                if self.isCanceled():
                    return False
                if sync_idx >= 0 and feat.attribute(sync_idx) == SyncStatusEnum.MODIFIED.value:
                    modified_features.append(feat)

            if not modified_features:
                self._exception = Exception("Nenhuma feature modificada para enviar")
                return False

            self.setProgress(20)
            self.signals.status_message.emit(
                f"Exportando {len(modified_features)} features..."
            )

            # 3. Criar GPKG temporario sem campos _sync_*
            temp_dir = tempfile.mkdtemp(prefix="satirriga_upload_")
            temp_gpkg = os.path.join(temp_dir, "upload.gpkg")

            # Campos sem prefixo _sync_
            clean_fields = QgsFields()
            sync_field_names = {"_original_fid", "_sync_status", "_sync_timestamp",
                                "_mapeamento_id", "_metodo_id"}
            field_mapping = []
            for field in src_layer.fields():
                if field.name() not in sync_field_names:
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
                self._exception = Exception(f"Erro ao criar GPKG temp: {writer.errorMessage()}")
                return False

            for feat in modified_features:
                clean_feat = QgsFeature(clean_fields)
                clean_feat.setGeometry(feat.geometry())
                for new_idx, old_idx in enumerate(field_mapping):
                    clean_feat.setAttribute(new_idx, feat.attribute(old_idx))
                writer.addFeature(clean_feat)

            del writer
            self.setProgress(50)

            # 4. Compactar em ZIP
            temp_zip = os.path.join(temp_dir, "upload.zip")
            with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(temp_gpkg, "upload.gpkg")

            self.setProgress(60)
            self.signals.status_message.emit("Enviando para servidor...")

            # 5. Upload multipart
            headers = {"Authorization": f"Bearer {self._token}"}
            with open(temp_zip, "rb") as f:
                files = {"file": ("upload.zip", f, "application/zip")}
                data = {
                    "mapeamentoId": str(self._mapeamento_id),
                    "metodoId": str(self._metodo_id),
                }
                response = requests.post(
                    self._url, headers=headers,
                    files=files, data=data, timeout=300,
                )

            self.setProgress(90)

            if response.status_code == 200:
                self._uploaded_count = len(modified_features)
                self.setProgress(100)
                self.signals.status_message.emit(
                    f"Upload concluido: {self._uploaded_count} features enviadas"
                )
                self._log(f"Upload: {self._uploaded_count} features para metodo {self._metodo_id}")
                return True
            else:
                self._exception = Exception(
                    f"Servidor retornou HTTP {response.status_code}: {response.text[:200]}"
                )
                return False

        except requests.RequestException as e:
            self._exception = Exception(f"Erro de upload: {e}")
            return False
        except Exception as e:
            self._exception = e
            return False
        finally:
            # Cleanup temp files
            import shutil
            if 'temp_dir' in dir():
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass
