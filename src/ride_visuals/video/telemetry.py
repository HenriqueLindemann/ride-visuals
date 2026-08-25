"""Canonical, time-aware telemetry timeline for renderers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


def _numeric(frame: pd.DataFrame, column: str, scale: float = 1.0) -> np.ndarray:
    if column not in frame:
        return np.full(len(frame), np.nan, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float) * scale


def _time_rolling(
    values: np.ndarray,
    timestamps: pd.DatetimeIndex,
    window_seconds: int,
) -> np.ndarray:
    """Smooth over actual elapsed time while preserving completely missing streams."""
    if len(values) < 2 or np.all(np.isnan(values)):
        return values.copy()
    series = pd.Series(values, index=timestamps)
    return (
        series.rolling(f"{window_seconds}s", min_periods=1)
        .mean()
        .to_numpy(dtype=float)
    )


def adaptive_speed_window_seconds(
    source_duration_seconds: float,
    render_duration_seconds: float,
    fps: int = 30,
    visual_frames: int = 10,
) -> int:
    """Choose a source-time window that remains stable after time compression.

    Ten rendered frames is long enough to prevent one-frame numerical flicker.
    The result is bounded so short rides stay responsive and long rides do not
    collapse into a season-wide average.
    """
    source_duration = max(float(source_duration_seconds), 1.0)
    rendered_frames = max(float(render_duration_seconds) * max(int(fps), 1), 1.0)
    proposed = source_duration / rendered_frames * max(int(visual_frames), 1)
    upper_bound = max(30.0, min(1200.0, source_duration * 0.10))
    return int(round(min(max(proposed, 30.0), upper_bound)))


@dataclass(frozen=True)
class TelemetryTimeline:
    timestamps: pd.DatetimeIndex
    elapsed_s: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    altitude_m: np.ndarray
    distance_km: np.ndarray
    speed_kmh: np.ndarray
    speed_3min_kmh: np.ndarray
    heart_rate_bpm: np.ndarray
    power_watts: np.ndarray
    temperature_c: np.ndarray
    grade_pct: np.ndarray
    bearing_deg: np.ndarray

    @classmethod
    def from_parquet(cls, path: Path, *, speed_window_seconds: int = 180) -> "TelemetryTimeline":
        return cls.from_frame(
            pq.read_table(path).to_pandas(),
            speed_window_seconds=speed_window_seconds,
        )

    @classmethod
    def from_frame(cls, source: pd.DataFrame, *, speed_window_seconds: int = 180) -> "TelemetryTimeline":
        if source.empty or not {"timestamp", "lat", "lon"}.issubset(source.columns):
            raise ValueError("Telemetry requires timestamp, lat and lon columns")

        frame = source.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["timestamp", "lat", "lon"]).sort_values("timestamp")
        frame = frame.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        if frame.empty:
            raise ValueError("Telemetry has no valid timestamped coordinates")

        timestamps = pd.DatetimeIndex(frame["timestamp"])
        elapsed = (timestamps - timestamps[0]).total_seconds().to_numpy(dtype=float)
        speed = _numeric(frame, "speed_mps", 3.6)
        heart_rate = _numeric(frame, "heart_rate_bpm")
        power = _numeric(frame, "power_watts")
        temperature = _numeric(frame, "temperature_c")
        grade = _numeric(frame, "grade_pct")

        return cls(
            timestamps=timestamps,
            elapsed_s=elapsed,
            lat=_numeric(frame, "lat"),
            lon=_numeric(frame, "lon"),
            altitude_m=_numeric(frame, "altitude"),
            distance_km=_numeric(frame, "distance_m", 0.001),
            speed_kmh=_time_rolling(speed, timestamps, 12),
            # Kept under the v1 field name for render-contract compatibility;
            # the effective window is supplied by the render profile.
            speed_3min_kmh=_time_rolling(speed, timestamps, speed_window_seconds),
            heart_rate_bpm=_time_rolling(heart_rate, timestamps, 12),
            power_watts=_time_rolling(power, timestamps, 5),
            temperature_c=_time_rolling(temperature, timestamps, 60),
            grade_pct=_time_rolling(grade, timestamps, 15),
            bearing_deg=_numeric(frame, "bearing_deg"),
        )

    def __len__(self) -> int:
        return len(self.timestamps)

    @property
    def duration_s(self) -> float:
        return float(self.elapsed_s[-1]) if len(self.elapsed_s) else 0.0

    def index_at(self, progress: float) -> int:
        """Resolve animation progress against elapsed time, not point count."""
        target = min(max(progress, 0.0), 1.0) * self.duration_s
        return min(int(np.searchsorted(self.elapsed_s, target, side="right")), len(self) - 1)

    def history_indices(self, index: int, seconds: int = 180, samples: int = 72) -> np.ndarray:
        start_time = max(0.0, self.elapsed_s[index] - seconds)
        start = int(np.searchsorted(self.elapsed_s, start_time, side="left"))
        count = max(2, min(samples, index - start + 1))
        return np.linspace(start, index, num=count, dtype=int)

    @staticmethod
    def available(values: np.ndarray) -> bool:
        return int(np.count_nonzero(~np.isnan(values))) >= 2

    @staticmethod
    def value(values: np.ndarray, index: int) -> float | None:
        value = float(values[index])
        return None if np.isnan(value) else value

    @property
    def total_distance_km(self) -> float:
        valid = self.distance_km[~np.isnan(self.distance_km)]
        return float(valid[-1]) if len(valid) else 0.0

    @property
    def elevation_gain_m(self) -> float:
        if not self.available(self.altitude_m):
            return 0.0
        smooth = _time_rolling(self.altitude_m, self.timestamps, 15)
        valid = smooth[~np.isnan(smooth)]
        return float(np.maximum(np.diff(valid), 0.0).sum()) if len(valid) > 1 else 0.0

    def elevation_gain_series_m(self) -> np.ndarray:
        """Cumulative smoothed elevation gain aligned with each timeline index."""
        count = len(self.altitude_m)
        series = np.zeros(count, dtype=float)
        if count < 2 or not self.available(self.altitude_m):
            return series
        smooth = _time_rolling(self.altitude_m, self.timestamps, 15)
        delta = np.diff(smooth)
        step = np.where(np.isnan(delta), 0.0, np.maximum(delta, 0.0))
        series[1:] = np.cumsum(step)
        return series
