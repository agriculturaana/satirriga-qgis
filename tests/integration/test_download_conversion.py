"""Testes de integracao: conversao FlatGeobuf -> GPKG (logica do DownloadZonalTask).

Valida que a logica de conversao via GDAL/OGR (migrada de QgsVectorLayer)
preserva features, geometrias, atributos e adiciona campos sync V2.

Usa GDAL/OGR real — sem mocks de QGIS.
"""

import os
import tempfile
import shutil
from datetime import datetime, timezone

import pytest
from osgeo import ogr, osr

from .conftest import (
    create_fgb_with_features,
    create_gpkg_v2_with_features,
    read_gpkg_features,
    read_gpkg_field_names,
    read_gpkg_srs,
    SAMPLE_FEATURES,
    SAMPLE_POLYGONS,
)


# Constantes V2 replicadas do domain/services/gpkg_service.py
SYNC_FIELDS_V2 = [
    ("_original_fid", "INTEGER"),
    ("_sync_status", "TEXT"),
    ("_sync_timestamp", "TEXT"),
    ("_zonal_id", "INTEGER"),
    ("_edit_token", "TEXT"),
]


def convert_fgb_to_gpkg(fgb_path, gpkg_path, zonal_id, edit_token):
    """Replica a logica exata de conversao FGB->GPKG do DownloadZonalTask.run().

    Retorna (written_count, write_errors).
    """
    from osgeo import ogr, osr, gdal
    gdal.UseExceptions()

    src_ds = ogr.Open(fgb_path, 0)
    if src_ds is None:
        raise Exception(f"Falha ao abrir FlatGeobuf: {fgb_path}")

    src_lyr = src_ds.GetLayer(0)
    if src_lyr is None:
        src_ds = None
        raise Exception(f"FlatGeobuf sem layers: {fgb_path}")

    os.makedirs(os.path.dirname(gpkg_path), exist_ok=True)

    gpkg_drv = ogr.GetDriverByName("GPKG")
    if os.path.exists(gpkg_path):
        gpkg_drv.DeleteDataSource(gpkg_path)
    dst_ds = gpkg_drv.CreateDataSource(gpkg_path)
    if dst_ds is None:
        src_ds = None
        raise Exception(f"Erro ao criar GPKG: {gpkg_path}")

    src_srs = src_lyr.GetSpatialRef()
    if src_srs is None:
        src_srs = osr.SpatialReference()
        src_srs.ImportFromEPSG(4326)

    src_defn = src_lyr.GetLayerDefn()
    geom_type = src_lyr.GetGeomType()
    dst_lyr = dst_ds.CreateLayer(
        "zonal", srs=src_srs, geom_type=geom_type,
        options=["FID=fid"],
    )

    # Copia campos originais
    src_field_count = src_defn.GetFieldCount()
    for i in range(src_field_count):
        field_defn = src_defn.GetFieldDefn(i)
        dst_lyr.CreateField(field_defn)

    # Campos de sync V2
    ogr_type_map = {"INTEGER": ogr.OFTInteger, "TEXT": ogr.OFTString}
    for fname, ftype in SYNC_FIELDS_V2:
        fd = ogr.FieldDefn(fname, ogr_type_map.get(ftype, ogr.OFTString))
        dst_lyr.CreateField(fd)

    id_field_idx = src_defn.GetFieldIndex("id")
    total_features = src_lyr.GetFeatureCount()
    now_iso = datetime.now(timezone.utc).isoformat()
    dst_defn = dst_lyr.GetLayerDefn()

    written_count = 0
    write_errors = 0
    dst_lyr.StartTransaction()

    for i, src_feat in enumerate(src_lyr):
        dst_feat = ogr.Feature(dst_defn)
        geom = src_feat.GetGeometryRef()
        if geom is not None:
            dst_feat.SetGeometry(geom.Clone())

        for j in range(src_field_count):
            dst_feat.SetField(j, src_feat.GetField(j))

        original_fid = src_feat.GetField(id_field_idx) if id_field_idx >= 0 else src_feat.GetFID()
        dst_feat.SetField("_original_fid", original_fid)
        dst_feat.SetField("_sync_status", "DOWNLOADED")
        dst_feat.SetField("_sync_timestamp", now_iso)
        dst_feat.SetField("_zonal_id", zonal_id)
        dst_feat.SetField("_edit_token", edit_token)

        err = dst_lyr.CreateFeature(dst_feat)
        if err == ogr.OGRERR_NONE:
            written_count += 1
        else:
            write_errors += 1

    dst_lyr.CommitTransaction()
    src_ds = None
    dst_ds = None

    return written_count, write_errors


def validate_existing_gpkg(gpkg_path, expected_count):
    """Replica a logica de _validate_existing_gpkg do DownloadZonalTask."""
    if not os.path.exists(gpkg_path):
        return False
    try:
        ds = ogr.Open(gpkg_path, 0)
        if ds is None:
            return False
        lyr = ds.GetLayer(0)
        if lyr is None:
            ds = None
            return False
        actual = lyr.GetFeatureCount()
        if actual == 0 and expected_count > 0:
            ds = None
            return False
        feat = lyr.GetNextFeature()
        if feat is not None and feat.GetGeometryRef() is None:
            ds = None
            return False
        ds = None
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tests: FGB -> GPKG conversion
# ---------------------------------------------------------------------------

class TestFgbToGpkgConversion:
    """Testa conversao FlatGeobuf -> GeoPackage com campos V2."""

    def test_basic_conversion_creates_valid_gpkg(self, temp_dir):
        """FGB com 3 features deve gerar GPKG valido com 3 features."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES)

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        written, errors = convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok-abc")

        assert written == 3
        assert errors == 0
        assert os.path.exists(gpkg_path)

        features = read_gpkg_features(gpkg_path)
        assert len(features) == 3

    def test_all_features_have_geometry(self, temp_dir):
        """Todas as features devem preservar geometria."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES)

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        features = read_gpkg_features(gpkg_path)
        for feat in features:
            assert feat["has_geometry"] is True
            assert feat["geom_type"] == ogr.wkbPolygon

    def test_original_attributes_preserved(self, temp_dir):
        """Campos originais (id, idSeg, areaHa, grupo, consolidado) preservados."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES)

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        features = read_gpkg_features(gpkg_path)

        f1 = features[0]
        assert f1["id"] == 101
        assert f1["idSeg"] == 1
        assert abs(f1["areaHa"] - 150.5) < 0.01
        assert f1["grupo"] == "Irrigacao"
        assert f1["consolidado"] == 1

        f2 = features[1]
        assert f2["id"] == 102
        assert f2["idSeg"] == 2
        assert abs(f2["areaHa"] - 200.3) < 0.01
        assert f2["grupo"] == "Sequeiro"
        assert f2["consolidado"] == 0

        f3 = features[2]
        assert f3["id"] == 103
        assert f3["idSeg"] == 3
        assert abs(f3["areaHa"] - 75.0) < 0.01
        assert f3["grupo"] == "Irrigacao"
        assert f3["consolidado"] == 1

    def test_sync_fields_v2_added(self, temp_dir):
        """GPKG deve conter todos os campos V2 de sync."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES[:1])

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        field_names = read_gpkg_field_names(gpkg_path)
        for fname, _ in SYNC_FIELDS_V2:
            assert fname in field_names, f"Campo V2 '{fname}' ausente no GPKG"

    def test_sync_status_is_downloaded(self, temp_dir):
        """Todas as features devem ter _sync_status = DOWNLOADED."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES)

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        features = read_gpkg_features(gpkg_path)
        for feat in features:
            assert feat["_sync_status"] == "DOWNLOADED"

    def test_original_fid_populated_from_id_field(self, temp_dir):
        """_original_fid deve ser preenchido a partir do campo 'id' do FGB."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES)

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        features = read_gpkg_features(gpkg_path)
        assert features[0]["_original_fid"] == 101
        assert features[1]["_original_fid"] == 102
        assert features[2]["_original_fid"] == 103

    def test_zonal_id_set_correctly(self, temp_dir):
        """_zonal_id deve corresponder ao zonal_id passado."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES[:1])

        gpkg_path = os.path.join(temp_dir, "output", "zonal_99.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 99, "tok")

        features = read_gpkg_features(gpkg_path)
        assert features[0]["_zonal_id"] == 99

    def test_edit_token_set(self, temp_dir):
        """_edit_token deve ser preenchido corretamente."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES[:1])

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "my-token-xyz")

        features = read_gpkg_features(gpkg_path)
        assert features[0]["_edit_token"] == "my-token-xyz"

    def test_crs_is_4326(self, temp_dir):
        """CRS do GPKG gerado deve ser EPSG:4326."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES[:1])

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        assert read_gpkg_srs(gpkg_path) == "4326"

    def test_empty_fgb_produces_empty_gpkg(self, temp_dir):
        """FGB com 0 features deve gerar GPKG vazio (sem erro)."""
        fgb_path = os.path.join(temp_dir, "empty.fgb")
        create_fgb_with_features(fgb_path, [])

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        written, errors = convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        assert written == 0
        assert errors == 0
        assert os.path.exists(gpkg_path)

        features = read_gpkg_features(gpkg_path)
        assert len(features) == 0

    def test_geometry_coordinates_preserved(self, temp_dir):
        """Coordenadas das geometrias devem ser preservadas com precisao."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES[:1])

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        features = read_gpkg_features(gpkg_path)
        geom = ogr.CreateGeometryFromWkt(features[0]["geom_wkt"])
        ring = geom.GetGeometryRef(0)

        assert ring.GetPointCount() == 5  # poligono fechado
        assert abs(ring.GetX(0) - (-45.0)) < 1e-6
        assert abs(ring.GetY(0) - (-15.0)) < 1e-6
        assert abs(ring.GetX(1) - (-44.0)) < 1e-6
        assert abs(ring.GetY(1) - (-15.0)) < 1e-6

    def test_large_feature_set(self, temp_dir):
        """Conversao de 500 features deve funcionar corretamente."""
        features = []
        for i in range(500):
            lon = -50.0 + (i % 50) * 0.1
            lat = -20.0 + (i // 50) * 0.1
            wkt = (
                f"POLYGON (({lon} {lat}, {lon+0.1} {lat}, "
                f"{lon+0.1} {lat+0.1}, {lon} {lat+0.1}, {lon} {lat}))"
            )
            features.append({
                "id": 1000 + i,
                "geometry_wkt": wkt,
                "attrs": {"idSeg": i, "areaHa": 10.0 + i, "grupo": "Teste", "consolidado": 0},
            })

        fgb_path = os.path.join(temp_dir, "large.fgb")
        create_fgb_with_features(fgb_path, features)

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        written, errors = convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        assert written == 500
        assert errors == 0

        result = read_gpkg_features(gpkg_path)
        assert len(result) == 500

    def test_overwrites_existing_gpkg(self, temp_dir):
        """Se GPKG ja existe, deve ser substituido."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES[:1])

        gpkg_dir = os.path.join(temp_dir, "output")
        os.makedirs(gpkg_dir)
        gpkg_path = os.path.join(gpkg_dir, "zonal_42.gpkg")

        # Cria GPKG pre-existente com 3 features
        create_gpkg_v2_with_features(gpkg_path, SAMPLE_FEATURES)

        # Conversao deve sobrescrever com 1 feature
        written, _ = convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        assert written == 1
        features = read_gpkg_features(gpkg_path)
        assert len(features) == 1

    def test_fgb_with_extra_fields_preserved(self, temp_dir):
        """Campos adicionais no FGB devem ser copiados para o GPKG."""
        features = [{
            "id": 200,
            "geometry_wkt": SAMPLE_POLYGONS[0],
            "attrs": {"idSeg": 1, "areaHa": 50.0, "grupo": "Extra", "consolidado": 0},
        }]

        fgb_path = os.path.join(temp_dir, "extra.fgb")
        create_fgb_with_features(
            fgb_path, features,
            extra_fields=[("custom_field", ogr.OFTString)],
        )

        # Seta valor do campo extra
        ds = ogr.Open(fgb_path, 1)
        lyr = ds.GetLayer(0)
        feat = lyr.GetNextFeature()
        feat.SetField("custom_field", "valor_extra")
        lyr.SetFeature(feat)
        ds = None

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        field_names = read_gpkg_field_names(gpkg_path)
        assert "custom_field" in field_names

        result = read_gpkg_features(gpkg_path)
        assert result[0]["custom_field"] == "valor_extra"

    def test_sync_timestamp_is_iso_format(self, temp_dir):
        """_sync_timestamp deve estar em formato ISO 8601 com timezone."""
        fgb_path = os.path.join(temp_dir, "test.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES[:1])

        gpkg_path = os.path.join(temp_dir, "output", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        features = read_gpkg_features(gpkg_path)
        ts = features[0]["_sync_timestamp"]
        assert ts is not None
        assert "T" in ts
        assert "+" in ts or "Z" in ts


# ---------------------------------------------------------------------------
# Tests: _validate_existing_gpkg
# ---------------------------------------------------------------------------

class TestValidateExistingGpkg:
    """Testa validacao de GPKG existente para cache."""

    def test_valid_gpkg_returns_true(self, temp_dir):
        gpkg_path = os.path.join(temp_dir, "valid.gpkg")
        create_gpkg_v2_with_features(gpkg_path, SAMPLE_FEATURES)
        assert validate_existing_gpkg(gpkg_path, expected_count=3) is True

    def test_nonexistent_returns_false(self, temp_dir):
        assert validate_existing_gpkg(
            os.path.join(temp_dir, "nope.gpkg"), expected_count=1,
        ) is False

    def test_empty_gpkg_with_expected_count_returns_false(self, temp_dir):
        gpkg_path = os.path.join(temp_dir, "empty.gpkg")
        create_gpkg_v2_with_features(gpkg_path, [])
        assert validate_existing_gpkg(gpkg_path, expected_count=5) is False

    def test_empty_gpkg_with_zero_expected_returns_true(self, temp_dir):
        gpkg_path = os.path.join(temp_dir, "empty.gpkg")
        create_gpkg_v2_with_features(gpkg_path, [])
        assert validate_existing_gpkg(gpkg_path, expected_count=0) is True

    def test_corrupted_file_returns_false(self, temp_dir):
        bad_path = os.path.join(temp_dir, "corrupted.gpkg")
        with open(bad_path, "wb") as f:
            f.write(b"not a real gpkg file content")
        assert validate_existing_gpkg(bad_path, expected_count=1) is False

    def test_feature_without_geometry_returns_false(self, temp_dir):
        gpkg_path = os.path.join(temp_dir, "no_geom.gpkg")

        drv = ogr.GetDriverByName("GPKG")
        ds = drv.CreateDataSource(gpkg_path)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        lyr = ds.CreateLayer("test", srs=srs, geom_type=ogr.wkbPolygon)
        lyr.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))

        defn = lyr.GetLayerDefn()
        feat = ogr.Feature(defn)
        feat.SetField("id", 1)
        # Sem geometria
        lyr.CreateFeature(feat)
        ds = None

        assert validate_existing_gpkg(gpkg_path, expected_count=1) is False

    def test_gpkg_with_valid_geometry_returns_true(self, temp_dir):
        gpkg_path = os.path.join(temp_dir, "with_geom.gpkg")
        create_gpkg_v2_with_features(gpkg_path, SAMPLE_FEATURES[:1])
        assert validate_existing_gpkg(gpkg_path, expected_count=1) is True
