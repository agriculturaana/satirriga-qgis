from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MetodoGeometria:
    id: int
    id_seg: Optional[int] = None
    area_ha: Optional[float] = None
    grupo: Optional[str] = None
    consolidado: Optional[bool] = None
    homologado: Optional[bool] = None
    unique_hash: Optional[str] = None
    tile: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "MetodoGeometria":
        return cls(
            id=data.get("id", 0),
            id_seg=data.get("idSeg"),
            area_ha=data.get("areaHa"),
            grupo=data.get("grupo"),
            consolidado=data.get("consolidado"),
            homologado=data.get("homologado"),
            unique_hash=data.get("uniqueHash"),
            tile=data.get("tile"),
        )


@dataclass
class Metodo:
    id: int
    metodo_apply: str
    status: str
    mapeamento_id: Optional[int] = None
    total_geometrias: Optional[int] = None
    geometrias: List[MetodoGeometria] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Metodo":
        geoms_raw = data.get("metodoGeometrias") or data.get("geometrias") or []
        geometrias = [MetodoGeometria.from_dict(g) for g in geoms_raw]
        return cls(
            id=data.get("id", 0),
            metodo_apply=data.get("metodoApply", data.get("metodo_apply", "")),
            status=data.get("status", ""),
            mapeamento_id=data.get("mapeamentoId") or data.get("mapeamento_id"),
            total_geometrias=data.get("totalGeometrias"),
            geometrias=geometrias,
        )
