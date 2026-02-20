from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class ZonalGeometria:
    id: int
    evi: Optional[float] = None
    ndvi: Optional[float] = None
    ndwi: Optional[float] = None
    albedo: Optional[float] = None
    evi_20: Optional[float] = None
    ndvi_20: Optional[float] = None
    ndwi_20: Optional[float] = None
    albedo_20: Optional[float] = None
    scan_date: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "ZonalGeometria":
        return cls(
            id=data.get("id", 0),
            evi=data.get("evi"),
            ndvi=data.get("ndvi"),
            ndwi=data.get("ndwi"),
            albedo=data.get("albedo"),
            evi_20=data.get("evi20"),
            ndvi_20=data.get("ndvi20"),
            ndwi_20=data.get("ndwi20"),
            albedo_20=data.get("albedo20"),
            scan_date=data.get("scanDate"),
        )


@dataclass
class Zonal:
    id: int
    metodo_id: int
    status: str
    geometrias: list = None

    def __post_init__(self):
        if self.geometrias is None:
            self.geometrias = []

    @classmethod
    def from_dict(cls, data: dict) -> "Zonal":
        geoms_raw = data.get("zonalGeometrias") or data.get("geometrias") or []
        geometrias = [ZonalGeometria.from_dict(g) for g in geoms_raw]
        return cls(
            id=data.get("id", 0),
            metodo_id=data.get("metodoId", data.get("metodo_id", 0)),
            status=data.get("status", ""),
            geometrias=geometrias,
        )


@dataclass
class CatalogoItem:
    id: int
    descricao: str
    status: str
    processed_at: Optional[str] = None
    result_count: int = 0
    total_area_ha: float = 0.0
    bbox: Optional[List[float]] = None

    @classmethod
    def from_dict(cls, data: dict) -> "CatalogoItem":
        return cls(
            id=data.get("id", 0),
            descricao=data.get("descricao", ""),
            status=data.get("status", ""),
            processed_at=data.get("processedAt"),
            result_count=data.get("resultCount", 0),
            total_area_ha=data.get("totalAreaHa", 0.0),
            bbox=data.get("bbox"),
        )
