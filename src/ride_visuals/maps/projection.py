"""Small, shared Web Mercator projection helpers."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np


EARTH_RADIUS_M = 6_378_137.0
WEB_MERCATOR_MAX_LATITUDE = 85.05112878


def project_mercator(
    lon: float,
    lat: float,
    *,
    radius: float = EARTH_RADIUS_M,
    max_latitude: float = WEB_MERCATOR_MAX_LATITUDE,
) -> tuple[float, float]:
    """Project longitude/latitude degrees into spherical Mercator coordinates."""
    if not math.isfinite(lon) or not math.isfinite(lat):
        return math.nan, math.nan
    safe_latitude = max(-max_latitude, min(max_latitude, lat))
    latitude_radians = math.radians(safe_latitude)
    x = radius * math.radians(lon)
    y = (radius / 2.0) * math.log(
        (1.0 + math.sin(latitude_radians)) / (1.0 - math.sin(latitude_radians))
    )
    return x, y


def unproject_mercator(
    x: float,
    y: float,
    *,
    radius: float = EARTH_RADIUS_M,
) -> tuple[float, float]:
    """Invert spherical Mercator coordinates into longitude/latitude degrees."""
    lon = math.degrees(x / radius)
    lat = math.degrees(2.0 * math.atan(math.exp(y / radius)) - math.pi / 2.0)
    return lon, lat


def compute_map_viewport(
    xs: Sequence[float] | np.ndarray,
    ys: Sequence[float] | np.ndarray,
    *,
    axes_width: float,
    axes_height: float,
    margin_pct: float = 0.05,
) -> tuple[float, float, float, float]:
    """Compute aspect-ratio-matched viewport bounds (x_min, x_max, y_min, y_max)
    so routes maximally fill the available axes box with uniform relative margin.
    """
    if axes_width <= 0.0 or axes_height <= 0.0:
        raise ValueError("Map viewport dimensions must be positive")
    if margin_pct < 0.0:
        raise ValueError("Map viewport margin cannot be negative")

    arr_x = np.asarray(xs, dtype=float)
    arr_y = np.asarray(ys, dtype=float)
    valid = np.isfinite(arr_x) & np.isfinite(arr_y)
    if not np.any(valid):
        raise ValueError("No valid coordinates to compute map viewport")

    x_min, x_max = float(np.min(arr_x[valid])), float(np.max(arr_x[valid]))
    y_min, y_max = float(np.min(arr_y[valid])), float(np.max(arr_y[valid]))

    dx = max(x_max - x_min, 100.0)
    dy = max(y_max - y_min, 100.0)
    x_center = (x_min + x_max) / 2.0
    y_center = (y_min + y_max) / 2.0

    aspect_ratio = float(axes_width) / float(axes_height)
    padded_dx = dx * (1.0 + 2.0 * margin_pct)
    padded_dy = dy * (1.0 + 2.0 * margin_pct)

    if padded_dx / aspect_ratio >= padded_dy:
        span_x = padded_dx
        span_y = span_x / aspect_ratio
    else:
        span_y = padded_dy
        span_x = span_y * aspect_ratio

    return (
        x_center - span_x / 2.0,
        x_center + span_x / 2.0,
        y_center - span_y / 2.0,
        y_center + span_y / 2.0,
    )


def expand_viewport_to_canvas(
    bounds: tuple[float, float, float, float],
    *,
    content_rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Extend content bounds to a full canvas while preserving registration.

    ``content_rect`` uses Matplotlib figure fractions: left, bottom, width,
    height. Data stays fitted inside that safe area while the basemap continues
    beneath headers and legends to every canvas edge.
    """
    left, bottom, width, height = content_rect
    if width <= 0.0 or height <= 0.0:
        raise ValueError("Content rectangle dimensions must be positive")
    if left < 0.0 or bottom < 0.0 or left + width > 1.0 or bottom + height > 1.0:
        raise ValueError("Content rectangle must fit inside the canvas")

    x_min, x_max, y_min, y_max = bounds
    full_width = (x_max - x_min) / width
    full_height = (y_max - y_min) / height
    canvas_x_min = x_min - left * full_width
    canvas_y_min = y_min - bottom * full_height
    return (
        canvas_x_min,
        canvas_x_min + full_width,
        canvas_y_min,
        canvas_y_min + full_height,
    )
