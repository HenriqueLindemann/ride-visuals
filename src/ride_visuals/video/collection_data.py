"""Typed loading and projection for collection videos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ride_visuals.maps.projection import project_mercator
from ride_visuals.selection import ActivitySelection
from ride_visuals.video.layout import VideoPartitionLayout


@dataclass(frozen=True)
class CollectionTrack:
    id: int
    name: str | None
    date: datetime
    dist_km: float
    elev_m: float
    xs: np.ndarray
    ys: np.ndarray
    elapsed_s: np.ndarray
    distances_m: np.ndarray
    ascents_m: np.ndarray
    altitudes: np.ndarray
    hrs: np.ndarray
    speeds: np.ndarray
    temperatures: np.ndarray
    grades: np.ndarray


@dataclass(frozen=True)
class ProjectedCollectionTrack(CollectionTrack):
    pixel_points: tuple[tuple[int, int], ...]
    point_elapsed_s: np.ndarray
    point_distances_m: np.ndarray
    point_ascents_m: np.ndarray
    point_altitudes: np.ndarray
    point_hrs: np.ndarray
    point_speeds_kmh: np.ndarray
    point_temperatures: np.ndarray
    point_grades: np.ndarray


@dataclass(frozen=True)
class CollectionProjection:
    tracks: tuple[ProjectedCollectionTrack, ...]
    scale: float
    geo_center_x: float
    geo_center_y: float
    pixel_center_x: float
    pixel_center_y: float


def load_collection_tracks(
    catalog_db_path: Path,
    streams_dir: Path,
    selection: ActivitySelection,
) -> list[CollectionTrack]:
    """Load selected activity summaries and their point streams."""
    where, parameters = selection.sql()
    with duckdb.connect(str(catalog_db_path), read_only=True) as connection:
        activities = connection.execute(
            "SELECT id, name, start_date, distance_m, elevation_gain_m "
            f"FROM activities{where} ORDER BY start_date",
            parameters,
        ).fetchdf()

    tracks: list[CollectionTrack] = []
    for _, row in activities.iterrows():
        activity_id = int(row["id"])
        stream_path = Path(streams_dir) / f"{activity_id}.parquet"
        if not stream_path.exists():
            continue
        columns = [
            "timestamp", "lat", "lon", "distance_m", "heart_rate_bpm",
            "speed_mps", "temperature_c", "grade_pct", "altitude",
        ]
        available_columns = set(pq.ParquetFile(stream_path).schema_arrow.names)
        if "quality_flags" in available_columns:
            columns.append("quality_flags")
        stream = pq.read_table(stream_path, columns=columns).to_pandas()
        if stream.empty:
            continue

        timestamps = pd.to_datetime(stream["timestamp"], utc=True)
        elapsed = (timestamps - timestamps.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
        latitudes = stream["lat"].to_numpy(dtype=float).copy()
        longitudes = stream["lon"].to_numpy(dtype=float).copy()
        if "quality_flags" in stream:
            gps_glitches = stream["quality_flags"].fillna("ok").eq("gps_glitch").to_numpy()
            latitudes[gps_glitches] = np.nan
            longitudes[gps_glitches] = np.nan
        projected = [project_mercator(lon, lat) for lat, lon in zip(latitudes, longitudes)]
        xs = np.asarray([point[0] for point in projected], dtype=float)
        ys = np.asarray([point[1] for point in projected], dtype=float)

        altitudes = stream["altitude"].to_numpy(dtype=float)
        smoothed_altitudes = (
            pd.Series(altitudes).interpolate(limit_direction="both")
            .rolling(5, center=True, min_periods=1).median().to_numpy(dtype=float)
        )
        raw_gain = np.concatenate(
            ([0.0], np.cumsum(np.maximum(np.diff(smoothed_altitudes), 0.0)))
        )
        catalog_gain = float(row["elevation_gain_m"])
        cumulative_ascent = (
            raw_gain * (catalog_gain / raw_gain[-1])
            if raw_gain[-1] > 0.0 else np.zeros(len(stream), dtype=float)
        )

        tracks.append(CollectionTrack(
            id=activity_id,
            name=row["name"],
            date=row["start_date"],
            dist_km=float(row["distance_m"]) / 1000.0,
            elev_m=catalog_gain,
            xs=xs,
            ys=ys,
            elapsed_s=elapsed,
            distances_m=stream["distance_m"].to_numpy(dtype=float),
            ascents_m=cumulative_ascent,
            altitudes=altitudes,
            hrs=stream["heart_rate_bpm"].to_numpy(dtype=float),
            speeds=stream["speed_mps"].to_numpy(dtype=float),
            temperatures=stream["temperature_c"].to_numpy(dtype=float),
            grades=stream["grade_pct"].to_numpy(dtype=float),
        ))
    return tracks


def project_collection_tracks(
    tracks: list[CollectionTrack],
    layout: VideoPartitionLayout,
    *,
    margin_px: int,
) -> CollectionProjection:
    """Project every route into one shared, isometric collection viewport."""
    valid_xs = [track.xs[np.isfinite(track.xs)] for track in tracks if len(track.xs)]
    valid_ys = [track.ys[np.isfinite(track.ys)] for track in tracks if len(track.ys)]
    if not valid_xs or not valid_ys:
        raise ValueError("Collection routes have no valid geographic coordinates")

    all_xs = np.concatenate(valid_xs)
    all_ys = np.concatenate(valid_ys)
    min_x, max_x = float(np.min(all_xs)), float(np.max(all_xs))
    min_y, max_y = float(np.min(all_ys)), float(np.max(all_ys))
    dx = max(max_x - min_x, 1.0)
    dy = max(max_y - min_y, 1.0)
    usable_w = max(layout.map_rect.w - 2 * margin_px, 10)
    usable_h = max(layout.map_rect.h - 2 * margin_px, 10)
    scale = min(usable_w / dx, usable_h / dy)
    geo_center_x = (min_x + max_x) / 2.0
    geo_center_y = (min_y + max_y) / 2.0
    pixel_center_x = layout.map_rect.x0 + layout.map_rect.w / 2.0
    pixel_center_y = layout.map_rect.y0 + layout.map_rect.h / 2.0

    projected_tracks: list[ProjectedCollectionTrack] = []
    for track in tracks:
        pixel_xs = pixel_center_x + (track.xs - geo_center_x) * scale
        pixel_ys = pixel_center_y - (track.ys - geo_center_y) * scale
        valid = np.isfinite(pixel_xs) & np.isfinite(pixel_ys)
        pixel_points = tuple(
            (int(round(x)), int(round(y)))
            for x, y in zip(pixel_xs[valid], pixel_ys[valid])
        )
        projected_tracks.append(ProjectedCollectionTrack(
            **vars(track),
            pixel_points=pixel_points,
            point_elapsed_s=track.elapsed_s[valid],
            point_distances_m=track.distances_m[valid],
            point_ascents_m=track.ascents_m[valid],
            point_altitudes=track.altitudes[valid],
            point_hrs=track.hrs[valid],
            point_speeds_kmh=track.speeds[valid] * 3.6,
            point_temperatures=track.temperatures[valid],
            point_grades=track.grades[valid],
        ))

    return CollectionProjection(
        tracks=tuple(projected_tracks),
        scale=scale,
        geo_center_x=geo_center_x,
        geo_center_y=geo_center_y,
        pixel_center_x=pixel_center_x,
        pixel_center_y=pixel_center_y,
    )
