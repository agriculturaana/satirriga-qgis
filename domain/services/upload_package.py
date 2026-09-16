"""Pacote persistente e identidade lógica das edições de uma zonal."""

import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

from .gpkg_service import has_pending_upload, read_sidecar, update_sidecar

EXCLUDED_FIELDS = {"_edit_token", "_sync_timestamp", "_zonal_id", "_mapeamento_id", "_metodo_id"}


def ensure_client_feature_ids(source_path):
    from osgeo import ogr

    source = ogr.Open(source_path, 1)
    if source is None or source.GetLayerCount() == 0:
        raise ValueError("GeoPackage inválido ou sem camadas.")
    layer = source.GetLayer(0)
    if layer.GetLayerDefn().GetFieldIndex("_client_feature_id") < 0:
        if layer.CreateField(ogr.FieldDefn("_client_feature_id", ogr.OFTString)) != ogr.OGRERR_NONE:
            raise RuntimeError("Não foi possível persistir o campo de identidade das inclusões.")
    seen = set()
    layer.StartTransaction()
    try:
        for feature in layer:
            original = feature.GetField("_original_fid")
            status = feature.GetField("_sync_status")
            identity = feature.GetField("_client_feature_id")
            if status != "DELETED" and (status == "NEW" or not original):
                if not identity:
                    identity = str(uuid.uuid4())
                    feature.SetField("_client_feature_id", identity)
                    if layer.SetFeature(feature) != ogr.OGRERR_NONE:
                        raise RuntimeError("Não foi possível persistir a identidade da inclusão.")
                uuid.UUID(identity)
                if identity in seen:
                    raise ValueError("Inclusões com identificadores locais duplicados. Revise as cópias antes de enviar.")
                seen.add(identity)
        layer.CommitTransaction()
    except Exception:
        layer.RollbackTransaction()
        raise
    finally:
        source = None


def _logical_hash(layer, field_indexes):
    definition = layer.GetLayerDefn()
    fields = [(definition.GetFieldDefn(i).GetName(), definition.GetFieldDefn(i).GetType()) for i in field_indexes]
    srs = layer.GetSpatialRef()
    digest = hashlib.sha256(json.dumps([fields, srs.ExportToWkt() if srs else None, layer.GetGeomType()]).encode())
    rows = []
    for feature in layer:
        geometry = feature.GetGeometryRef()
        values = [feature.GetField(i) for i in field_indexes]
        serialized = json.dumps([values, bytes(geometry.ExportToWkb()).hex() if geometry else None],
                                ensure_ascii=False, separators=(",", ":"), default=str)
        rows.append(hashlib.sha256(serialized.encode()).digest())
    # FIDs locais, ordem física e datas do contêiner não fazem parte do conteúdo enviado.
    for row in sorted(rows):
        digest.update(row)
    layer.ResetReading()
    return digest.hexdigest()


def archive_path(source_path, operation):
    operation_id = str(uuid.UUID(operation["operationId"]))
    return os.path.join(os.path.dirname(source_path), ".satirriga-upload", operation_id + ".zip")


def archive_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def operation_recoverable(source_path, operation):
    if operation.get("batchUuid"):
        return True
    path = archive_path(source_path, operation)
    return bool(operation.get("archiveHash")) and os.path.isfile(path) and archive_hash(path) == operation["archiveHash"]


def abandon_unrecoverable_operations(source_path, operations):
    # Sem recibo e sem os bytes originais, a operação não pode ser repetida. A operação seguinte parte da mesma base,
    # e o servidor recusa a base já consumida (VERSION_CONFLICT) ou o lote ainda em processamento (UPLOAD_IN_PROGRESS).
    for operation in operations:
        if operation.get("abandoned") or operation.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
            continue
        if not operation_recoverable(source_path, operation):
            operation.update(abandoned=True, abandonedAt=datetime.now(timezone.utc).isoformat())
            save_operation(source_path, operation)


def save_operation(source_path, operation, **metadata):
    def merge(sidecar):
        operations = sidecar.setdefault("uploadOperations", [])
        for index, existing in enumerate(operations):
            if existing["operationId"] == operation["operationId"]:
                operations[index] = dict(operation)
                break
        else:
            operations.append(dict(operation))
        sidecar.update(metadata)
    update_sidecar(source_path, merge)


def prepare_operation(source_path, upload_url, expected_version, conflict_strategy, cancelled=lambda: False):
    from osgeo import gdal, ogr, osr

    gdal.UseExceptions()
    sidecar = read_sidecar(source_path)
    if sidecar.get("readOnly"):
        raise ValueError("Esta cópia permite somente leitura.")
    base_version = sidecar.get("zonalVersion")
    snapshot_hash = sidecar.get("snapshotHash")
    if base_version is None or not snapshot_hash or base_version != expected_version:
        raise ValueError("Metadados da revisão-base ausentes ou divergentes. Faça novo download.")
    ensure_client_feature_ids(source_path)
    source = ogr.Open(source_path, 0)
    layer = source.GetLayer(0)
    definition = layer.GetLayerDefn()
    indexes = [i for i in range(definition.GetFieldCount())
               if definition.GetFieldDefn(i).GetName() not in EXCLUDED_FIELDS]
    logical_hash = _logical_hash(layer, indexes)
    scope = {"logicalHash": logical_hash, "baseVersion": base_version,
             "baseSnapshotHash": snapshot_hash, "conflictStrategy": conflict_strategy,
             "uploadUrl": upload_url}
    operations = sidecar.get("uploadOperations", [])
    abandon_unrecoverable_operations(source_path, operations)
    for operation in reversed(operations):
        if operation.get("abandoned") or not all(operation.get(key) == value for key, value in scope.items()):
            continue
        # Um lote encerrado sem persistência não alterou o servidor; o mesmo conteúdo segue em outra operação.
        if operation.get("status") in ("FAILED", "CANCELLED"):
            break
        source = None
        return dict(operation)
    if sidecar.get("needsRedownload"):
        raise ValueError("A cópia local antecede o envio persistido. Faça novo download antes de enviar outras edições.")
    if has_pending_upload(sidecar):
        raise ValueError("Há um envio pendente com outro conteúdo. Recupere o recibo do envio anterior antes de fazer novo download.")
    operation = {**scope, "operationId": str(uuid.uuid4()), "protocolVersion": 2}
    path = archive_path(source_path, operation)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="satirriga_export_") as temp_dir:
        exported = os.path.join(temp_dir, "upload.gpkg")
        destination = ogr.GetDriverByName("GPKG").CreateDataSource(exported)
        srs = layer.GetSpatialRef()
        if srs is None:
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(4326)
        output = destination.CreateLayer("upload", srs=srs, geom_type=layer.GetGeomType(), options=["FID=fid"])
        for index in indexes:
            output.CreateField(definition.GetFieldDefn(index))
        output.StartTransaction()
        try:
            for feature in layer:
                if cancelled():
                    raise InterruptedError("Exportação cancelada.")
                exported_feature = ogr.Feature(output.GetLayerDefn())
                geometry = feature.GetGeometryRef()
                if geometry is not None:
                    exported_feature.SetGeometry(geometry)
                for target_index, source_index in enumerate(indexes):
                    if feature.IsFieldSetAndNotNull(source_index):
                        exported_feature.SetField(target_index, feature.GetField(source_index))
                if output.CreateFeature(exported_feature) != ogr.OGRERR_NONE:
                    raise RuntimeError("Não foi possível exportar uma feição.")
            output.CommitTransaction()
        except Exception:
            output.RollbackTransaction()
            raise
        finally:
            destination = None
            source = None
        staging = path + ".tmp"
        try:
            # O Windows só sincroniza descritores abertos para escrita.
            with open(staging, "wb") as stream:
                with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(exported, "upload.gpkg")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staging, path)
        finally:
            if os.path.exists(staging):
                os.unlink(staging)
    operation["archiveHash"] = archive_hash(path)
    save_operation(source_path, operation)
    return operation
