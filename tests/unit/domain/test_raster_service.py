"""Testes unitarios para domain.services.raster_service."""

from domain.models.raster import VisParams, RasterHierarchy
from domain.services.raster_service import (
    build_raster_hierarchy,
    build_raster_configs,
    build_xyz_url,
    get_default_vis_params,
    get_tile_url,
    _JOBS_BASE,
    _BAND_ORDER,
)


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------

ALL_BAND_KEYS = list(_BAND_ORDER)


def _make_tile(image_id="S2A_MSIL2A_20251022T132231_N0511_R038_T24MXT_20251022T172030",
               data="2025-10-22", tile="24MXT_52", url="https://legacy/url",
               metodo_key="metodo1_response",
               indices=None):
    """Cria dict de TileData para testes."""
    if indices is None:
        indices = {"class_irri": "u1", "NDVI": "u2", "NDWI": "u3", "albedo": "u4"}
    item = {
        "url": url,
        "id_imagem": image_id,
        "data": data,
        "tile": tile,
    }
    if metodo_key:
        item[metodo_key] = {"url_indices": indices}
    return item


def _make_legacy_tile(data="2025-01-01", url="https://legacy/rgb",
                      metodo_key="metodo1_response", indices=None):
    """Cria TileData legado (sem id_imagem)."""
    if indices is None:
        indices = {"class_irri": "u1", "NDVI": "u2", "NDWI": "u3", "albedo": "u4"}
    item = {"url": url, "data": data}
    if metodo_key:
        item[metodo_key] = {"url_indices": indices}
    return item


# ----------------------------------------------------------------
# build_raster_hierarchy — tiles com image_id (acesso direto)
# ----------------------------------------------------------------

class TestBuildHierarchyDirect:
    """Tiles com id_imagem: todas as bandas via URL direta ao jobs-server."""

    def test_multiple_tiles_single_date(self):
        tile_data = [
            _make_tile(image_id="IMG_A", tile="24MXT"),
            _make_tile(image_id="IMG_B", tile="24MXU"),
        ]
        h = build_raster_hierarchy(tile_data, "RANDOM_FOREST")

        assert len(h.dates) == 1
        assert h.dates[0].date_label == "22/10/2025"
        band_keys = [b.band_key for b in h.dates[0].bands]
        assert band_keys == ALL_BAND_KEYS
        for band in h.dates[0].bands:
            assert len(band.layers) == 2

    def test_multiple_dates(self):
        tile_data = [
            _make_tile(image_id="IMG_A", data="2025-10-22", tile="24MXT"),
            _make_tile(image_id="IMG_B", data="2025-11-15", tile="24MXT"),
        ]
        h = build_raster_hierarchy(tile_data, "RANDOM_FOREST")

        assert len(h.dates) == 2
        assert h.dates[0].date_iso == "2025-11-15"
        assert h.dates[1].date_iso == "2025-10-22"

    def test_all_bands_regardless_of_metodo(self):
        """Com image_id, todas as bandas sao geradas independente do metodo."""
        tile_data = [_make_tile(metodo_key=None)]
        h = build_raster_hierarchy(tile_data, "METODO_DESCONHECIDO")

        band_keys = [b.band_key for b in h.dates[0].bands]
        assert band_keys == ALL_BAND_KEYS

    def test_all_bands_with_real_metodo_names(self):
        """Testa com nomes reais de metodo da API (RANDOM_FOREST, SVM, etc.)."""
        for metodo in ("RANDOM_FOREST", "SVM", "DEEP_LEARNING", "MANUAL"):
            tile_data = [_make_tile()]
            h = build_raster_hierarchy(tile_data, metodo)
            band_keys = [b.band_key for b in h.dates[0].bands]
            assert band_keys == ALL_BAND_KEYS, f"Falhou para metodo={metodo}"

    def test_urls_are_simple_band_only(self):
        """URLs diretas devem conter apenas ?band=X, sem min/max/palette."""
        tile_data = [_make_tile(image_id="MY_IMG")]
        h = build_raster_hierarchy(tile_data, "RANDOM_FOREST")

        for band in h.dates[0].bands:
            for layer in band.layers:
                assert layer.xyz_url.startswith(_JOBS_BASE)
                assert "MY_IMG" in layer.xyz_url
                assert f"?band={band.band_key}" in layer.xyz_url
                # Nao deve conter & (parametros extras) — servidor aplica defaults
                assert "&" not in layer.xyz_url

    def test_image_id_and_vis_params_preserved(self):
        tile_data = [_make_tile(image_id="MY_IMAGE")]
        h = build_raster_hierarchy(tile_data, "RANDOM_FOREST")

        rgb_band = next(b for b in h.dates[0].bands if b.band_key == "original")
        layer = rgb_band.layers[0]
        assert layer.image_id == "MY_IMAGE"
        assert layer.vis_params.band == "original"
        assert layer.vis_params.min_val == 0
        assert layer.vis_params.max_val == 3000
        assert layer.vis_params.gamma == 1.2

    def test_layer_visibility_defaults(self):
        tile_data = [_make_tile()]
        h = build_raster_hierarchy(tile_data, "RANDOM_FOREST")

        for band in h.dates[0].bands:
            for layer in band.layers:
                if band.band_key in ("classIrri", "original"):
                    assert layer.is_visible is True
                else:
                    assert layer.is_visible is False

    def test_date_extraction_with_datetime(self):
        """Campo data com timestamp completo deve ser normalizado."""
        tile_data = [_make_tile(data="2025-10-22T13:22:31Z")]
        h = build_raster_hierarchy(tile_data, "RANDOM_FOREST")
        assert h.dates[0].date_iso == "2025-10-22"
        assert h.dates[0].date_label == "22/10/2025"

    def test_alternative_date_field_names(self):
        """Testa campos alternativos de data (dataReferencia, scanDate)."""
        for field in ("data", "date", "dataReferencia", "scanDate"):
            tile_data = [{"id_imagem": "IMG_X", field: "2025-03-15", "tile": "T1"}]
            h = build_raster_hierarchy(tile_data, "RANDOM_FOREST")
            assert len(h.dates) == 1
            assert h.dates[0].date_label == "15/03/2025", f"Falhou para campo={field}"


# ----------------------------------------------------------------
# build_raster_hierarchy — tiles legados (sem image_id)
# ----------------------------------------------------------------

class TestBuildHierarchyLegacy:
    """Tiles sem id_imagem: fallback para URLs da API."""

    def test_legacy_rgb_only_without_metodo(self):
        tile_data = [_make_legacy_tile(metodo_key=None)]
        h = build_raster_hierarchy(tile_data, "METODO_1")

        assert len(h.dates) == 1
        band_keys = [b.band_key for b in h.dates[0].bands]
        assert band_keys == ["original"]
        assert h.dates[0].bands[0].layers[0].xyz_url == "https://legacy/rgb"

    def test_legacy_with_indices(self):
        tile_data = [_make_legacy_tile(metodo_key="metodo1_response")]
        h = build_raster_hierarchy(tile_data, "METODO_1")

        band_keys = [b.band_key for b in h.dates[0].bands]
        assert "original" in band_keys
        assert "NDVI" in band_keys
        assert "classIrri" in band_keys

    def test_legacy_unknown_metodo_only_rgb(self):
        """Legado sem indices: apenas RGB."""
        tile_data = [_make_legacy_tile(metodo_key=None)]
        h = build_raster_hierarchy(tile_data, "DESCONHECIDO")

        band_keys = [b.band_key for b in h.dates[0].bands]
        assert band_keys == ["original"]


# ----------------------------------------------------------------
# build_raster_hierarchy — edge cases
# ----------------------------------------------------------------

class TestBuildHierarchyEdgeCases:

    def test_empty_input(self):
        assert build_raster_hierarchy([], "RANDOM_FOREST").dates == []
        assert build_raster_hierarchy(None, "RANDOM_FOREST").dates == []
        assert build_raster_hierarchy("invalid", "RANDOM_FOREST").dates == []

    def test_dict_input_normalized_to_list(self):
        tile = _make_tile()
        h = build_raster_hierarchy(tile, "RANDOM_FOREST")
        assert len(h.dates) == 1

    def test_missing_date_label(self):
        tile_data = [_make_tile(data="")]
        h = build_raster_hierarchy(tile_data, "RANDOM_FOREST")
        assert h.dates[0].date_label == "Sem data"


# ----------------------------------------------------------------
# get_tile_url — URL simples
# ----------------------------------------------------------------

class TestGetTileUrl:

    def test_default_band(self):
        url = get_tile_url("IMG123")
        assert url == f"{_JOBS_BASE}/IMG123/{{z}}/{{x}}/{{y}}?band=original"

    def test_specific_band(self):
        url = get_tile_url("IMG123", "NDVI")
        assert url == f"{_JOBS_BASE}/IMG123/{{z}}/{{x}}/{{y}}?band=NDVI"

    def test_no_extra_params(self):
        """URL simples nao deve conter & (apenas ?band=X)."""
        url = get_tile_url("IMG123", "classIrri")
        assert "&" not in url
        assert "?band=classIrri" in url


# ----------------------------------------------------------------
# build_xyz_url — URL com parametros de customizacao
# ----------------------------------------------------------------

class TestBuildXyzUrl:

    def test_default_params(self):
        params = get_default_vis_params("NDVI")
        url = build_xyz_url("IMG123", params)
        assert url.startswith(f"{_JOBS_BASE}/IMG123/")
        assert "band=NDVI" in url
        assert "min=-1" in url
        assert "max=1" in url
        assert "palette=NDVI" in url

    def test_original_with_gamma(self):
        params = get_default_vis_params("original")
        url = build_xyz_url("IMG123", params)
        assert "band=original" in url
        assert "gamma=1.2" in url
        assert "palette" not in url

    def test_custom_params(self):
        params = VisParams(
            band="NDVI", min_val=-0.5, max_val=0.8,
            gamma=1.5, palette="VIRIDIS",
        )
        url = build_xyz_url("IMG_X", params)
        assert "min=-0.5" in url
        assert "max=0.8" in url
        assert "gamma=1.5" in url
        assert "palette=VIRIDIS" in url

    def test_optional_params_omitted(self):
        params = VisParams(band="original")
        url = build_xyz_url("IMG_X", params)
        assert "min=" not in url
        assert "gamma=" not in url
        assert "palette=" not in url
        assert "gain=" not in url


# ----------------------------------------------------------------
# Backward compatibility
# ----------------------------------------------------------------

class TestBackwardCompat:

    def test_build_raster_configs_returns_flat_list(self):
        tile_data = [
            _make_tile(image_id="IMG_A", tile="24MXT"),
            _make_tile(image_id="IMG_B", tile="24MXU"),
        ]
        configs = build_raster_configs(tile_data, "RANDOM_FOREST")

        assert isinstance(configs, list)
        assert all(hasattr(c, "xyz_url") for c in configs)
        # 2 tiles × 6 bandas (todas, pois tem image_id) = 12
        assert len(configs) == 12
