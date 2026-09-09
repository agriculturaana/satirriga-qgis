"""Testes do resumo de retorno do upload e do desfecho do reprocessamento."""

from domain.services.upload_feedback import (
    RejectedFeature,
    find_duplicate_original_fids,
    is_terminal_zonal_status,
    parse_rejections,
    reprocessing_outcome,
    summarize_batch,
)


class TestParseRejections:
    def test_lista_vazia_quando_error_log_ausente(self):
        assert parse_rejections(None) == []
        assert parse_rejections("erro textual") == []
        assert parse_rejections({}) == []

    def test_extrai_fid_motivo_e_desfecho(self):
        error_log = {
            "mantidas": 1,
            "rejeitadas": [
                {"stagingId": 10, "originalFid": 65183, "syncStatus": "MODIFIED",
                 "diffAction": "UPDATE", "errors": [{"type": "SLIVER", "detail": 401.2}]},
                {"stagingId": 11, "originalFid": None, "syncStatus": "NEW",
                 "diffAction": "INSERT", "errors": [{"type": "SLIVER", "detail": 380.0}]},
                {"stagingId": 12, "originalFid": 65192, "syncStatus": "DOWNLOADED",
                 "diffAction": None, "errors": [{"type": "DUPLICATE_FEATURE", "detail": 65192}]},
                {"stagingId": 13, "originalFid": 60001, "syncStatus": "DOWNLOADED",
                 "diffAction": None, "errors": [{"type": "STALE_DELETED", "detail": 60001}]},
            ],
        }
        rejeitadas = parse_rejections(error_log)
        assert [r.original_fid for r in rejeitadas] == [65183, None, 65192, 60001]
        assert rejeitadas[0].kept_previous is True
        assert "900" in rejeitadas[0].reasons[0]
        assert rejeitadas[1].kept_previous is False
        assert rejeitadas[2].kept_previous is True
        assert rejeitadas[3].kept_previous is False

    def test_motivo_desconhecido_mantem_codigo(self):
        rejeitadas = parse_rejections({"rejeitadas": [
            {"originalFid": 1, "errors": [{"type": "ALGO_NOVO", "detail": None}]}
        ]})
        assert rejeitadas[0].reasons == ["ALGO_NOVO"]


class TestSummarizeBatch:
    def test_resumo_inclui_removidas_invalidas_e_rejeicoes(self):
        status = {
            "status": "COMPLETED", "featureCount": 612, "validCount": 610, "invalidCount": 2,
            "newCount": 3, "modifiedCount": 1, "deletedCount": 1, "acceptedCount": 605,
            "errorLog": {"mantidas": 1, "rejeitadas": [
                {"originalFid": 65183, "errors": [{"type": "SLIVER", "detail": 401.2}]},
                {"originalFid": 65192, "errors": [{"type": "DUPLICATE_FEATURE", "detail": 65192}]},
            ]},
        }
        resumo = summarize_batch(status)
        assert resumo.deleted_count == 1
        assert resumo.invalid_count == 2
        assert len(resumo.rejected) == 2
        texto = resumo.detail_text()
        assert "Removidas: 1" in texto
        assert "Rejeitadas: 2" in texto
        assert "65183" in resumo.rejection_text()

    def test_resumo_sem_rejeicoes(self):
        resumo = summarize_batch({"featureCount": 10, "newCount": 0, "errorLog": None})
        assert resumo.rejected == []
        assert resumo.rejection_text() == ""


class TestReprocessingOutcome:
    def test_consolidado_e_sucesso(self):
        r = reprocessing_outcome("CONSOLIDATED", None, 0)
        assert r.ok is True
        assert r.label == "Consolidado"

    def test_falha_de_overlay_traz_motivo(self):
        r = reprocessing_outcome("OVERLAY_FAILED", "2 feição(ões) sem geoid após 25 ciclos", 2)
        assert r.ok is False
        assert "Falha no overlay" in r.label
        assert "25 ciclos" in r.message
        assert r.color == "#B71C1C"

    def test_status_intermediario_nao_e_terminal(self):
        assert is_terminal_zonal_status("PROCESSING") is False
        assert is_terminal_zonal_status("OVERLAID") is False
        assert is_terminal_zonal_status("CONSOLIDATED") is True
        assert is_terminal_zonal_status("OVERLAY_FAILED") is True


class TestDuplicateOriginalFids:
    def test_detecta_repeticoes_ignorando_nulos(self):
        fids = [10, 11, 11, None, None, 0, 12, 12, 12]
        assert find_duplicate_original_fids(fids) == {11: 2, 12: 3}
