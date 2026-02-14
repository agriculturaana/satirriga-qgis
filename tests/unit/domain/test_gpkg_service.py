"""Testes unitarios para gpkg_service — funcoes que nao dependem de QGIS."""

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
        layer_group_name,
        layer_name,
        list_local_gpkgs,
        SYNC_FIELDS,
    )


class TestSyncFields:
    def test_sync_fields_exist(self):
        field_names = [f[0] for f in SYNC_FIELDS]
        assert "_original_fid" in field_names
        assert "_sync_status" in field_names
        assert "_sync_timestamp" in field_names
        assert "_mapeamento_id" in field_names
        assert "_metodo_id" in field_names

    def test_sync_fields_types(self):
        types = {f[0]: f[1] for f in SYNC_FIELDS}
        assert types["_original_fid"] == "INTEGER"
        assert types["_sync_status"] == "TEXT"
        assert types["_sync_timestamp"] == "TEXT"
        assert types["_mapeamento_id"] == "INTEGER"
        assert types["_metodo_id"] == "INTEGER"


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

    def test_finds_gpkg_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Cria estrutura de pastas simulando download
            m_dir = os.path.join(tmpdir, "mapeamento_42")
            os.makedirs(m_dir)
            gpkg_file = os.path.join(m_dir, "metodo_10.gpkg")
            with open(gpkg_file, "w") as f:
                f.write("fake gpkg content")

            result = list_local_gpkgs(tmpdir)
            assert len(result) == 1
            assert result[0]["mapeamento_id"] == 42
            assert result[0]["metodo_id"] == 10
            assert result[0]["path"] == gpkg_file
            assert result[0]["size_mb"] >= 0

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
