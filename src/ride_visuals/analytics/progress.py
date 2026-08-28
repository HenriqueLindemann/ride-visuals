"""Season-level metrics shared by reports and progress films."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ride_visuals.analytics.climbs import ClimbAnalyzer
from ride_visuals.analytics.drift import DriftAnalyzer
from ride_visuals.analytics.trimp import TRIMPAnalyzer
from ride_visuals.analytics.zones import HRZoneProfile
from ride_visuals.i18n import sanitize_display_text
from ride_visuals.selection import ActivitySelection


MAX_SENSOR_GAP_SECONDS = 10.0
SPEED_HISTOGRAM_MAX_KMH = 70.0
ROBUST_PEAK_PERCENTILE = 99.9


def _sample_durations_seconds(timestamps: pd.Series) -> np.ndarray:
    """Return local sample durations without counting long recording gaps."""
    parsed = pd.to_datetime(timestamps, utc=True, errors="coerce")
    if len(parsed) == 0:
        return np.array([], dtype=float)
    # Arrow-backed timestamps may be stored at microsecond rather than
    # nanosecond resolution. Timedelta conversion is unit-independent.
    seconds = (parsed - parsed.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
    if len(seconds) == 1:
        return np.ones(1, dtype=float)
    deltas = np.diff(seconds)
    ordinary = deltas[np.isfinite(deltas) & (deltas > 0.0) & (deltas <= MAX_SENSOR_GAP_SECONDS)]
    fallback = float(np.median(ordinary)) if len(ordinary) else 1.0
    deltas = np.where(
        np.isfinite(deltas) & (deltas > 0.0),
        np.minimum(deltas, MAX_SENSOR_GAP_SECONDS),
        fallback,
    )
    return np.concatenate((deltas, [fallback]))


def _safe_name(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return sanitize_display_text(value)


def _best_row(frame: pd.DataFrame, column: str) -> pd.Series | None:
    candidates = frame.dropna(subset=[column]).sort_values(column, ascending=False)
    return None if candidates.empty else candidates.iloc[0]


class SeasonAnalytics:
    """Calculate the canonical season metrics without depending on a renderer."""

    def __init__(
        self,
        catalog_db_path: Path,
        streams_dir: Path,
        *,
        selection: ActivitySelection | None = None,
    ) -> None:
        self.catalog_db_path = Path(catalog_db_path)
        self.streams_dir = Path(streams_dir)
        self.selection = selection or ActivitySelection()

    def extract(self) -> dict[str, Any]:
        where, parameters = self.selection.sql()
        with duckdb.connect(str(self.catalog_db_path), read_only=True) as connection:
            activities = connection.execute(
                f"SELECT * FROM activities{where} ORDER BY start_date", parameters
            ).fetchdf()
        if activities.empty:
            raise ValueError("No activities match the selected period")

        total_rides = len(activities)
        total_km = float(activities["distance_m"].sum() / 1000.0)
        total_elevation = float(activities["elevation_gain_m"].sum())
        total_hours = float(activities["moving_time_s"].sum() / 3600.0)

        activities["month"] = activities["start_date"].dt.strftime("%Y-%m")
        monthly = activities.groupby("month").agg(
            rides=("id", "count"),
            km=("distance_m", lambda values: float(values.sum() / 1000.0)),
            elev=("elevation_gain_m", "sum"),
            hours=("moving_time_s", lambda values: float(values.sum() / 3600.0)),
            avg_hr=("avg_heart_rate", "mean"),
        ).reset_index()

        activities["week_start"] = (
            activities["start_date"]
            - pd.to_timedelta(activities["start_date"].dt.weekday, unit="D")
        ).dt.normalize()
        weekly = activities.groupby("week_start").agg(
            rides=("id", "count"),
            km=("distance_m", lambda values: float(values.sum() / 1000.0)),
        )
        complete_weeks = pd.date_range(
            activities["week_start"].min(),
            activities["week_start"].max(),
            freq="7D",
        )
        weekly = weekly.reindex(complete_weeks, fill_value=0).rename_axis("week_start").reset_index()
        weekly["rolling_km"] = weekly["km"].rolling(4, min_periods=1).mean()
        weekly["week_start"] = weekly["week_start"].dt.strftime("%Y-%m-%d")

        all_heart_rates: list[float] = []
        all_heart_rate_durations: list[float] = []
        all_speeds_kmh: list[float] = []
        all_temperatures: list[float] = []
        drifts: list[float] = []
        climbs: list[dict[str, float]] = []
        rides_with_hr = 0
        trimp_analyzer = TRIMPAnalyzer()
        monthly_trimp = {month: 0.0 for month in monthly["month"]}
        activity_speed_peaks: list[tuple[float, str]] = []

        for _, activity in activities.iterrows():
            stream_path = self.streams_dir / f"{activity['id']}.parquet"
            if not stream_path.exists():
                continue
            stream = pq.read_table(
                stream_path,
                columns=[
                    "heart_rate_bpm", "speed_mps", "temperature_c", "altitude",
                    "timestamp", "quality_flags",
                ],
            ).to_pandas()
            durations = _sample_durations_seconds(stream["timestamp"])
            heart_rate_values = pd.to_numeric(
                stream["heart_rate_bpm"], errors="coerce"
            ).to_numpy(dtype=float)
            heart_rate_valid = np.isfinite(heart_rate_values)
            heart_rates = heart_rate_values[heart_rate_valid]
            if np.any(heart_rate_valid):
                rides_with_hr += 1
            all_heart_rates.extend(heart_rate_values)
            all_heart_rate_durations.extend(durations)

            speeds_kmh = pd.to_numeric(stream["speed_mps"], errors="coerce").to_numpy(dtype=float) * 3.6
            quality_ok = stream["quality_flags"].fillna("ok").to_numpy() != "gps_glitch"
            valid_speeds = speeds_kmh[np.isfinite(speeds_kmh) & (speeds_kmh >= 0.0) & quality_ok]
            all_speeds_kmh.extend(valid_speeds)
            chart_speeds = valid_speeds[valid_speeds <= SPEED_HISTOGRAM_MAX_KMH]
            if len(chart_speeds):
                activity_speed_peaks.append((
                    float(np.percentile(chart_speeds, ROBUST_PEAK_PERCENTILE)),
                    _safe_name(activity["name"]),
                ))
            temperatures = stream["temperature_c"].dropna().values
            all_temperatures.extend(temperatures[np.isfinite(temperatures)])

            drift = DriftAnalyzer.calculate_aerobic_drift(
                stream["speed_mps"].values,
                stream["heart_rate_bpm"].values,
            )
            if drift["valid"]:
                drifts.append(float(drift["drift_pct"]))

            parsed_timestamps = pd.to_datetime(stream["timestamp"], utc=True, errors="coerce")
            timestamps = (
                parsed_timestamps - parsed_timestamps.iloc[0]
            ).dt.total_seconds().to_numpy(dtype=float)
            climbs.extend(ClimbAnalyzer.calculate_climb_vam(stream["altitude"].values, timestamps))

            month = activity["month"]
            monthly_trimp[month] = monthly_trimp.get(month, 0.0) + trimp_analyzer.calculate_activity_trimp(
                heart_rates,
                float(np.sum(durations[heart_rate_valid])) / 60.0,
            )

        all_heart_rate_values = np.asarray(all_heart_rates, dtype=float)
        all_heart_rate_weights = np.asarray(all_heart_rate_durations, dtype=float)
        zone_distribution = HRZoneProfile().calculate_time_in_zones(
            all_heart_rate_values,
            all_heart_rate_weights,
        )
        speed_samples = np.asarray(all_speeds_kmh, dtype=float)
        chart_speed_samples = speed_samples[speed_samples <= SPEED_HISTOGRAM_MAX_KMH]
        heart_rate_samples = all_heart_rate_values[np.isfinite(all_heart_rate_values)]
        temperature_samples = np.asarray(all_temperatures, dtype=float)
        speed_hist_counts, speed_hist_edges = np.histogram(
            chart_speed_samples,
            bins=np.linspace(0, SPEED_HISTOGRAM_MAX_KMH, 15),
        )
        longest = activities.sort_values("distance_m", ascending=False).iloc[0]
        highest = activities.sort_values("elevation_gain_m", ascending=False).iloc[0]
        sustained_candidates = activities[activities["distance_m"] >= 20_000]
        sustained = _best_row(sustained_candidates, "avg_speed_mps")
        if sustained is None:
            sustained = _best_row(activities, "avg_speed_mps")
        hardest = _best_row(activities, "relative_effort")
        highest_hr = _best_row(activities, "max_heart_rate")
        robust_peak, robust_peak_name = max(activity_speed_peaks, default=(0.0, ""))

        return {
            "total_rides": total_rides,
            "total_km": round(total_km, 1),
            "total_elev_m": round(total_elevation),
            "total_hours": round(total_hours, 1),
            "rides_with_hr": rides_with_hr,
            "sample_counts": {
                "total": int(activities["point_count"].fillna(0).sum()),
                "speed": int(len(speed_samples)),
                "heart_rate": int(len(heart_rate_samples)),
                "temperature": int(len(temperature_samples)),
            },
            "activity_avg_speeds_kmh": [
                float(value * 3.6) for value in activities["avg_speed_mps"].dropna().values
            ],
            "speed_stats": {
                "median": round(float(np.percentile(chart_speed_samples, 50)), 1) if len(chart_speed_samples) > 0 else 0.0,
                "p90": round(float(np.percentile(chart_speed_samples, 90)), 1) if len(chart_speed_samples) > 0 else 0.0,
                "p99": round(float(np.percentile(chart_speed_samples, 99)), 1) if len(chart_speed_samples) > 0 else 0.0,
                "peak": round(robust_peak, 1),
            },
            "speed_histogram": {
                "counts": speed_hist_counts.tolist(),
                "edges": speed_hist_edges.tolist(),
            },
            "heart_rate_stats": {
                "median": round(float(np.percentile(heart_rate_samples, 50))) if len(heart_rate_samples) > 0 else 0,
                "p90": round(float(np.percentile(heart_rate_samples, 90))) if len(heart_rate_samples) > 0 else 0,
                "peak": (
                    round(float(activities["max_heart_rate"].max()))
                    if pd.notna(activities["max_heart_rate"].max()) else 0
                ),
            },
            "temperature_stats": {
                "p10": round(float(np.percentile(temperature_samples, 10))) if len(temperature_samples) > 0 else None,
                "p90": round(float(np.percentile(temperature_samples, 90))) if len(temperature_samples) > 0 else None,
                "min": round(float(np.min(temperature_samples))) if len(temperature_samples) > 0 else None,
                "max": round(float(np.max(temperature_samples))) if len(temperature_samples) > 0 else None,
            },
            "monthly": monthly.to_dict(orient="records"),
            "weekly": weekly.to_dict(orient="records"),
            "monthly_trimp": monthly_trimp,
            "zones_pct": {
                f"Z{index}": zone_distribution[f"z{index}_pct"]
                for index in range(1, 6)
            },
            "avg_drift_pct": round(float(np.mean(drifts)), 2) if drifts else 0.0,
            "top_climbs_count": len(climbs),
            "avg_climb_vam": (
                round(float(np.mean([climb["vam_mh"] for climb in climbs])), 1)
                if climbs else 0.0
            ),
            "records": {
                "longest_km": round(float(longest["distance_m"]) / 1000.0, 1),
                "longest_name": _safe_name(longest["name"]),
                "highest_elev_m": round(float(highest["elevation_gain_m"])),
                "highest_elev_name": _safe_name(highest["name"]),
                "max_speed_kmh": round(robust_peak, 1),
                "max_speed_name": robust_peak_name,
                "fastest_sustained_kmh": (
                    round(float(sustained["avg_speed_mps"]) * 3.6, 1)
                    if sustained is not None else None
                ),
                "fastest_sustained_name": _safe_name(sustained["name"]) if sustained is not None else "",
                "highest_effort": (
                    round(float(hardest["relative_effort"])) if hardest is not None else None
                ),
                "highest_effort_name": _safe_name(hardest["name"]) if hardest is not None else "",
                "peak_hr": round(float(highest_hr["max_heart_rate"])) if highest_hr is not None else None,
                "peak_hr_name": _safe_name(highest_hr["name"]) if highest_hr is not None else "",
            },
        }
