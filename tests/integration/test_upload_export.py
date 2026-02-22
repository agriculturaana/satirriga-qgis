"""Testes de integracao: export GPKG para upload (logica do UploadZonalTask).

Valida que o export via GDAL/OGR filtra campos internos,
preserva atributos do dominio, geometrias e campos usados pelo servidor.

Usa GDAL/OGR real — sem mocks de QGIS.
"""

import os
import zipfile
import tempfile
import shutil

import pytest
from osgeo import ogr, osr

from .conftest import (
    create_gpkg_v2_with_features,
    read_gpkg_features,
    read_gpkg_field_names,
    read_gpkg_srs,
    SAMPLE_FEATURES,
    SAMPLE_POLYGONS,
)


# Campos internos que devem ser removidos (replicado de upload_task.py)
INTERNAL_FIELDS = {"_edit_token", "_sync_timestamp", "_zonal_id",
                   "_mapeamento_id", "_metodo_id"}


def export_gpkg_for_upload(source_path, dest_path):
    """Replica a logica exata de export do UploadZonalTask.run().

    Retorna feature count exportado.
    """
    from osgeo import ogr, gdal
    gdal.UseExceptions()

    src_ds = ogr.Open(source_path, 0)
    if src_ds is None:
        raise Exception(f"GPKG invalido: {source_path}")

    src_lyr = src_ds.GetLayer(0)
    if src_lyr is None:
        src_ds = None
        raise Exception(f"GPKG sem layers: {source_path}")

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    src_defn = src_lyr.GetLayerDefn()
    field_mapping = []
    for i in range(src_defn.GetFieldCount()):
        fd = src_defn.GetFieldDefn(i)
        if fd.GetName() not in INTERNAL_FIELDS:
            field_mapping.append((i, fd))

    src_srs = src_lyr.GetSpatialRef()
    if src_srs is None:
        src_srs = osr.SpatialReference()
        src_srs.ImportFromEPSG(4326)

    gpkg_drv = ogr.GetDriverByName("GPKG")
    dst_ds = gpkg_drv.CreateDataSource(dest_path)
    if dst_ds is None:
        src_ds = None
        raise Exception(f"Erro ao criar GPKG temp: {dest_path}")

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
        dst_feat = ogr.Feature(dst_defn)
        geom = src_feat.GetGeometryRef()
        if geom is not None:
            dst_feat.SetGeometry(geom.Clone())
        for new_idx, (old_idx, _) in enumerate(field_mapping):
            dst_feat.SetField(new_idx, src_feat.GetField(old_idx))
        dst_lyr.CreateFeature(dst_feat)

    dst_lyr.CommitTransaction()
    src_ds = None
    dst_ds = None

    return total_features


def export_and_zip(source_path, zip_path):
    """Replica export + ZIP do UploadZonalTask."""
    temp_dir = tempfile.mkdtemp(prefix="satirriga_test_export_")
    try:
        temp_gpkg = os.path.join(temp_dir, "upload.gpkg")
        count = export_gpkg_for_upload(source_path, temp_gpkg)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(temp_gpkg, "upload.gpkg")

        return count
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: GPKG export com filtragem de campos
# ---------------------------------------------------------------------------

class TestGpkgExportFieldFiltering:
    """Testa que campos internos sao removidos e campos uteis preservados."""

    def test_internal_fields_removed(self, temp_dir):
        """Campos internos nao devem estar no export."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES)

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(source, dest)

        field_names = read_gpkg_field_names(dest)
        for f in INTERNAL_FIELDS:
            assert f not in field_names, f"Campo interno '{f}' nao deveria estar no export"

    def test_original_fid_preserved(self, temp_dir):
        """_original_fid deve ser preservado (servidor usa)."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES)

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(source, dest)

        field_names = read_gpkg_field_names(dest)
        assert "_original_fid" in field_names

        features = read_gpkg_features(dest)
        assert features[0]["_original_fid"] == 101
        assert features[1]["_original_fid"] == 102
        assert features[2]["_original_fid"] == 103

    def test_sync_status_preserved(self, temp_dir):
        """_sync_status deve ser preservado (servidor usa para classificar)."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES)

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(source, dest)

        field_names = read_gpkg_field_names(dest)
        assert "_sync_status" in field_names

    def test_domain_fields_preserved(self, temp_dir):
        """Campos do dominio devem estar presentes."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES)

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(source, dest)

        field_names = read_gpkg_field_names(dest)
        for expected in ("id", "idSeg", "areaHa", "grupo", "consolidado"):
            assert expected in field_names, f"Campo '{expected}' ausente no export"


class TestGpkgExportDataPreservation:
    """Testa que dados sao preservados corretamente no export."""

    def test_attribute_values_preserved(self, temp_dir):
        """Valores dos atributos devem ser identicos ao source."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES)

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(source, dest)

        features = read_gpkg_features(dest)
        f1 = features[0]
        assert f1["id"] == 101
        assert f1["idSeg"] == 1
        assert abs(f1["areaHa"] - 150.5) < 0.01
        assert f1["grupo"] == "Irrigacao"
        assert f1["consolidado"] == 1

        f3 = features[2]
        assert f3["id"] == 103
        assert abs(f3["areaHa"] - 75.0) < 0.01

    def test_geometry_preserved(self, temp_dir):
        """Todas as geometrias devem ser preservadas."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES)

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(source, dest)

        features = read_gpkg_features(dest)
        for feat in features:
            assert feat["has_geometry"] is True
            assert feat["geom_type"] == ogr.wkbPolygon

    def test_geometry_coordinates_match(self, temp_dir):
        """Coordenadas devem ser identicas ao source."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES[:1])

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(source, dest)

        src_features = read_gpkg_features(source)
        dst_features = read_gpkg_features(dest)

        src_geom = ogr.CreateGeometryFromWkt(src_features[0]["geom_wkt"])
        dst_geom = ogr.CreateGeometryFromWkt(dst_features[0]["geom_wkt"])

        # Geometrias devem ser iguais
        assert src_geom.Equal(dst_geom)

    def test_feature_count_matches(self, temp_dir):
        """Numero de features deve ser identico."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES)

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        count = export_gpkg_for_upload(source, dest)

        assert count == 3
        features = read_gpkg_features(dest)
        assert len(features) == 3

    def test_crs_preserved(self, temp_dir):
        """CRS deve ser preservado (EPSG:4326)."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES[:1])

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(source, dest)

        assert read_gpkg_srs(dest) == "4326"

    def test_empty_source_succeeds(self, temp_dir):
        """Export de GPKG vazio deve funcionar."""
        source = os.path.join(temp_dir, "empty.gpkg")
        create_gpkg_v2_with_features(source, [])

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        count = export_gpkg_for_upload(source, dest)

        assert count == 0
        features = read_gpkg_features(dest)
        assert len(features) == 0

    def test_modified_features_exported(self, temp_dir):
        """Features com _sync_status=MODIFIED devem ser exportadas."""
        modified = [{**feat, "sync_status": "MODIFIED"} for feat in SAMPLE_FEATURES]
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, modified)

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(source, dest)

        features = read_gpkg_features(dest)
        assert len(features) == 3
        for feat in features:
            assert feat["_sync_status"] == "MODIFIED"

    def test_mixed_sync_status(self, temp_dir):
        """Features com diferentes sync_status devem todas ser exportadas."""
        mixed = [
            {**SAMPLE_FEATURES[0], "sync_status": "DOWNLOADED"},
            {**SAMPLE_FEATURES[1], "sync_status": "MODIFIED"},
            {**SAMPLE_FEATURES[2], "sync_status": "NEW"},
        ]
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, mixed)

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(source, dest)

        features = read_gpkg_features(dest)
        statuses = {f["_sync_status"] for f in features}
        assert statuses == {"DOWNLOADED", "MODIFIED", "NEW"}


class TestUploadZipCreation:
    """Testa criacao do ZIP para upload."""

    def test_zip_contains_gpkg(self, temp_dir):
        """ZIP deve conter upload.gpkg."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES)

        zip_path = os.path.join(temp_dir, "upload.zip")
        export_and_zip(source, zip_path)

        with zipfile.ZipFile(zip_path, "r") as zf:
            assert "upload.gpkg" in zf.namelist()

    def test_zip_gpkg_is_valid(self, temp_dir):
        """GPKG dentro do ZIP deve ser aberto pelo OGR."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES)

        zip_path = os.path.join(temp_dir, "upload.zip")
        export_and_zip(source, zip_path)

        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        gpkg_in_zip = os.path.join(extract_dir, "upload.gpkg")
        assert os.path.exists(gpkg_in_zip)

        features = read_gpkg_features(gpkg_in_zip)
        assert len(features) == 3

    def test_zip_gpkg_has_no_internal_fields(self, temp_dir):
        """GPKG no ZIP nao deve conter campos internos."""
        source = os.path.join(temp_dir, "source.gpkg")
        create_gpkg_v2_with_features(source, SAMPLE_FEATURES)

        zip_path = os.path.join(temp_dir, "upload.zip")
        export_and_zip(source, zip_path)

        extract_dir = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_dir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        field_names = read_gpkg_field_names(os.path.join(extract_dir, "upload.gpkg"))
        for f in INTERNAL_FIELDS:
            assert f not in field_names

    def test_zip_is_compressed(self, temp_dir):
        """ZIP deve usar compressao (menor que GPKG original)."""
        source = os.path.join(temp_dir, "source.gpkg")
        # Cria features suficientes para compressao ser notavel
        large_features = []
        for i in range(100):
            lon = -50 + i * 0.01
            wkt = (f"POLYGON (({lon} -15, {lon+0.01} -15, "
                   f"{lon+0.01} -14.99, {lon} -14.99, {lon} -15))")
            large_features.append({
                "id": i,
                "geometry_wkt": wkt,
                "attrs": {"idSeg": i, "areaHa": float(i), "grupo": "Teste", "consolidado": 0},
            })
        create_gpkg_v2_with_features(source, large_features)

        zip_path = os.path.join(temp_dir, "upload.zip")
        export_and_zip(source, zip_path)

        gpkg_size = os.path.getsize(source)
        zip_size = os.path.getsize(zip_path)
        # ZIP deve ser menor (compressao DEFLATE)
        assert zip_size < gpkg_size


class TestExportErrorHandling:
    """Testa cenarios de erro no export."""

    def test_invalid_source_raises(self, temp_dir):
        """Source invalido deve levantar excecao."""
        bad_path = os.path.join(temp_dir, "invalid.gpkg")
        with open(bad_path, "w") as f:
            f.write("not a gpkg")

        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        with pytest.raises(Exception):
            export_gpkg_for_upload(bad_path, dest)

    def test_nonexistent_source_raises(self, temp_dir):
        """Source inexistente deve levantar excecao."""
        dest = os.path.join(temp_dir, "export", "upload.gpkg")
        with pytest.raises(Exception):
            export_gpkg_for_upload(
                os.path.join(temp_dir, "nope.gpkg"), dest,
            )
