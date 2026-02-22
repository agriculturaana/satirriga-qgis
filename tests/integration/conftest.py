"""Fixtures para testes de integracao com GDAL/OGR."""

import os
import tempfile
import shutil

import pytest
from osgeo import ogr, osr


@pytest.fixture
def temp_dir():
    """Diretorio temporario limpo automaticamente apos o teste."""
    d = tempfile.mkdtemp(prefix="satirriga_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _create_srs_4326():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    return srs


def create_fgb_with_features(path, features, extra_fields=None):
    """Cria FlatGeobuf com features de teste.

    Args:
        path: caminho do arquivo .fgb
        features: lista de dicts com keys: id, geometry_wkt, attrs (dict)
        extra_fields: lista de (nome, ogr_type) para campos adicionais
    """
    drv = ogr.GetDriverByName("FlatGeobuf")
    ds = drv.CreateDataSource(path)
    srs = _create_srs_4326()
    lyr = ds.CreateLayer("test", srs=srs, geom_type=ogr.wkbPolygon)

    # Campo 'id' obrigatorio (servidor usa)
    fd_id = ogr.FieldDefn("id", ogr.OFTInteger)
    lyr.CreateField(fd_id)

    # Campos padrao do dominio
    default_fields = [
        ("idSeg", ogr.OFTInteger),
        ("areaHa", ogr.OFTReal),
        ("grupo", ogr.OFTString),
        ("consolidado", ogr.OFTInteger),
    ]
    for fname, ftype in default_fields:
        lyr.CreateField(ogr.FieldDefn(fname, ftype))

    if extra_fields:
        for fname, ftype in extra_fields:
            lyr.CreateField(ogr.FieldDefn(fname, ftype))

    defn = lyr.GetLayerDefn()
    for feat_data in features:
        feat = ogr.Feature(defn)

        if "geometry_wkt" in feat_data:
            geom = ogr.CreateGeometryFromWkt(feat_data["geometry_wkt"])
            feat.SetGeometry(geom)

        feat.SetField("id", feat_data.get("id", 0))

        for key, val in feat_data.get("attrs", {}).items():
            idx = defn.GetFieldIndex(key)
            if idx >= 0:
                feat.SetField(idx, val)

        lyr.CreateFeature(feat)

    ds = None  # flush
    return path


def create_gpkg_v2_with_features(path, features, zonal_id=42, edit_token="tok-test"):
    """Cria GPKG com schema V2 (campos de sync) simulando resultado de download.

    Args:
        path: caminho do arquivo .gpkg
        features: lista de dicts com keys: id, geometry_wkt, attrs, sync_status
        zonal_id: id do zonal
        edit_token: token de edicao
    """
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(path)
    srs = _create_srs_4326()
    lyr = ds.CreateLayer("zonal", srs=srs, geom_type=ogr.wkbPolygon,
                         options=["FID=fid"])

    # Campos do dominio (mesmo schema que vem do servidor)
    domain_fields = [
        ("id", ogr.OFTInteger),
        ("idSeg", ogr.OFTInteger),
        ("areaHa", ogr.OFTReal),
        ("grupo", ogr.OFTString),
        ("consolidado", ogr.OFTInteger),
    ]
    for fname, ftype in domain_fields:
        lyr.CreateField(ogr.FieldDefn(fname, ftype))

    # Campos de sync V2
    sync_fields = [
        ("_original_fid", ogr.OFTInteger),
        ("_sync_status", ogr.OFTString),
        ("_sync_timestamp", ogr.OFTString),
        ("_zonal_id", ogr.OFTInteger),
        ("_edit_token", ogr.OFTString),
    ]
    for fname, ftype in sync_fields:
        lyr.CreateField(ogr.FieldDefn(fname, ftype))

    defn = lyr.GetLayerDefn()
    for feat_data in features:
        feat = ogr.Feature(defn)

        if "geometry_wkt" in feat_data:
            geom = ogr.CreateGeometryFromWkt(feat_data["geometry_wkt"])
            feat.SetGeometry(geom)

        feat.SetField("id", feat_data.get("id", 0))
        feat.SetField("_original_fid", feat_data.get("id", 0))
        feat.SetField("_sync_status", feat_data.get("sync_status", "DOWNLOADED"))
        feat.SetField("_sync_timestamp", "2026-01-01T00:00:00+00:00")
        feat.SetField("_zonal_id", zonal_id)
        feat.SetField("_edit_token", edit_token)

        for key, val in feat_data.get("attrs", {}).items():
            idx = defn.GetFieldIndex(key)
            if idx >= 0:
                feat.SetField(idx, val)

        lyr.CreateFeature(feat)

    ds = None  # flush
    return path


def read_gpkg_features(path):
    """Le features de um GPKG e retorna lista de dicts para assertions."""
    ds = ogr.Open(path, 0)
    if ds is None:
        return []

    lyr = ds.GetLayer(0)
    if lyr is None:
        ds = None
        return []

    defn = lyr.GetLayerDefn()
    field_names = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]

    results = []
    for feat in lyr:
        entry = {"fid": feat.GetFID()}

        geom = feat.GetGeometryRef()
        entry["has_geometry"] = geom is not None
        if geom:
            entry["geom_type"] = geom.GetGeometryType()
            entry["geom_wkt"] = geom.ExportToWkt()

        for fname in field_names:
            entry[fname] = feat.GetField(fname)

        results.append(entry)

    ds = None
    return results


def read_gpkg_field_names(path):
    """Retorna lista de nomes de campos de um GPKG."""
    ds = ogr.Open(path, 0)
    if ds is None:
        return []

    lyr = ds.GetLayer(0)
    if lyr is None:
        ds = None
        return []

    defn = lyr.GetLayerDefn()
    names = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    ds = None
    return names


def read_gpkg_srs(path):
    """Retorna authority code do CRS de um GPKG (ex: '4326')."""
    ds = ogr.Open(path, 0)
    if ds is None:
        return None

    lyr = ds.GetLayer(0)
    if lyr is None:
        ds = None
        return None

    srs = lyr.GetSpatialRef()
    code = srs.GetAuthorityCode(None) if srs else None
    ds = None
    return code


# Geometrias de teste reutilizaveis
SAMPLE_POLYGONS = [
    "POLYGON ((-45.0 -15.0, -44.0 -15.0, -44.0 -14.0, -45.0 -14.0, -45.0 -15.0))",
    "POLYGON ((-46.0 -16.0, -45.0 -16.0, -45.0 -15.0, -46.0 -15.0, -46.0 -16.0))",
    "POLYGON ((-47.0 -17.0, -46.0 -17.0, -46.0 -16.0, -47.0 -16.0, -47.0 -17.0))",
]

SAMPLE_FEATURES = [
    {
        "id": 101,
        "geometry_wkt": SAMPLE_POLYGONS[0],
        "attrs": {"idSeg": 1, "areaHa": 150.5, "grupo": "Irrigacao", "consolidado": 1},
    },
    {
        "id": 102,
        "geometry_wkt": SAMPLE_POLYGONS[1],
        "attrs": {"idSeg": 2, "areaHa": 200.3, "grupo": "Sequeiro", "consolidado": 0},
    },
    {
        "id": 103,
        "geometry_wkt": SAMPLE_POLYGONS[2],
        "attrs": {"idSeg": 3, "areaHa": 75.0, "grupo": "Irrigacao", "consolidado": 1},
    },
]
