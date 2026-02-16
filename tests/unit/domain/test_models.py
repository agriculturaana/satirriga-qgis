"""Testes unitarios para domain models — sem dependencia QGIS."""

import pytest

from domain.models.enums import JobStatusEnum, MetodoMapeamentoEnum, SyncStatusEnum
from domain.models.user import UserInfo
from domain.models.mapeamento import Mapeamento, PaginatedResult
from domain.models.metodo import Metodo, MetodoGeometria
from domain.models.zonal import Zonal, ZonalGeometria


class TestJobStatusEnum:
    def test_colors(self):
        assert JobStatusEnum.DONE.color == "#4CAF50"
        assert JobStatusEnum.PROCESSING.color == "#FF9800"
        assert JobStatusEnum.FAILED.color == "#F44336"

    def test_labels(self):
        assert JobStatusEnum.DONE.label == "Concluido"
        assert JobStatusEnum.PROCESSING.label == "Processando"


class TestUserInfo:
    def test_from_jwt_claims_with_resource_access(self):
        claims = {
            "sub": "user-123",
            "name": "Tharles Andrade",
            "email": "tharles@example.com",
            "preferred_username": "tharles",
            "exp": 1700000000,
            "realm_access": {"roles": ["planet-tiles", "planet-mosaicos"]},
            "resource_access": {
                "sat-irriga": {
                    "roles": ["acesso", "homologar", "gerenciar-mascaras"]
                },
                "account": {
                    "roles": ["manage-account"]
                },
            },
        }
        user = UserInfo.from_jwt_claims(claims, resource_id="sat-irriga")
        assert user.sub == "user-123"
        assert user.name == "Tharles Andrade"
        assert user.email == "tharles@example.com"
        assert user.roles == ["acesso", "homologar", "gerenciar-mascaras"]
        assert user.realm_roles == ["planet-tiles", "planet-mosaicos"]
        assert user.token_exp == 1700000000

    def test_from_jwt_claims_without_resource_id(self):
        claims = {
            "sub": "user-456",
            "name": "Test User",
            "email": "test@example.com",
            "realm_access": {"roles": ["user", "admin"]},
            "resource_access": {
                "sat-irriga": {"roles": ["acesso"]},
            },
        }
        user = UserInfo.from_jwt_claims(claims)
        assert user.roles == []
        assert user.realm_roles == ["user", "admin"]

    def test_from_jwt_claims_unknown_resource_id(self):
        claims = {
            "sub": "user-789",
            "name": "Test",
            "email": "t@example.com",
            "resource_access": {
                "sat-irriga": {"roles": ["acesso"]},
            },
        }
        user = UserInfo.from_jwt_claims(claims, resource_id="outro-sistema")
        assert user.roles == []

    def test_from_jwt_claims_minimal(self):
        user = UserInfo.from_jwt_claims({})
        assert user.sub == ""
        assert user.name == ""
        assert user.roles == []
        assert user.realm_roles == []


class TestMapeamento:
    def test_from_dict(self):
        data = {
            "id": 42,
            "descricao": "Mapeamento Teste",
            "dataReferencia": "2024-01-15",
            "status": "DONE",
            "satelite": "Sentinel-2",
            "areaTotalHa": 1500.5,
            "metodoMapeamentos": [
                {
                    "id": 1,
                    "metodoApply": "RANDOM_FOREST",
                    "status": "DONE",
                },
            ],
        }
        m = Mapeamento.from_dict(data)
        assert m.id == 42
        assert m.descricao == "Mapeamento Teste"
        assert m.data_referencia == "2024-01-15"
        assert m.satelite == "Sentinel-2"
        assert len(m.metodos) == 1
        assert m.metodos[0].metodo_apply == "RANDOM_FOREST"

    def test_from_dict_empty(self):
        m = Mapeamento.from_dict({})
        assert m.id == 0
        assert m.metodos == []


class TestPaginatedResult:
    def test_from_dict(self):
        data = {
            "content": [
                {"id": 1, "descricao": "M1", "dataReferencia": "2024-01-01", "status": "DONE"},
                {"id": 2, "descricao": "M2", "dataReferencia": "2024-02-01", "status": "PROCESSING"},
            ],
            "number": 0,
            "size": 15,
            "totalElements": 50,
            "totalPages": 4,
        }
        result = PaginatedResult.from_dict(data)
        assert len(result.content) == 2
        assert result.page == 0
        assert result.total_elements == 50
        assert result.total_pages == 4


class TestMetodo:
    def test_from_dict(self):
        data = {
            "id": 10,
            "metodoApply": "SVM",
            "status": "PROCESSING",
            "mapeamentoId": 42,
            "totalGeometrias": 100,
            "metodoGeometrias": [
                {"id": 1, "idSeg": 99, "areaHa": 12.5, "grupo": "Irrigado"},
            ],
        }
        metodo = Metodo.from_dict(data)
        assert metodo.id == 10
        assert metodo.metodo_apply == "SVM"
        assert metodo.mapeamento_id == 42
        assert len(metodo.geometrias) == 1
        assert metodo.geometrias[0].area_ha == 12.5


class TestZonal:
    def test_from_dict(self):
        data = {
            "id": 5,
            "metodoId": 10,
            "status": "DONE",
            "zonalGeometrias": [
                {"id": 1, "evi": 0.5, "ndvi": 0.7, "scanDate": "2024-01-15"},
            ],
        }
        z = Zonal.from_dict(data)
        assert z.id == 5
        assert z.metodo_id == 10
        assert len(z.geometrias) == 1
        assert z.geometrias[0].ndvi == 0.7
