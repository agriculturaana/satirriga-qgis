"""Testes unitarios para domain.models.pixel_indexes."""

import math

from domain.models.pixel_indexes import SceneIndexes, parse_scene_list


class TestSceneIndexesFromDict:
    def test_parses_complete_payload(self):
        data = {
            "id_imagem": "S2A_X",
            "tile": "24MXT",
            "data_formatada": "22/10/2025",
            "ndvi": 0.456,
            "savi": 0.401,
            "evi": 0.512,
            "ndwi": 0.234,
            "mndwi": 0.189,
            "albedo": 0.23,
        }
        scene = SceneIndexes.from_dict(data)
        assert scene.id_imagem == "S2A_X"
        assert scene.tile == "24MXT"
        assert scene.data_formatada == "22/10/2025"
        assert scene.ndvi == 0.456
        assert scene.albedo == 0.23

    def test_missing_fields_become_none(self):
        data = {"id_imagem": "X", "tile": "T", "data_formatada": "10/10/2025"}
        scene = SceneIndexes.from_dict(data)
        assert scene.ndvi is None
        assert scene.savi is None
        assert scene.albedo is None

    def test_null_values_become_none(self):
        scene = SceneIndexes.from_dict({"ndvi": None, "evi": "null"})
        assert scene.ndvi is None
        assert scene.evi is None

    def test_string_numbers_are_coerced(self):
        scene = SceneIndexes.from_dict({"ndvi": "0.5"})
        assert scene.ndvi == 0.5

    def test_nan_becomes_none(self):
        scene = SceneIndexes.from_dict({"ndvi": float("nan")})
        assert scene.ndvi is None

    def test_data_field_fallback(self):
        # API legado pode mandar "data" em vez de "data_formatada"
        scene = SceneIndexes.from_dict({"data": "01/01/2024"})
        assert scene.data_formatada == "01/01/2024"

    def test_display_label_uses_date_and_tile(self):
        scene = SceneIndexes.from_dict({
            "id_imagem": "X", "tile": "24MXT", "data_formatada": "22/10/2025",
        })
        assert scene.display_label() == "22/10/2025 - 24MXT"

    def test_display_label_falls_back_to_id(self):
        scene = SceneIndexes.from_dict({"id_imagem": "X"})
        assert scene.display_label() == "X"


class TestParseSceneList:
    def test_handles_list(self):
        result = parse_scene_list([
            {"id_imagem": "A", "tile": "T1", "data_formatada": "01/01"},
            {"id_imagem": "B", "tile": "T2", "data_formatada": "02/01"},
        ])
        assert len(result) == 2
        assert result[0].id_imagem == "A"

    def test_wraps_single_dict(self):
        result = parse_scene_list({"id_imagem": "A"})
        assert len(result) == 1
        assert result[0].id_imagem == "A"

    def test_empty_list_returns_empty(self):
        assert parse_scene_list([]) == []

    def test_none_returns_empty(self):
        assert parse_scene_list(None) == []

    def test_string_input_returns_empty(self):
        assert parse_scene_list("invalido") == []

    def test_skips_non_dict_items(self):
        result = parse_scene_list([{"id_imagem": "A"}, "lixo", None])
        assert len(result) == 1
        assert result[0].id_imagem == "A"
