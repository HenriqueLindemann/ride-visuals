"""Modelo e schema de trackpoints e séries temporais (nível stream/ponto)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import pyarrow as pa


@dataclass
class TrackPoint:
    """Um ponto de telemetria com procedência explícita."""
    timestamp: datetime
    lat: float
    lon: float
    altitude: Optional[float] = None
    distance_m: Optional[float] = None
    speed_mps: Optional[float] = None
    heart_rate_bpm: Optional[float] = None
    power_watts: Optional[float] = None
    cadence_rpm: Optional[float] = None
    temperature_c: Optional[float] = None
    grade_pct: Optional[float] = None
    bearing_deg: Optional[float] = None
    provenance_speed: str = "none"      # 'measured', 'derived', 'none'
    provenance_power: str = "none"      # 'measured', 'provider_estimated', 'unknown', 'none'
    provenance_temp: str = "none"       # 'sensor', 'weather_model', 'none'
    quality_flags: str = "ok"           # 'ok', 'interpolated', 'gps_glitch'


# Schema estrito do Apache Arrow / Parquet para serialização sem perdas
STREAM_ARROW_SCHEMA = pa.schema([
    ("timestamp", pa.timestamp("ms", tz="UTC")),
    ("lat", pa.float64()),
    ("lon", pa.float64()),
    ("altitude", pa.float64()),
    ("distance_m", pa.float64()),
    ("speed_mps", pa.float64()),
    ("heart_rate_bpm", pa.float64()),
    ("power_watts", pa.float64()),
    ("cadence_rpm", pa.float64()),
    ("temperature_c", pa.float64()),
    ("grade_pct", pa.float64()),
    ("bearing_deg", pa.float64()),
    ("provenance_speed", pa.string()),
    ("provenance_power", pa.string()),
    ("provenance_temp", pa.string()),
    ("quality_flags", pa.string()),
])
