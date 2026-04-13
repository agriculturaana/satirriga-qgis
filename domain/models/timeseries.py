"""Modelos de dominio para serie temporal."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TimeSeriesPoint:
    """Ponto de consulta para serie temporal."""
    id: int
    color: str
    lon: float
    lat: float


@dataclass
class TimeSeriesDataset:
    """Dados temporais retornados pela API para um ponto."""
    dates: List[str] = field(default_factory=list)
    evi: List[Optional[float]] = field(default_factory=list)
    evi_original: List[Optional[float]] = field(default_factory=list)
    ndvi: List[Optional[float]] = field(default_factory=list)
    ndvi_original: List[Optional[float]] = field(default_factory=list)
    precipitation: List[Optional[float]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "TimeSeriesDataset":
        # API retorna "evi_orginal"/"ndvi_orginal" (typo sem o 'i')
        return cls(
            dates=data.get("dates", []),
            evi=data.get("evi", []),
            evi_original=data.get("evi_orginal") or data.get("evi_original", []),
            ndvi=data.get("ndvi", []),
            ndvi_original=data.get("ndvi_orginal") or data.get("ndvi_original", []),
            precipitation=data.get("precipitation", []),
        )


@dataclass
class TimeSeriesResult:
    """Resultado de serie temporal para um ponto especifico."""
    id: int
    label: str
    color: str
    data: TimeSeriesDataset

    @classmethod
    def from_dict(cls, data: dict) -> "TimeSeriesResult":
        ts_data = data.get("data", {})
        return cls(
            id=data.get("id", 0),
            label=data.get("label", ""),
            color=data.get("color", "#4C63B6"),
            data=TimeSeriesDataset.from_dict(ts_data),
        )
