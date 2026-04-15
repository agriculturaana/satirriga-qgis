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

# Bandas base sempre geradas via acesso direto (image_id).
# Diffs so aparecem quando url_indices traz as chaves "Diferenca ...".
BASE_BAND_KEYS = ["original", "NDVI", "NDWI", "albedo"]
ALL_BAND_KEYS = BASE_BAND_KEYS


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

    def test_urls_contain_vis_params(self):
        """URLs diretas incluem parametros de visualizacao (min/max/gamma/palette)."""
        tile_data = [_make_tile(image_id="MY_IMG")]
        h = build_raster_hierarchy(tile_data, "RANDOM_FOREST")

        for band in h.dates[0].bands:
            for layer in band.layers:
                assert layer.xyz_url.startswith(_JOBS_BASE)
                assert "MY_IMG" in layer.xyz_url
                assert f"band={band.band_key}" in layer.xyz_url
                # URLs diretas agora incluem params de visualizacao
                assert "&" in layer.xyz_url

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
        assert "classIrri" not in band_keys  # classIrri removido

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
# build_raster_hierarchy — camadas de diferenca
# ----------------------------------------------------------------

# URL de diff e replicada em todos os tiles da resposta (payload real).
_DIFF_NDVI_URL = (
    "https://jobs.snirh.gov.br/tiles/s2/"
    "20251122T125321_20251122T125323_T24MXU-20251115T125259_20251115T125302_T24MXU"
    "/{z}/{x}/{y}?band=NDVI&min=0.035&max=0.23&operator=SUBTRACT"
)
_DIFF_NDWI_URL = _DIFF_NDVI_URL.replace("band=NDVI", "band=NDWI")
_DIFF_ALBEDO_URL = _DIFF_NDVI_URL.replace("band=NDVI", "band=albedo")


def _make_fuzzy_tile(image_id, data):
    """Tile real do payload fuzzy: url_indices com bases + 3 diffs identicas."""
    return {
        "id_imagem": image_id,
        "tile": "24MXU_52",
        "data": data,
        "url": f"https://jobs.snirh.gov.br/tiles/s2/{image_id}/{{z}}/{{x}}/{{y}}?band=original",
        "metodo2_fuzzy_response": {
            "url_indices": {
                "NDVI": f"https://jobs.snirh.gov.br/tiles/s2/{image_id}/{{z}}/{{x}}/{{y}}?band=NDVI",
                "Diferença NDVI": _DIFF_NDVI_URL,
                "NDWI": f"https://jobs.snirh.gov.br/tiles/s2/{image_id}/{{z}}/{{x}}/{{y}}?band=NDWI",
                "Diferença NDWI": _DIFF_NDWI_URL,
                "albedo": f"https://jobs.snirh.gov.br/tiles/s2/{image_id}/{{z}}/{{x}}/{{y}}?band=albedo",
                "Diferença albedo": _DIFF_ALBEDO_URL,
            }
        },
    }


class TestBuildHierarchyDiff:
    """Cobertura do payload real com 'Diferença NDVI/NDWI/albedo'."""

    def test_diffs_appear_on_first_image_date(self):
        """Diffs devem aparecer apenas na data da primeira imagem do par (img_A)."""
        tile_data = [
            _make_fuzzy_tile("20251122T125321_20251122T125323_T24MXU", "2025-11-22"),
            _make_fuzzy_tile("20251115T125259_20251115T125302_T24MXU", "2025-11-15"),
            _make_fuzzy_tile("20251112T125321_20251112T125321_T24MXU", "2025-11-12"),
        ]
        h = build_raster_hierarchy(tile_data, "METODO_2_FUZZY")

        date_to_bandkeys = {
            d.date_iso: [b.band_key for b in d.bands] for d in h.dates
        }
        # Data do par A: possui as 3 diffs alem das bases.
        assert "ndvi_diff" in date_to_bandkeys["2025-11-22"]
        assert "ndwi_diff" in date_to_bandkeys["2025-11-22"]
        assert "albedo_diff" in date_to_bandkeys["2025-11-22"]
        # Datas fora do par: sem diffs.
        assert "ndvi_diff" not in date_to_bandkeys["2025-11-15"]
        assert "ndvi_diff" not in date_to_bandkeys["2025-11-12"]

    def test_diff_layers_deduplicated(self):
        """Mesma URL replicada em N tiles deve gerar apenas 1 camada por banda."""
        tile_data = [
            _make_fuzzy_tile("20251122T125321_20251122T125323_T24MXU", "2025-11-22"),
            _make_fuzzy_tile("20251115T125259_20251115T125302_T24MXU", "2025-11-15"),
            _make_fuzzy_tile("20251112T125321_20251112T125321_T24MXU", "2025-11-12"),
            _make_fuzzy_tile("20251105T125259_20251105T125302_T24MXU", "2025-11-05"),
        ]
        h = build_raster_hierarchy(tile_data, "METODO_2_FUZZY")

        date_22 = next(d for d in h.dates if d.date_iso == "2025-11-22")
        diff_bands = [b for b in date_22.bands if b.band_key.endswith("_diff")]
        for band in diff_bands:
            assert len(band.layers) == 1, (
                f"Esperava 1 layer deduplicada em {band.band_key}, "
                f"obtive {len(band.layers)}"
            )

    def test_diff_urls_preserved_verbatim(self):
        """URL de diff ja vem pronta do servidor — nao deve ser reescrita."""
        tile_data = [
            _make_fuzzy_tile("20251122T125321_20251122T125323_T24MXU", "2025-11-22"),
        ]
        h = build_raster_hierarchy(tile_data, "METODO_2_FUZZY")

        date_22 = h.dates[0]
        ndvi_diff = next(b for b in date_22.bands if b.band_key == "ndvi_diff")
        assert ndvi_diff.layers[0].xyz_url == _DIFF_NDVI_URL
        assert "operator=SUBTRACT" in ndvi_diff.layers[0].xyz_url

    def test_diff_layers_invisible_by_default(self):
        tile_data = [
            _make_fuzzy_tile("20251122T125321_20251122T125323_T24MXU", "2025-11-22"),
        ]
        h = build_raster_hierarchy(tile_data, "METODO_2_FUZZY")

        for band in h.dates[0].bands:
            if band.band_key.endswith("_diff"):
                for layer in band.layers:
                    assert layer.is_visible is False

    def test_diff_band_display_names(self):
        tile_data = [
            _make_fuzzy_tile("20251122T125321_20251122T125323_T24MXU", "2025-11-22"),
        ]
        h = build_raster_hierarchy(tile_data, "METODO_2_FUZZY")

        names = {b.band_key: b.band_name for b in h.dates[0].bands}
        assert names["ndvi_diff"] == "Diff NDVI"
        assert names["ndwi_diff"] == "Diff NDWI"
        assert names["albedo_diff"] == "Diff Albedo"

    def test_no_diffs_when_method_response_lacks_diff_keys(self):
        """Zonais de metodos sem diffs (e.g. METODO_1) nao devem gerar diff bands."""
        tile_data = [_make_tile()]
        h = build_raster_hierarchy(tile_data, "METODO_1")

        for date in h.dates:
            for band in date.bands:
                assert not band.band_key.endswith("_diff")

    def test_diff_layer_image_id_is_compound(self):
        tile_data = [
            _make_fuzzy_tile("20251122T125321_20251122T125323_T24MXU", "2025-11-22"),
        ]
        h = build_raster_hierarchy(tile_data, "METODO_2_FUZZY")

        ndvi_diff = next(
            b for b in h.dates[0].bands if b.band_key == "ndvi_diff"
        )
        assert "-" in ndvi_diff.layers[0].image_id  # compound A-B


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
        # Defaults hardcoded: min=0, max=0.8, palette=RDYLGN
        assert "min=0" in url
        assert "max=0.8" in url
        assert "palette=RDYLGN" in url

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
        # GEE: palette e gamma sao mutuamente exclusivos; palette tem prioridade
        assert "palette=VIRIDIS" in url
        assert "gamma" not in url

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
        # 2 tiles × 4 bandas (original, NDVI, NDWI, albedo) = 8
        assert len(configs) == 8
