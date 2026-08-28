"""Georeferenced basemaps for individual activity renders."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from ride_visuals.maps.tiles import TILE_PROVIDERS, TileManager
from ride_visuals.maps.projection import project_mercator, unproject_mercator


def _mercator(lon: float, lat: float) -> tuple[float, float]:
    return project_mercator(lon, lat, radius=1.0, max_latitude=85.0)


def _inverse_mercator(x: float, y: float) -> tuple[float, float]:
    return unproject_mercator(x, y, radius=1.0)


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
    show_progress_bar: bool = False,
) -> tuple[float, float, float, float]:
    """Extend the route viewport extent to the edges of its map partition,

    matching the exact container padding and projection of RouteMap.tsx.
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

    vertical = height > width
    scale_factor = height / (1920.0 if vertical else 1080.0)
    # Mirrors renderer/src/design/layout.ts (MAP_SHARE_PORTRAIT / PANEL_SHARE_LANDSCAPE
    # / mapPadding) so basemap tiles stay registered with RouteMap.tsx.
    if layout == "telemetry":
        view_w = width if vertical else int(round(width * 0.70))
        view_h = int(round(height * 0.50)) if vertical else height
        top_pad = int(round((56 if vertical else 64) * scale_factor))
        bottom_pad = int(round((56 if vertical else 64) * scale_factor))
        side_pad = int(round((56 if vertical else 64) * scale_factor))
    elif layout == "clean":
        view_w = width
        view_h = height
        top_pad = int(round((150 if vertical else 140) * scale_factor))
        bottom_pad = int(round((75 if show_progress_bar else 48) * scale_factor))
        side_pad = int(round((48 if vertical else 64) * scale_factor))
    else:
        raise ValueError("Activity basemap layout must be 'telemetry' or 'clean'")

    usable_w = max(view_w - 2 * side_pad, 10)
    usable_h = max(view_h - top_pad - bottom_pad, 10)
    scale = min(usable_w / data_w, usable_h / data_h)

    rendered_w = data_w * scale
    rendered_h = data_h * scale

    offset_x = side_pad + (usable_w - rendered_w) / 2.0
    offset_y = top_pad + (usable_h - rendered_h) / 2.0

    # Extend the same georeferenced plane beneath the telemetry panel. Route
    # coordinates still use the map partition's fit and remain registered.
    canvas_min_x = min_x + (0.0 - offset_x) / scale
    canvas_max_x = min_x + (float(width) - offset_x) / scale
    canvas_max_y = max_y - (0.0 - offset_y) / scale
    canvas_min_y = max_y - (float(height) - offset_y) / scale

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
    show_progress_bar: bool = False,
    tile_manager: TileManager | None = None,
) -> Path:
    """Render a full-canvas tile image aligned to the route partition."""

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
        show_progress_bar=show_progress_bar,
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
