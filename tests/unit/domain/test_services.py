"""Testes unitarios para domain services — sem dependencia QGIS."""

import pytest

from domain.models.mapeamento import Mapeamento
from domain.models.metodo import Metodo
from domain.services.mapeamento_service import (
    parse_mapeamento,
    parse_paginated_result,
    has_downloadable_metodo,
    has_processing_metodo,
)


class TestMapeamentoService:
    def test_parse_mapeamento(self):
        data = {
            "id": 1,
            "descricao": "Test",
            "dataReferencia": "2024-01-01",
            "status": "DONE",
        }
        m = parse_mapeamento(data)
        assert isinstance(m, Mapeamento)
        assert m.id == 1

    def test_parse_paginated_result(self):
        data = {
            "content": [
                {"id": 1, "descricao": "M1", "dataReferencia": "2024-01-01", "status": "DONE"},
            ],
            "number": 0,
            "size": 15,
            "totalElements": 1,
            "totalPages": 1,
        }
        result = parse_paginated_result(data)
        assert len(result.content) == 1
        assert result.total_elements == 1

    def test_has_downloadable_metodo(self):
        m = Mapeamento(
            id=1, descricao="Test", data_referencia="2024-01-01", status="DONE",
            metodos=[
                Metodo(id=1, metodo_apply="RF", status="DONE"),
                Metodo(id=2, metodo_apply="SVM", status="PROCESSING"),
            ],
        )
        assert has_downloadable_metodo(m) is True

    def test_has_no_downloadable_metodo(self):
        m = Mapeamento(
            id=1, descricao="Test", data_referencia="2024-01-01", status="PROCESSING",
            metodos=[
                Metodo(id=1, metodo_apply="RF", status="PROCESSING"),
            ],
        )
        assert has_downloadable_metodo(m) is False

    def test_has_processing_metodo(self):
        m = Mapeamento(
            id=1, descricao="Test", data_referencia="2024-01-01", status="PROCESSING",
            metodos=[
                Metodo(id=1, metodo_apply="RF", status="PROCESSING"),
                Metodo(id=2, metodo_apply="SVM", status="DONE"),
            ],
        )
        assert has_processing_metodo(m) is True
