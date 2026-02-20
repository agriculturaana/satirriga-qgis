"""Testes unitarios para domain models — sem dependencia QGIS."""

import pytest

from domain.models.enums import (
    JobStatusEnum, MetodoMapeamentoEnum, SyncStatusEnum,
    ZonalStatusEnum, UploadBatchStatusEnum, ConflictResolutionEnum,
)
from domain.models.user import UserInfo
from domain.models.mapeamento import Mapeamento, PaginatedResult
from domain.models.metodo import Metodo, MetodoGeometria
from domain.models.zonal import Zonal, ZonalGeometria, CatalogoItem
from domain.models.upload_batch import UploadBatchStatus
from domain.models.conflict import ConflictItem, ConflictSet


class TestJobStatusEnum:
    def test_colors(self):
        assert JobStatusEnum.DONE.color == "#4CAF50"
        assert JobStatusEnum.PROCESSING.color == "#FF9800"
        assert JobStatusEnum.FAILED.color == "#F44336"

    def test_labels(self):
        assert JobStatusEnum.DONE.label == "Concluido"
        assert JobStatusEnum.PROCESSING.label == "Processando"


class TestSyncStatusEnum:
    def test_has_new_value(self):
        assert SyncStatusEnum.NEW.value == "NEW"

    def test_all_values(self):
        values = {e.value for e in SyncStatusEnum}
        assert values == {"DOWNLOADED", "MODIFIED", "UPLOADED", "NEW"}


class TestZonalStatusEnum:
    def test_all_values(self):
        values = {e.value for e in ZonalStatusEnum}
        assert "CREATED" in values
        assert "CONSOLIDATED" in values
        assert "CONSOLIDATION_FAILED" in values

    def test_labels(self):
        assert ZonalStatusEnum.CONSOLIDATED.label == "Consolidado"
        assert ZonalStatusEnum.PROCESSING.label == "Processando"
        assert ZonalStatusEnum.CONSOLIDATION_FAILED.label == "Falha na consolidacao"

    def test_colors(self):
        assert ZonalStatusEnum.DONE.color == "#4CAF50"
        assert ZonalStatusEnum.CONSOLIDATED.color == "#1B5E20"
        assert ZonalStatusEnum.FAILED.color == "#F44336"


class TestUploadBatchStatusEnum:
    def test_all_values(self):
        values = {e.value for e in UploadBatchStatusEnum}
        assert "RECEIVED" in values
        assert "COMPLETED" in values
        assert "CONFLICT_CHECKING" in values

    def test_labels(self):
        assert UploadBatchStatusEnum.RECEIVED.label == "Recebido"
        assert UploadBatchStatusEnum.VALIDATING_TOPOLOGY.label == "Validando topologia"
        assert UploadBatchStatusEnum.COMPLETED.label == "Concluido"

    def test_is_terminal_true(self):
        assert UploadBatchStatusEnum.COMPLETED.is_terminal is True
        assert UploadBatchStatusEnum.FAILED.is_terminal is True
        assert UploadBatchStatusEnum.CANCELLED.is_terminal is True

    def test_is_terminal_false(self):
        assert UploadBatchStatusEnum.RECEIVED.is_terminal is False
        assert UploadBatchStatusEnum.DIFFING.is_terminal is False
        assert UploadBatchStatusEnum.PROMOTING.is_terminal is False


class TestConflictResolutionEnum:
    def test_values(self):
        assert ConflictResolutionEnum.TAKE_MINE.value == "TAKE_MINE"
        assert ConflictResolutionEnum.TAKE_THEIRS.value == "TAKE_THEIRS"
        assert ConflictResolutionEnum.MERGE.value == "MERGE"


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
        assert m.data_referencia == "15/01/2024"
        assert m.satelite == "Sentinel-2"
        assert len(m.metodos) == 1
        assert m.metodos[0].metodo_apply == "RANDOM_FOREST"

    def test_from_dict_empty(self):
        m = Mapeamento.from_dict({})
        assert m.id == 0
        assert m.metodos == []


class TestPaginatedResult:
    def test_from_dict_spring_format(self):
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

    def test_from_dict_api_pagination_1indexed(self):
        """API retorna pagination.page 1-indexed; model normaliza para 0-indexed."""
        data = {
            "data": [
                {"id": 1, "descricao": "M1", "dataReferencia": "2024-01-01", "status": "DONE"},
            ],
            "pagination": {
                "page": 1,
                "size": 15,
                "total": 50,
                "totalPages": 4,
            },
        }
        result = PaginatedResult.from_dict(data)
        assert result.page == 0
        assert result.total_elements == 50
        assert result.total_pages == 4

    def test_from_dict_api_pagination_page3(self):
        data = {
            "data": [],
            "pagination": {
                "page": 3,
                "size": 15,
                "total": 50,
                "totalPages": 4,
            },
        }
        result = PaginatedResult.from_dict(data)
        assert result.page == 2


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


class TestCatalogoItem:
    def test_from_dict_full(self):
        data = {
            "id": 42,
            "descricao": "Zonal Cerrado 2024",
            "status": "CONSOLIDATED",
            "processedAt": "2024-06-15T10:30:00Z",
            "resultCount": 1500,
            "totalAreaHa": 25000.75,
            "bbox": [-52.0, -15.0, -47.0, -10.0],
        }
        item = CatalogoItem.from_dict(data)
        assert item.id == 42
        assert item.descricao == "Zonal Cerrado 2024"
        assert item.status == "CONSOLIDATED"
        assert item.processed_at == "2024-06-15T10:30:00Z"
        assert item.result_count == 1500
        assert item.total_area_ha == 25000.75
        assert item.bbox == [-52.0, -15.0, -47.0, -10.0]

    def test_from_dict_minimal(self):
        data = {"id": 1, "descricao": "Test", "status": "DONE"}
        item = CatalogoItem.from_dict(data)
        assert item.id == 1
        assert item.processed_at is None
        assert item.result_count == 0
        assert item.total_area_ha == 0.0
        assert item.bbox is None

    def test_from_dict_empty(self):
        item = CatalogoItem.from_dict({})
        assert item.id == 0
        assert item.descricao == ""
        assert item.status == ""


class TestUploadBatchStatus:
    def test_from_dict_full(self):
        data = {
            "batchUuid": "abc-123-def",
            "status": "VALIDATING_TOPOLOGY",
            "progressPct": 45,
            "featureCount": 100,
            "validCount": 80,
            "invalidCount": 5,
            "conflictCount": 3,
            "acceptedCount": 70,
            "modifiedCount": 50,
            "newCount": 20,
            "deletedCount": 10,
            "errorLog": None,
            "completedAt": None,
        }
        status = UploadBatchStatus.from_dict(data)
        assert status.batch_uuid == "abc-123-def"
        assert status.status == "VALIDATING_TOPOLOGY"
        assert status.progress_pct == 45
        assert status.feature_count == 100
        assert status.valid_count == 80
        assert status.invalid_count == 5
        assert status.conflict_count == 3
        assert status.accepted_count == 70
        assert status.modified_count == 50
        assert status.new_count == 20
        assert status.deleted_count == 10
        assert status.error_log is None
        assert status.completed_at is None

    def test_from_dict_completed(self):
        data = {
            "batchUuid": "xyz-789",
            "status": "COMPLETED",
            "progressPct": 100,
            "completedAt": "2024-06-15T12:00:00Z",
        }
        status = UploadBatchStatus.from_dict(data)
        assert status.status == "COMPLETED"
        assert status.progress_pct == 100
        assert status.completed_at == "2024-06-15T12:00:00Z"

    def test_from_dict_minimal(self):
        status = UploadBatchStatus.from_dict({})
        assert status.batch_uuid == ""
        assert status.status == ""
        assert status.progress_pct == 0
        assert status.feature_count == 0


class TestConflictItem:
    def test_from_dict(self):
        data = {
            "featureHash": "abc123hash",
            "conflictType": "GEOMETRY_CHANGED",
            "mine": {"type": "Feature", "geometry": {"type": "Polygon"}},
            "theirs": {"type": "Feature", "geometry": {"type": "Polygon"}},
            "suggested": "TAKE_MINE",
        }
        item = ConflictItem.from_dict(data)
        assert item.feature_hash == "abc123hash"
        assert item.conflict_type == "GEOMETRY_CHANGED"
        assert item.mine is not None
        assert item.theirs is not None
        assert item.suggested == "TAKE_MINE"

    def test_from_dict_minimal(self):
        item = ConflictItem.from_dict({})
        assert item.feature_hash == ""
        assert item.conflict_type == ""
        assert item.mine is None
        assert item.theirs is None
        assert item.suggested is None


class TestConflictSet:
    def test_from_dict_full(self):
        data = {
            "conflictId": 99,
            "baseVersion": 3,
            "currentVersion": 5,
            "items": [
                {
                    "featureHash": "hash1",
                    "conflictType": "GEOMETRY_CHANGED",
                    "suggested": "TAKE_THEIRS",
                },
                {
                    "featureHash": "hash2",
                    "conflictType": "ATTRIBUTE_CHANGED",
                },
            ],
            "expiresAt": "2024-06-15T13:00:00Z",
            "status": "PENDING",
        }
        cs = ConflictSet.from_dict(data)
        assert cs.conflict_id == 99
        assert cs.base_version == 3
        assert cs.current_version == 5
        assert len(cs.items) == 2
        assert cs.items[0].feature_hash == "hash1"
        assert cs.items[0].suggested == "TAKE_THEIRS"
        assert cs.items[1].feature_hash == "hash2"
        assert cs.items[1].suggested is None
        assert cs.expires_at == "2024-06-15T13:00:00Z"
        assert cs.status == "PENDING"

    def test_from_dict_empty_items(self):
        data = {
            "conflictId": 1,
            "baseVersion": 0,
            "currentVersion": 1,
        }
        cs = ConflictSet.from_dict(data)
        assert cs.items == []
        assert cs.expires_at is None

    def test_from_dict_minimal(self):
        cs = ConflictSet.from_dict({})
        assert cs.conflict_id == 0
        assert cs.base_version == 0
        assert cs.current_version == 0
        assert cs.items == []
