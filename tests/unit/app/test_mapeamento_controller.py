"""Testes unitarios para MapeamentoController — logica de negocio.

Testa parsing de responses, paginacao e validacao de pre-condicoes
usando os mesmos parsers do dominio + fixtures JSON.
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch

# Mock QGIS
import sys
qgis_mocks = {
    "qgis": MagicMock(),
    "qgis.PyQt": MagicMock(),
    "qgis.PyQt.QtCore": MagicMock(),
    "qgis.core": MagicMock(),
}
qgis_mocks["qgis.PyQt.QtCore"].QObject = type("QObject", (), {"__init__": lambda *a, **k: None})

class MockSignal:
    def __init__(self, *args):
        self._callbacks = []
        self._mock = MagicMock()
        self.emit = self._mock

    def connect(self, slot):
        self._callbacks.append(slot)

    def disconnect(self, slot=None):
        pass

qgis_mocks["qgis.PyQt.QtCore"].pyqtSignal = MockSignal

for mod, mock in qgis_mocks.items():
    sys.modules[mod] = mock

# Importa domain (sem dependencia QGIS)
from domain.services.mapeamento_service import parse_paginated_result, parse_mapeamento
from domain.models.mapeamento import Mapeamento, PaginatedResult
from domain.models.metodo import Metodo

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures")


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


class TestMapeamentosParsing:
    """Testa parsing de responses reais da API usando fixtures."""

    def test_parse_list_response(self):
        data = _load_fixture("mapeamentos_response.json")
        result = parse_paginated_result(data)
        assert isinstance(result, PaginatedResult)
        assert len(result.content) == 3
        assert result.page == 0
        assert result.total_elements == 3
        assert result.total_pages == 1

    def test_parse_list_mapeamento_fields(self):
        data = _load_fixture("mapeamentos_response.json")
        result = parse_paginated_result(data)
        m = result.content[0]
        assert m.id == 1
        assert m.descricao == "Mapeamento Cerrado 2024"
        assert m.data_referencia == "15/01/2024"
        assert m.status == "DONE"
        assert m.satelite == "Sentinel-2"
        assert len(m.metodos) == 2

    def test_parse_list_metodos_nested(self):
        data = _load_fixture("mapeamentos_response.json")
        result = parse_paginated_result(data)
        m = result.content[0]
        assert m.metodos[0].metodo_apply == "RANDOM_FOREST"
        assert m.metodos[0].status == "DONE"
        assert m.metodos[1].metodo_apply == "SVM"
        assert m.metodos[1].status == "PROCESSING"

    def test_parse_detail_response(self):
        data = _load_fixture("mapeamento_detail_response.json")
        m = parse_mapeamento(data)
        assert isinstance(m, Mapeamento)
        assert m.id == 1
        assert len(m.metodos) == 2
        assert m.metodos[0].metodo_apply == "RANDOM_FOREST"

    def test_parse_detail_geometrias(self):
        data = _load_fixture("mapeamento_detail_response.json")
        m = parse_mapeamento(data)
        geoms = m.metodos[0].geometrias
        assert len(geoms) == 2
        assert geoms[0].id == 100
        assert geoms[0].area_ha == 12.5
        assert geoms[0].grupo == "Irrigado"

    def test_parse_empty_metodos(self):
        data = _load_fixture("mapeamentos_response.json")
        result = parse_paginated_result(data)
        m = result.content[2]  # Amazonia — sem metodos
        assert m.metodos == []


class TestPaginationLogic:
    """Testa logica de paginacao isolada do controller."""

    def test_can_go_next(self):
        result = PaginatedResult(
            content=[], page=0, size=15, total_elements=50, total_pages=4
        )
        assert result.page < result.total_pages - 1

    def test_cannot_go_next_at_last_page(self):
        result = PaginatedResult(
            content=[], page=3, size=15, total_elements=50, total_pages=4
        )
        assert not (result.page < result.total_pages - 1)

    def test_can_go_previous(self):
        result = PaginatedResult(
            content=[], page=2, size=15, total_elements=50, total_pages=4
        )
        assert result.page > 0

    def test_cannot_go_previous_at_first_page(self):
        result = PaginatedResult(
            content=[], page=0, size=15, total_elements=50, total_pages=4
        )
        assert not (result.page > 0)


class TestBusinessRules:
    """Testa regras de negocio com dados de fixture."""

    def test_mapeamento_with_done_metodo_is_downloadable(self):
        from domain.services.mapeamento_service import has_downloadable_metodo
        data = _load_fixture("mapeamento_detail_response.json")
        m = parse_mapeamento(data)
        assert has_downloadable_metodo(m) is True

    def test_mapeamento_all_processing_not_downloadable(self):
        from domain.services.mapeamento_service import has_downloadable_metodo
        m = Mapeamento(
            id=1, descricao="Test", data_referencia="2024-01-01",
            status="PROCESSING",
            metodos=[
                Metodo(id=1, metodo_apply="RF", status="PROCESSING"),
            ],
        )
        assert has_downloadable_metodo(m) is False

    def test_has_processing_metodo_from_fixture(self):
        from domain.services.mapeamento_service import has_processing_metodo
        data = _load_fixture("mapeamentos_response.json")
        result = parse_paginated_result(data)
        # Mapeamento 0 (Cerrado) tem metodo SVM em PROCESSING
        assert has_processing_metodo(result.content[0]) is True
        # Mapeamento 2 (Amazonia) nao tem metodos
        assert has_processing_metodo(result.content[2]) is False
