"""Testes unitarios para domain.services.tile_indexes_service."""

import json
from unittest.mock import MagicMock

from domain.services.tile_indexes_service import TileIndexesService


class _FakeConfig:
    def __init__(self, base_url):
        self._base = base_url

    def get(self, key):
        if key == "api_base_url":
            return self._base
        return None


def _make_service(base_url="https://api.test/api"):
    http = MagicMock()
    http.post_json = MagicMock(return_value="req-1")
    cfg = _FakeConfig(base_url)
    return TileIndexesService(http, cfg), http


class TestRequest:
    def test_posts_to_correct_endpoint(self):
        service, http = _make_service()
        rid = service.request(["A", "B"], -15.5, -48.2)
        assert rid == "req-1"
        url, body = http.post_json.call_args[0]
        assert url == "https://api.test/api/mapeamento/tiles/get/indexs/images"
        payload = json.loads(body)
        assert payload == {
            "id_imagens": ["A", "B"],
            "lat": -15.5,
            "lon": -48.2,
        }

    def test_trims_trailing_slash_in_base(self):
        service, http = _make_service("https://api.test/api/")
        service.request(["A"], 0.0, 0.0)
        url, _ = http.post_json.call_args[0]
        assert url == "https://api.test/api/mapeamento/tiles/get/indexs/images"


class TestParseResponse:
    def test_parses_array(self):
        service, _ = _make_service()
        body = json.dumps([
            {"id_imagem": "X", "tile": "T", "data_formatada": "01/01",
             "ndvi": 0.5, "albedo": 0.2},
        ]).encode("utf-8")
        scenes = service.parse_response(body)
        assert len(scenes) == 1
        assert scenes[0].ndvi == 0.5

    def test_empty_body_returns_empty(self):
        service, _ = _make_service()
        assert service.parse_response(b"") == []

    def test_invalid_json_returns_empty(self):
        service, _ = _make_service()
        assert service.parse_response(b"not-json") == []


class TestCache:
    def test_store_and_retrieve(self):
        service, _ = _make_service()
        scenes = [
            type("S", (), {"id_imagem": "X"})(),
        ]
        service.store(["A"], -15.5, -48.2, scenes)
        cached = service.cached_for(["A"], -15.5, -48.2)
        assert cached is scenes

    def test_miss_returns_none(self):
        service, _ = _make_service()
        assert service.cached_for(["A"], -15.5, -48.2) is None

    def test_key_is_order_insensitive(self):
        service, _ = _make_service()
        sentinel = ["dummy"]
        service.store(["A", "B"], 1.0, 2.0, sentinel)
        assert service.cached_for(["B", "A"], 1.0, 2.0) is sentinel

    def test_key_rounds_coordinates(self):
        service, _ = _make_service()
        sentinel = ["dummy"]
        service.store(["A"], -15.1234567, -48.9876543, sentinel)
        # Mesmo ponto truncado a 6 casas
        assert service.cached_for(["A"], -15.1234567, -48.9876543) is sentinel

    def test_lru_eviction(self):
        service, _ = _make_service()
        # _CACHE_MAX default 64 — for tests, insere 70 e confirma cap
        for i in range(70):
            service.store([f"id-{i}"], float(i), 0.0, [f"val-{i}"])
        # Primeiros 6 devem ter sido evictados
        assert service.cached_for(["id-0"], 0.0, 0.0) is None
        assert service.cached_for(["id-69"], 69.0, 0.0) == ["val-69"]

    def test_clear_cache(self):
        service, _ = _make_service()
        service.store(["A"], 0.0, 0.0, ["x"])
        service.clear_cache()
        assert service.cached_for(["A"], 0.0, 0.0) is None
