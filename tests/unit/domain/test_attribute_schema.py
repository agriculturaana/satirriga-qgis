"""Testes unitarios para attribute_schema — sem dependencia QGIS."""

import pytest

from domain.services.attribute_schema import (
    FieldWidgetType,
    FieldSpec,
    FieldGroup,
    INTERNAL_FIELDS,
    build_field_groups,
    get_field_spec,
    is_internal_field,
)


class TestBuildFieldGroups:
    def test_returns_six_groups(self):
        groups = build_field_groups()
        assert len(groups) == 6

    def test_group_names(self):
        groups = build_field_groups()
        names = [g.name for g in groups]
        assert names == [
            "identificacao", "medidas", "agricultura",
            "localizacao", "outorga", "metadados",
        ]

    def test_each_group_has_fields(self):
        groups = build_field_groups()
        for g in groups:
            assert len(g.fields) > 0, f"Grupo '{g.name}' sem campos"

    def test_groups_are_field_group_instances(self):
        groups = build_field_groups()
        for g in groups:
            assert isinstance(g, FieldGroup)
            for f in g.fields:
                assert isinstance(f, FieldSpec)

    def test_identificacao_has_classe_combo(self):
        groups = build_field_groups()
        ident = next(g for g in groups if g.name == "identificacao")
        classe = next(f for f in ident.fields if f.name == "classe")
        assert classe.widget_type == FieldWidgetType.COMBO
        assert len(classe.combo_values) > 0

    def test_medidas_fields_are_numeric(self):
        groups = build_field_groups()
        medidas = next(g for g in groups if g.name == "medidas")
        for f in medidas.fields:
            assert f.widget_type == FieldWidgetType.NUMERIC

    def test_metadados_has_date_fields(self):
        groups = build_field_groups()
        meta = next(g for g in groups if g.name == "metadados")
        date_fields = [f for f in meta.fields if f.widget_type == FieldWidgetType.DATE]
        assert len(date_fields) >= 2


class TestGetFieldSpec:
    def test_known_field(self):
        spec = get_field_spec("classe")
        assert spec.name == "classe"
        assert spec.widget_type == FieldWidgetType.COMBO
        assert spec.group == "identificacao"

    def test_id_field_is_read_only(self):
        spec = get_field_spec("id")
        assert spec.read_only is True
        assert spec.widget_type == FieldWidgetType.READ_ONLY

    def test_unknown_field_fallback(self):
        spec = get_field_spec("campo_novo_xyz")
        assert spec.name == "campo_novo_xyz"
        assert spec.widget_type == FieldWidgetType.TEXT
        assert spec.group == "outros"

    def test_observacao_is_multiline(self):
        spec = get_field_spec("observacao")
        assert spec.widget_type == FieldWidgetType.MULTILINE

    def test_area_ha_is_numeric(self):
        spec = get_field_spec("area_ha")
        assert spec.widget_type == FieldWidgetType.NUMERIC


class TestIsInternalField:
    def test_sync_status(self):
        assert is_internal_field("_sync_status") is True

    def test_sync_timestamp(self):
        assert is_internal_field("_sync_timestamp") is True

    def test_original_fid(self):
        assert is_internal_field("_original_fid") is True

    def test_zonal_id(self):
        assert is_internal_field("_zonal_id") is True

    def test_edit_token(self):
        assert is_internal_field("_edit_token") is True

    def test_normal_field(self):
        assert is_internal_field("classe") is False

    def test_unknown_underscore_prefix(self):
        assert is_internal_field("_qualquer_coisa") is True

    def test_internal_fields_set(self):
        assert "_sync_status" in INTERNAL_FIELDS
        assert "_sync_timestamp" in INTERNAL_FIELDS
        assert "_original_fid" in INTERNAL_FIELDS
