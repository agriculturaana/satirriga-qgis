"""Teste de integracao roundtrip: FGB -> GPKG -> editar -> export upload.

Simula o ciclo completo do usuario:
1. Download FlatGeobuf do servidor -> conversao para GPKG com campos V2
2. Edicao local (modificar geometria, alterar atributo, adicionar feature)
3. Export para upload (filtra campos internos, preserva dados do dominio)

Usa GDAL/OGR real — sem mocks de QGIS.
"""

import os

import pytest
from osgeo import ogr, osr

from .conftest import (
    create_fgb_with_features,
    read_gpkg_features,
    read_gpkg_field_names,
    SAMPLE_FEATURES,
    SAMPLE_POLYGONS,
)

# Reutiliza funcoes de conversao dos outros testes
from .test_download_conversion import convert_fgb_to_gpkg
from .test_upload_export import export_gpkg_for_upload, INTERNAL_FIELDS


def simulate_local_edits(gpkg_path):
    """Simula edicoes que o usuario faria no QGIS.

    1. Modifica geometria da feature id=101
    2. Altera atributo 'grupo' da feature id=102
    3. Adiciona uma nova feature (id=0, _sync_status=NEW)
    """
    ds = ogr.Open(gpkg_path, 1)  # read-write
    lyr = ds.GetLayer(0)
    defn = lyr.GetLayerDefn()

    # 1. Modifica geometria da feature 101
    lyr.SetAttributeFilter("id = 101")
    feat = lyr.GetNextFeature()
    if feat:
        new_geom = ogr.CreateGeometryFromWkt(
            "POLYGON ((-45.1 -15.1, -43.9 -15.1, -43.9 -13.9, -45.1 -13.9, -45.1 -15.1))"
        )
        feat.SetGeometry(new_geom)
        feat.SetField("_sync_status", "MODIFIED")
        lyr.SetFeature(feat)

    # 2. Altera atributo da feature 102
    lyr.SetAttributeFilter("id = 102")
    feat = lyr.GetNextFeature()
    if feat:
        feat.SetField("grupo", "Irrigacao_Modificado")
        feat.SetField("_sync_status", "MODIFIED")
        lyr.SetFeature(feat)

    # 3. Adiciona nova feature
    lyr.SetAttributeFilter(None)
    new_feat = ogr.Feature(defn)
    new_geom = ogr.CreateGeometryFromWkt(
        "POLYGON ((-48.0 -18.0, -47.0 -18.0, -47.0 -17.0, -48.0 -17.0, -48.0 -18.0))"
    )
    new_feat.SetGeometry(new_geom)
    new_feat.SetField("id", 0)
    new_feat.SetField("idSeg", 99)
    new_feat.SetField("areaHa", 300.0)
    new_feat.SetField("grupo", "Nova_Irrigacao")
    new_feat.SetField("consolidado", 0)
    new_feat.SetField("_original_fid", 0)
    new_feat.SetField("_sync_status", "NEW")
    new_feat.SetField("_sync_timestamp", "2026-02-22T10:00:00+00:00")
    new_feat.SetField("_zonal_id", 42)
    new_feat.SetField("_edit_token", "tok-roundtrip")
    lyr.CreateFeature(new_feat)

    ds = None  # flush


class TestDownloadEditUploadRoundtrip:
    """Ciclo completo: download -> edicao local -> upload."""

    def test_full_roundtrip(self, temp_dir):
        """Download 3 features, edita 2, adiciona 1, upload 4 features."""
        # --- STEP 1: FGB -> GPKG (simula download) ---
        fgb_path = os.path.join(temp_dir, "server.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES)

        gpkg_path = os.path.join(temp_dir, "zonal_42", "zonal_42.gpkg")
        written, errors = convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok-rt")

        assert written == 3
        assert errors == 0

        # Verifica estado pos-download
        features_dl = read_gpkg_features(gpkg_path)
        assert len(features_dl) == 3
        assert all(f["_sync_status"] == "DOWNLOADED" for f in features_dl)

        # --- STEP 2: Simula edicoes locais ---
        simulate_local_edits(gpkg_path)

        features_edited = read_gpkg_features(gpkg_path)
        assert len(features_edited) == 4  # 3 originais + 1 nova

        # Verifica sync_status apos edicao
        status_map = {f["id"]: f["_sync_status"] for f in features_edited}
        assert status_map[101] == "MODIFIED"
        assert status_map[102] == "MODIFIED"
        assert status_map[103] == "DOWNLOADED"  # nao editada
        assert status_map[0] == "NEW"  # nova feature

        # --- STEP 3: Export para upload ---
        export_path = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(gpkg_path, export_path)

        export_features = read_gpkg_features(export_path)
        assert len(export_features) == 4

        # --- STEP 4: Validacoes do export ---
        export_fields = read_gpkg_field_names(export_path)

        # Campos internos removidos
        for f in INTERNAL_FIELDS:
            assert f not in export_fields

        # Campos preservados
        assert "_original_fid" in export_fields
        assert "_sync_status" in export_fields
        assert "id" in export_fields
        assert "grupo" in export_fields
        assert "areaHa" in export_fields

        # Atributo modificado preservado
        f102 = next(f for f in export_features if f["id"] == 102)
        assert f102["grupo"] == "Irrigacao_Modificado"
        assert f102["_sync_status"] == "MODIFIED"

        # Nova feature presente
        f_new = next(f for f in export_features if f["id"] == 0)
        assert f_new["_sync_status"] == "NEW"
        assert f_new["grupo"] == "Nova_Irrigacao"
        assert abs(f_new["areaHa"] - 300.0) < 0.01

        # Geometria modificada preservada
        f101 = next(f for f in export_features if f["id"] == 101)
        assert f101["has_geometry"] is True
        geom = ogr.CreateGeometryFromWkt(f101["geom_wkt"])
        ring = geom.GetGeometryRef(0)
        assert abs(ring.GetX(0) - (-45.1)) < 1e-6

        # Feature nao editada preservada
        f103 = next(f for f in export_features if f["id"] == 103)
        assert f103["_sync_status"] == "DOWNLOADED"
        assert f103["grupo"] == "Irrigacao"

    def test_roundtrip_preserves_all_original_fids(self, temp_dir):
        """_original_fid deve ser preservado do download ate o upload."""
        fgb_path = os.path.join(temp_dir, "server.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES)

        gpkg_path = os.path.join(temp_dir, "zonal_42", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        # Verifica _original_fid apos download
        dl_fids = {f["_original_fid"] for f in read_gpkg_features(gpkg_path)}
        assert dl_fids == {101, 102, 103}

        # Export (sem edicoes)
        export_path = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(gpkg_path, export_path)

        # Verifica _original_fid preservado
        export_fids = {f["_original_fid"] for f in read_gpkg_features(export_path)}
        assert export_fids == dl_fids

    def test_roundtrip_no_data_loss(self, temp_dir):
        """Nenhum dado (atributo ou geometria) deve ser perdido no ciclo."""
        fgb_path = os.path.join(temp_dir, "server.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES)

        gpkg_path = os.path.join(temp_dir, "zonal_42", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        # Export direto (sem edicoes)
        export_path = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(gpkg_path, export_path)

        export_features = read_gpkg_features(export_path)
        assert len(export_features) == 3

        # Atributos do dominio preservados
        for i, expected in enumerate(SAMPLE_FEATURES):
            actual = export_features[i]
            assert actual["id"] == expected["id"]
            assert actual["has_geometry"] is True
            for attr_name, attr_val in expected["attrs"].items():
                if isinstance(attr_val, float):
                    assert abs(actual[attr_name] - attr_val) < 0.01
                else:
                    assert actual[attr_name] == attr_val

    def test_roundtrip_large_dataset(self, temp_dir):
        """Roundtrip com 200 features deve preservar todos os dados."""
        features = []
        for i in range(200):
            lon = -50.0 + (i % 20) * 0.1
            lat = -20.0 + (i // 20) * 0.1
            wkt = (
                f"POLYGON (({lon} {lat}, {lon+0.1} {lat}, "
                f"{lon+0.1} {lat+0.1}, {lon} {lat+0.1}, {lon} {lat}))"
            )
            features.append({
                "id": 2000 + i,
                "geometry_wkt": wkt,
                "attrs": {"idSeg": i, "areaHa": 10.0 + i * 0.5,
                          "grupo": f"Grupo_{i % 5}", "consolidado": i % 2},
            })

        fgb_path = os.path.join(temp_dir, "large.fgb")
        create_fgb_with_features(fgb_path, features)

        gpkg_path = os.path.join(temp_dir, "zonal_42", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        export_path = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(gpkg_path, export_path)

        export_features = read_gpkg_features(export_path)
        assert len(export_features) == 200

        # Verifica que todos os IDs originais estao presentes
        exported_ids = {f["id"] for f in export_features}
        expected_ids = {2000 + i for i in range(200)}
        assert exported_ids == expected_ids
        assert all(f["has_geometry"] for f in export_features)

    def test_roundtrip_field_order_consistent(self, temp_dir):
        """Campos do dominio devem manter ordem coerente no roundtrip."""
        fgb_path = os.path.join(temp_dir, "server.fgb")
        create_fgb_with_features(fgb_path, SAMPLE_FEATURES[:1])

        gpkg_path = os.path.join(temp_dir, "zonal_42", "zonal_42.gpkg")
        convert_fgb_to_gpkg(fgb_path, gpkg_path, 42, "tok")

        dl_fields = read_gpkg_field_names(gpkg_path)

        export_path = os.path.join(temp_dir, "export", "upload.gpkg")
        export_gpkg_for_upload(gpkg_path, export_path)

        export_fields = read_gpkg_field_names(export_path)

        # Campos do dominio devem estar na mesma ordem relativa
        domain_fields = ["id", "idSeg", "areaHa", "grupo", "consolidado"]
        dl_domain = [f for f in dl_fields if f in domain_fields]
        export_domain = [f for f in export_fields if f in domain_fields]
        assert dl_domain == export_domain
