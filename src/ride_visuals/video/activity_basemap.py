"""Georeferenced basemaps for individual activity renders."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Mapping, Sequence

from ride_visuals.maps.tiles import TILE_PROVIDERS, TileManager


def _mercator(lon: float, lat: float) -> tuple[float, float]:
    safe_lat = max(-85.0, min(85.0, lat))
    x = math.radians(lon)
    y = math.log(math.tan(math.pi / 4.0 + math.radians(safe_lat) / 2.0))
    return x, y


def _inverse_mercator(x: float, y: float) -> tuple[float, float]:
    lon = math.degrees(x)
    lat = math.degrees(2.0 * math.atan(math.exp(y)) - math.pi / 2.0)
    return lon, lat


def route_basemap_bounds(points: Sequence[Mapping[str, object]]) -> tuple[float, float, float, float]:
    """Return the geographic extent of the renderer's square route viewport.

    ``RouteMap.tsx`` fits the activity into an 880-unit box inside a 1000-unit
    square. Repeating that projection here makes a raster basemap line up with
    the SVG route without composition-specific pixel calculations.
    """

    projected = [
        _mercator(float(point["lon"]), float(point["lat"]))
        for point in points
        if point.get("lon") is not None and point.get("lat") is not None
    ]
    if len(projected) < 2:
        raise ValueError("At least two geographic points are required for an activity basemap")

    xs = [x for x, _ in projected]
    ys = [y for _, y in projected]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    data_w = max(max_x - min_x, 1e-9)
    data_h = max(max_y - min_y, 1e-9)
    scale = min(880.0 / data_w, 880.0 / data_h)
    offset_x = (1000.0 - data_w * scale) / 2.0
    offset_y = (1000.0 - data_h * scale) / 2.0

    view_min_x = min_x - offset_x / scale
    view_max_x = min_x + (1000.0 - offset_x) / scale
    view_min_y = min_y - offset_y / scale
    view_max_y = min_y + (1000.0 - offset_y) / scale
    min_lon, min_lat = _inverse_mercator(view_min_x, view_min_y)
    max_lon, max_lat = _inverse_mercator(view_max_x, view_max_y)
    return min_lon, min_lat, max_lon, max_lat


def canvas_basemap_bounds(
    points: Sequence[Mapping[str, object]],
    *,
    width: int,
    height: int,
    layout: str,
) -> tuple[float, float, float, float]:
    """Extend the route viewport extent to the edges of the video canvas."""

    min_lon, min_lat, max_lon, max_lat = route_basemap_bounds(points)
    view_min_x, view_min_y = _mercator(min_lon, min_lat)
    view_max_x, view_max_y = _mercator(max_lon, max_lat)
    view_span = view_max_x - view_min_x

    if layout == "telemetry":
        map_w = width if height > width else width * 0.70
        map_h = height * 0.60 if height > width else height
    elif layout == "clean":
        map_w = width
        map_h = height
    else:
        raise ValueError("Activity basemap layout must be 'telemetry' or 'clean'")

    svg_w = map_w * 0.90
    svg_h = map_h * 0.90
    side = min(svg_w, svg_h)
    square_x = map_w * 0.05 + (svg_w - side) / 2.0
    square_y = map_h * 0.05 + (svg_h - side) / 2.0

    canvas_min_x = view_min_x - square_x / side * view_span
    canvas_max_x = view_max_x + (width - square_x - side) / side * view_span
    canvas_min_y = view_min_y - (height - square_y - side) / side * view_span
    canvas_max_y = view_max_y + square_y / side * view_span
    canvas_min_lon, canvas_min_lat = _inverse_mercator(canvas_min_x, canvas_min_y)
    canvas_max_lon, canvas_max_lat = _inverse_mercator(canvas_max_x, canvas_max_y)
    return canvas_min_lon, canvas_min_lat, canvas_max_lon, canvas_max_lat


def render_activity_basemap(
    points: Sequence[Mapping[str, object]],
    output_path: Path,
    *,
    provider: str,
    width: int,
    height: int,
    layout: str,
    map_detail: str = "standard",
    tile_manager: TileManager | None = None,
) -> Path:
    """Render a full-canvas tile image aligned with ``RouteMap``."""

    if provider not in TILE_PROVIDERS:
        raise ValueError(f"Unsupported activity basemap provider: {provider}")
    if map_detail not in {"standard", "high"}:
        raise ValueError("Map detail must be 'standard' or 'high'")
    if width < 320 or height < 320:
        raise ValueError("Activity basemap dimensions must be at least 320 px")

    min_lon, min_lat, max_lon, max_lat = canvas_basemap_bounds(
        points,
        width=width,
        height=height,
        layout=layout,
    )
    manager = tile_manager or TileManager()
    image = manager.render_basemap_layer(
        min_lon,
        min_lat,
        max_lon,
        max_lat,
        width,
        height,
        provider=provider,
        dim_pct=0.0,
        detail_scale=2 if map_detail == "high" else 1,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
    return destination
