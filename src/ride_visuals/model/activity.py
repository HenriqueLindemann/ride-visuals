"""Modelo de dados de atividades consolidadas (nível atividade)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any


@dataclass
class ActivitySummary:
    """Metadados e resumo consolidado de uma atividade no catálogo."""
    id: int
    name: str
    start_date: datetime
    activity_type: str
    distance_m: float
    elevation_gain_m: float
    moving_time_s: int
    elapsed_time_s: int
    avg_speed_mps: Optional[float] = None
    max_speed_mps: Optional[float] = None
    avg_heart_rate: Optional[float] = None
    max_heart_rate: Optional[float] = None
    relative_effort: Optional[float] = None
    estimated_watts_avg: Optional[float] = None
    estimated_watts_max: Optional[float] = None
    temperature_avg: Optional[float] = None
    temperature_max: Optional[float] = None
    gear: Optional[str] = None
    source_filename: str = ""
    source_format: str = ""  # 'fit', 'tcx', 'gpx'
    file_sha256: str = ""
    point_count: int = 0
    has_hr_stream: bool = False
    has_speed_stream: bool = False
    has_temp_stream: bool = False
    has_watts_stream: bool = False
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "start_date": self.start_date.isoformat(),
            "activity_type": self.activity_type,
            "distance_m": self.distance_m,
            "elevation_gain_m": self.elevation_gain_m,
            "moving_time_s": self.moving_time_s,
            "elapsed_time_s": self.elapsed_time_s,
            "avg_speed_mps": self.avg_speed_mps,
            "max_speed_mps": self.max_speed_mps,
            "avg_heart_rate": self.avg_heart_rate,
            "max_heart_rate": self.max_heart_rate,
            "relative_effort": self.relative_effort,
            "estimated_watts_avg": self.estimated_watts_avg,
            "estimated_watts_max": self.estimated_watts_max,
            "temperature_avg": self.temperature_avg,
            "temperature_max": self.temperature_max,
            "gear": self.gear,
            "source_filename": self.source_filename,
            "source_format": self.source_format,
            "file_sha256": self.file_sha256,
            "point_count": self.point_count,
            "has_hr_stream": self.has_hr_stream,
            "has_speed_stream": self.has_speed_stream,
            "has_temp_stream": self.has_temp_stream,
            "has_watts_stream": self.has_watts_stream,
        }
