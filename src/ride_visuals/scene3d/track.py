"""Ride geometry prepared for the 3D scenes: cleaning, altitude, encoding."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import pyarrow.parquet as pq

EARTH_RADIUS_M = 6_371_008.8
#: A fix further than this from both neighbours is treated as a GPS spike.
MAX_STEP_M = 2_000.0


class ElevationSampler(Protocol):
    """Anything that knows the ground height (m) at points; NaN where unknown."""

    def sample(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray: ...


def haversine_m(lon1: np.ndarray, lat1: np.ndarray, lon2: np.ndarray, lat2: np.ndarray) -> np.ndarray:
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    h = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))


def local_xy(lon: np.ndarray, lat: np.ndarray, origin: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """Equirectangular metres around ``origin`` (fine at ride scale)."""
    k = math.cos(math.radians(origin[1]))
    return (lon - origin[0]) * 111_320.0 * k, (lat - origin[1]) * 110_540.0


def from_local_xy(x: np.ndarray, y: np.ndarray, origin: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    k = math.cos(math.radians(origin[1]))
    return origin[0] + x / (111_320.0 * k), origin[1] + y / 110_540.0


def simplify_indices(x: np.ndarray, y: np.ndarray, tolerance: float) -> np.ndarray:
    """Ramer–Douglas–Peucker (iterative) on metric coordinates."""
    n = len(x)
    if n < 3:
        return np.arange(n)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        sx, sy = x[b] - x[a], y[b] - y[a]
        length = math.hypot(sx, sy)
        px = x[a + 1 : b] - x[a]
        py = y[a + 1 : b] - y[a]
        dist = np.hypot(px, py) if length < 1e-9 else np.abs(sx * py - sy * px) / length
        i = int(np.argmax(dist))
        if dist[i] > tolerance:
            mid = a + 1 + i
            keep[mid] = True
            stack.append((a, mid))
            stack.append((mid, b))
    return np.flatnonzero(keep)


def delta_encode(values: np.ndarray, scale: float) -> list[int]:
    """Integer deltas of round(values * scale): compact, lossless at that scale."""
    scaled = np.nan_to_num(np.asarray(values, dtype=float) * scale, nan=0.0, posinf=0.0, neginf=0.0)
    ints = np.round(scaled).astype(np.int64)
    return np.diff(ints, prepend=0).tolist()


@dataclass
class RideTrack:
    """One ride: positions, cumulative distance, altitude and elapsed time."""

    lon: np.ndarray
    lat: np.ndarray
    alt: np.ndarray
    dist: np.ndarray
    elapsed: np.ndarray

    @property
    def length_m(self) -> float:
        return float(self.dist[-1]) if len(self.dist) else 0.0

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return float(self.lon.min()), float(self.lat.min()), float(self.lon.max()), float(self.lat.max())

    @classmethod
    def from_parquet(cls, path: Path) -> RideTrack:
        table = pq.read_table(path, columns=["timestamp", "lat", "lon", "altitude"])
        frame = table.to_pandas()
        stamps = frame["timestamp"]
        elapsed = (
            (stamps - stamps.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
            if len(frame)
            else np.zeros(0)
        )
        return cls.from_arrays(
            frame["lon"].to_numpy(dtype=float),
            frame["lat"].to_numpy(dtype=float),
            frame["altitude"].to_numpy(dtype=float),
            elapsed,
        )

    @classmethod
    def from_arrays(
        cls,
        lon: np.ndarray,
        lat: np.ndarray,
        alt: np.ndarray | None = None,
        elapsed: np.ndarray | None = None,
    ) -> RideTrack:
        """Clean raw fixes: drop invalid ones, glitches and duplicates; unwrap longitudes."""
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        alt = np.full(len(lon), np.nan) if alt is None else np.asarray(alt, dtype=float)
        elapsed = np.arange(len(lon), dtype=float) if elapsed is None else np.asarray(elapsed, dtype=float)
        valid = (
            np.isfinite(lon) & np.isfinite(lat)
            & (np.abs(lat) <= 85.0) & (np.abs(lon) <= 180.0)
            # (0, 0) is what many devices write before the first fix.
            & ~((np.abs(lon) < 1e-9) & (np.abs(lat) < 1e-9))
        )
        lon, lat, alt, elapsed = lon[valid], lat[valid], alt[valid], elapsed[valid]
        if len(lon) == 0:
            return cls(lon, lat, alt, np.zeros(0), elapsed)
        # Rides crossing the antimeridian stay continuous (MapLibre accepts |lon| > 180).
        lon = np.degrees(np.unwrap(np.radians(lon)))
        if len(lon) >= 2:
            # Drop fixes that did not move first so duplicates never mask a neighbouring spike.
            step0 = np.concatenate([[0.0], haversine_m(lon[:-1], lat[:-1], lon[1:], lat[1:])])
            moved0 = np.concatenate([[True], step0[1:] > 0.5])
            lon, lat, alt, elapsed = lon[moved0], lat[moved0], alt[moved0], elapsed[moved0]
        if len(lon) >= 3:
            # A spike is a lone fix far from both neighbours that are close to
            # each other; a real gap (tunnel, recorder paused) is kept as is.
            step = haversine_m(lon[:-1], lat[:-1], lon[1:], lat[1:])
            bridge = haversine_m(lon[:-2], lat[:-2], lon[2:], lat[2:])
            spike = np.zeros(len(lon), dtype=bool)
            spike[1:-1] = (step[:-1] > MAX_STEP_M) & (step[1:] > MAX_STEP_M) & (bridge < MAX_STEP_M)
            lon, lat, alt, elapsed = lon[~spike], lat[~spike], alt[~spike], elapsed[~spike]
        step = np.concatenate([[0.0], haversine_m(lon[:-1], lat[:-1], lon[1:], lat[1:])])
        dist = np.cumsum(step)
        return cls(lon, lat, alt, dist, elapsed)

    def fill_altitude(self, sampler: ElevationSampler | None) -> RideTrack:
        """Fill missing altitude from the DEM (recordings without a barometer or GPS height)."""
        missing = ~np.isfinite(self.alt)
        if not missing.any():
            return self
        alt = self.alt.copy()
        if missing.mean() > 0.2 and sampler is not None:
            alt = sampler.sample(self.lon, self.lat)
            missing = ~np.isfinite(alt)
        if missing.all():
            alt = np.zeros(len(alt))
        elif missing.any():
            index = np.arange(len(alt))
            alt[missing] = np.interp(index[missing], index[~missing], alt[~missing])
        return RideTrack(self.lon, self.lat, alt, self.dist, self.elapsed)

    def smoothed_altitude(self, sigma_m: float = 60.0, step_m: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
        """Altitude resampled every ``step_m`` and smoothed over ``sigma_m`` (distance, altitude)."""
        if self.length_m <= 0:
            return np.zeros(1), self.alt[:1].copy() if len(self.alt) else np.zeros(1)
        grid = np.arange(0.0, self.length_m + step_m, step_m)
        alt = np.interp(grid, self.dist, self.alt)
        return grid, gaussian_smooth(alt, sigma_m / step_m)

    def encode(self, tolerance_m: float = 1.5, max_vertices: int = 24_000) -> dict[str, list[int]]:
        """Delta-encoded geometry (micro-degrees, decimetres) for the renderer."""
        origin = (float(self.lon.mean()), float(self.lat.mean()))
        x, y = local_xy(self.lon, self.lat, origin)
        tolerance = tolerance_m
        idx = simplify_indices(x, y, tolerance)
        while len(idx) > max_vertices:
            tolerance *= 1.6
            idx = simplify_indices(x, y, tolerance)
        return {
            "x": delta_encode(self.lon[idx], 1e6),
            "y": delta_encode(self.lat[idx], 1e6),
            "d": delta_encode(self.dist[idx], 10.0),
            "a": delta_encode(self.alt[idx], 10.0),
        }


def gaussian_smooth(values: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian filter (sigma in samples) with edge values held, NaN-free input."""
    values = np.asarray(values, dtype=float)
    if sigma <= 0.0 or len(values) < 3:
        return values.copy()
    radius = max(1, int(math.ceil(3.0 * sigma)))
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(values, radius, mode="edge")
    return np.convolve(padded, kernel, mode="valid")
