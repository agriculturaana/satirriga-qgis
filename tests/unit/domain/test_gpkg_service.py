"""Testes unitarios para gpkg_service — funcoes que nao dependem de QGIS."""

import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Mock QgsApplication antes de importar gpkg_service
with patch.dict("sys.modules", {
    "qgis": MagicMock(),
    "qgis.core": MagicMock(),
}):
    from domain.services.gpkg_service import (
        gpkg_path,
        gpkg_path_for_zonal,
        sidecar_path,
        write_sidecar,
        read_sidecar,
        layer_group_name,
        layer_name,
        list_local_gpkgs,
        SYNC_FIELDS,
        SYNC_FIELDS_V2,
        SIDECAR_FILENAME,
    )


class TestSyncFields:
    def test_sync_fields_v1_exist(self):
        field_names = [f[0] for f in SYNC_FIELDS]
        assert "_original_fid" in field_names
        assert "_sync_status" in field_names
        assert "_sync_timestamp" in field_names
        assert "_mapeamento_id" in field_names
        assert "_metodo_id" in field_names

    def test_sync_fields_v1_types(self):
        types = {f[0]: f[1] for f in SYNC_FIELDS}
        assert types["_original_fid"] == "INTEGER"
        assert types["_sync_status"] == "TEXT"
        assert types["_sync_timestamp"] == "TEXT"
        assert types["_mapeamento_id"] == "INTEGER"
        assert types["_metodo_id"] == "INTEGER"

    def test_sync_fields_v2_exist(self):
        field_names = [f[0] for f in SYNC_FIELDS_V2]
        assert "_original_fid" in field_names
        assert "_sync_status" in field_names
        assert "_sync_timestamp" in field_names
        assert "_zonal_id" in field_names
        assert "_edit_token" in field_names

    def test_sync_fields_v2_types(self):
        types = {f[0]: f[1] for f in SYNC_FIELDS_V2}
        assert types["_original_fid"] == "INTEGER"
        assert types["_zonal_id"] == "INTEGER"
        assert types["_edit_token"] == "TEXT"

    def test_v1_and_v2_differ(self):
        """V1 e V2 devem ter campos diferentes (mapeamento/metodo vs zonal/token)."""
        v1_names = {f[0] for f in SYNC_FIELDS}
        v2_names = {f[0] for f in SYNC_FIELDS_V2}
        assert "_mapeamento_id" in v1_names
        assert "_mapeamento_id" not in v2_names
        assert "_zonal_id" in v2_names
        assert "_zonal_id" not in v1_names

    def test_sidecar_filename_constant(self):
        assert SIDECAR_FILENAME == ".satirriga.json"


class TestGpkgPath:
    def test_gpkg_path_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = gpkg_path(tmpdir, 42, 10)
            expected = os.path.join(tmpdir, "mapeamento_42", "metodo_10.gpkg")
            assert result == expected

    def test_gpkg_path_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = gpkg_path(tmpdir, 1, 1)
            assert os.path.isdir(os.path.join(tmpdir, "mapeamento_1"))


class TestGpkgPathForZonal:
    def test_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = gpkg_path_for_zonal(tmpdir, 99)
            expected = os.path.join(tmpdir, "zonal_99", "zonal_99.gpkg")
            assert result == expected

    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gpkg_path_for_zonal(tmpdir, 42)
            assert os.path.isdir(os.path.join(tmpdir, "zonal_42"))


class TestSidecarPath:
    def test_sidecar_path_format(self):
        result = sidecar_path("/data/zonal_99/zonal_99.gpkg")
        assert result == "/data/zonal_99/.satirriga.json"

    def test_sidecar_path_v1(self):
        result = sidecar_path("/data/mapeamento_1/metodo_5.gpkg")
        assert result == "/data/mapeamento_1/.satirriga.json"


class TestWriteReadSidecar:
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gpkg = os.path.join(tmpdir, "test.gpkg")
            data = {
                "zonalId": 42,
                "editToken": "tok-123",
                "zonalVersion": 5,
                "snapshotHash": "abc",
            }
            write_sidecar(gpkg, data)

            result = read_sidecar(gpkg)
            assert result["zonalId"] == 42
            assert result["editToken"] == "tok-123"
            assert result["zonalVersion"] == 5

    def test_read_nonexistent(self):
        result = read_sidecar("/nonexistent/path/file.gpkg")
        assert result == {}

    def test_read_corrupted_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sc = os.path.join(tmpdir, SIDECAR_FILENAME)
            with open(sc, "w") as f:
                f.write("not valid json {{{")

            gpkg = os.path.join(tmpdir, "test.gpkg")
            result = read_sidecar(gpkg)
            assert result == {}

    def test_write_overwrites(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gpkg = os.path.join(tmpdir, "test.gpkg")
            write_sidecar(gpkg, {"version": 1})
            write_sidecar(gpkg, {"version": 2})

            result = read_sidecar(gpkg)
            assert result["version"] == 2

    def test_write_unicode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gpkg = os.path.join(tmpdir, "test.gpkg")
            write_sidecar(gpkg, {"descricao": "Zonal Cerrado — 2024"})

            result = read_sidecar(gpkg)
            assert result["descricao"] == "Zonal Cerrado — 2024"


class TestLayerNames:
    def test_layer_group_name(self):
        assert layer_group_name("Cerrado 2024") == "SatIrriga / Cerrado 2024"

    def test_layer_name(self):
        assert layer_name("RANDOM_FOREST") == "RANDOM_FOREST"


class TestListLocalGpkgs:
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = list_local_gpkgs(tmpdir)
            assert result == []

    def test_nonexistent_dir(self):
        result = list_local_gpkgs("/nonexistent/path")
        assert result == []

    def test_finds_v1_gpkg_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m_dir = os.path.join(tmpdir, "mapeamento_42")
            os.makedirs(m_dir)
            gpkg_file = os.path.join(m_dir, "metodo_10.gpkg")
            with open(gpkg_file, "w") as f:
                f.write("fake gpkg content")

            result = list_local_gpkgs(tmpdir)
            assert len(result) == 1
            assert result[0]["mapeamento_id"] == 42
            assert result[0]["metodo_id"] == 10
            assert result[0]["type"] == "v1"
            assert result[0]["zonal_id"] is None
            assert result[0]["has_sidecar"] is False
            assert result[0]["path"] == gpkg_file
            assert result[0]["size_mb"] >= 0

    def test_finds_v2_gpkg_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            z_dir = os.path.join(tmpdir, "zonal_99")
            os.makedirs(z_dir)
            gpkg_file = os.path.join(z_dir, "zonal_99.gpkg")
            with open(gpkg_file, "w") as f:
                f.write("fake gpkg v2")

            result = list_local_gpkgs(tmpdir)
            assert len(result) == 1
            assert result[0]["zonal_id"] == 99
            assert result[0]["type"] == "v2"
            assert result[0]["has_sidecar"] is False
            assert result[0]["mapeamento_id"] is None
            assert result[0]["metodo_id"] is None

    def test_v2_with_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            z_dir = os.path.join(tmpdir, "zonal_42")
            os.makedirs(z_dir)
            gpkg_file = os.path.join(z_dir, "zonal_42.gpkg")
            with open(gpkg_file, "w") as f:
                f.write("fake gpkg v2")

            # Cria sidecar
            write_sidecar(gpkg_file, {"zonalId": 42})

            result = list_local_gpkgs(tmpdir)
            assert len(result) == 1
            assert result[0]["has_sidecar"] is True

    def test_mixed_v1_and_v2(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # V1
            m_dir = os.path.join(tmpdir, "mapeamento_1")
            os.makedirs(m_dir)
            with open(os.path.join(m_dir, "metodo_5.gpkg"), "w") as f:
                f.write("v1")

            # V2
            z_dir = os.path.join(tmpdir, "zonal_99")
            os.makedirs(z_dir)
            with open(os.path.join(z_dir, "zonal_99.gpkg"), "w") as f:
                f.write("v2")

            result = list_local_gpkgs(tmpdir)
            assert len(result) == 2

            types = {r["type"] for r in result}
            assert types == {"v1", "v2"}

            v1 = next(r for r in result if r["type"] == "v1")
            v2 = next(r for r in result if r["type"] == "v2")

            assert v1["mapeamento_id"] == 1
            assert v1["metodo_id"] == 5
            assert v2["zonal_id"] == 99

    def test_multiple_gpkgs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for m_id in (1, 2):
                m_dir = os.path.join(tmpdir, f"mapeamento_{m_id}")
                os.makedirs(m_dir)
                for met_id in (10, 20):
                    with open(os.path.join(m_dir, f"metodo_{met_id}.gpkg"), "w") as f:
                        f.write("x")

            result = list_local_gpkgs(tmpdir)
            assert len(result) == 4
            ids = {(r["mapeamento_id"], r["metodo_id"]) for r in result}
            assert (1, 10) in ids
            assert (2, 20) in ids

    def test_ignores_non_gpkg_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m_dir = os.path.join(tmpdir, "mapeamento_1")
            os.makedirs(m_dir)
            with open(os.path.join(m_dir, "data.csv"), "w") as f:
                f.write("a,b,c")
            with open(os.path.join(m_dir, "metodo_1.gpkg"), "w") as f:
                f.write("gpkg")

            result = list_local_gpkgs(tmpdir)
            assert len(result) == 1
