"""Route and legend painting primitives for collection videos."""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence

import numpy as np
from PIL import Image, ImageDraw

from ride_visuals.design import (
    ALTITUDE_COLORS,
    EFFORT_COLORS,
    GRADE_COLORS,
    SPEED_COLORS,
    TEMPERATURE_COLORS,
    VisualTheme,
    route_color,
)
from ride_visuals.i18n import Translator
from ride_visuals.video.collection_data import ProjectedCollectionTrack
from ride_visuals.video.fonts import FontManager
from ride_visuals.video.layout import VideoPartitionLayout


DATA_STYLE_SPECS: dict[str, dict[str, Any]] = {
    "heart_rate": {
        "field": "point_hrs",
        "thresholds": (132.0, 150.0, 165.0, 175.0),
        "colors": EFFORT_COLORS,
        "labels": ("<132", "132–149", "150–164", "165–174", "≥175"),
        "legend_key": "collection.legend.effort",
    },
    "temperature": {
        "field": "point_temperatures",
        "thresholds": (15.0, 20.0, 25.0, 30.0),
        "colors": TEMPERATURE_COLORS,
        "labels": ("<15", "15–19", "20–24", "25–29", "≥30"),
        "legend_key": "collection.legend.temperature",
    },
    "speed": {
        "field": "point_speeds_kmh",
        "thresholds": (15.0, 22.0, 28.0, 35.0),
        "colors": SPEED_COLORS,
        "labels": ("<15", "15–21", "22–27", "28–34", "≥35"),
        "legend_key": "collection.legend.speed",
    },
    "grade": {
        "field": "point_grades",
        "thresholds": (-5.0, -1.0, 1.0, 5.0),
        "colors": GRADE_COLORS,
        "labels": ("<−5", "−5–−1", "−1–1", "1–5", "≥5"),
        "legend_key": "collection.legend.grade",
    },
    "altitude": {
        "field": "point_altitudes",
        "thresholds": (150.0, 250.0, 350.0, 425.0),
        "colors": ALTITUDE_COLORS,
        "labels": ("<150", "150–249", "250–349", "350–424", "≥425"),
        "legend_key": "collection.legend.altitude",
    },
}


def route_metric_color(style: str, value: Optional[float]) -> Optional[str]:
    """Return the discrete semantic color for one recorded route sample."""
    if style not in DATA_STYLE_SPECS:
        raise ValueError(f"Unsupported data route style: {style}")
    if value is None or not np.isfinite(value):
        return None
    spec = DATA_STYLE_SPECS[style]
    index = int(np.searchsorted(spec["thresholds"], float(value), side="right"))
    return str(spec["colors"][index])


def draw_dashed_path(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[int, int]],
    *,
    fill: str,
    width: int,
    dash: int,
    gap: int,
) -> None:
    """Draw a distance-based dashed polyline, independent of sample density."""
    period = dash + gap
    distance_along = 0.0
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        segment_length = math.hypot(dx, dy)
        if segment_length == 0:
            continue
        cursor = 0.0
        while cursor < segment_length:
            phase = distance_along % period
            drawing = phase < dash
            run = (dash - phase) if drawing else (period - phase)
            step = min(run, segment_length - cursor)
            if drawing and step > 0:
                t0 = cursor / segment_length
                t1 = (cursor + step) / segment_length
                draw.line(
                    [
                        (round(start[0] + dx * t0), round(start[1] + dy * t0)),
                        (round(start[0] + dx * t1), round(start[1] + dy * t1)),
                    ],
                    fill=fill,
                    width=width,
                )
            cursor += step
            distance_along += step


def draw_route(
    draw: ImageDraw.ImageDraw,
    track: ProjectedCollectionTrack,
    style: str,
    end_index: int,
    width: int,
    *,
    theme: VisualTheme,
    start_index: int = 0,
    halo_width: int = 0,
) -> None:
    """Draw a route prefix, grouping equal semantic colors into clean runs."""
    points = track.pixel_points
    end = min(max(int(end_index), 0), len(points))
    start = min(max(int(start_index), 0), max(end - 1, 0))
    if end - start < 2:
        return
    if halo_width > 0:
        draw.line(
            points[start:end],
            fill=theme.canvas,
            width=width + 2 * halo_width,
        )
    if style == "density":
        from PIL import ImageColor
        c = ImageColor.getrgb(theme.route_primary)
        draw.line(
            points[start:end],
            fill=(c[0], c[1], c[2], 55),
            width=width,
        )
        return
    if style not in DATA_STYLE_SPECS:
        draw.line(
            points[start:end],
            fill=route_color(style, track.date, theme=theme),
            width=width,
        )
        return

    values = np.asarray(getattr(track, DATA_STYLE_SPECS[style]["field"]), dtype=float)
    finite = np.isfinite(values)
    if not np.any(finite):
        draw_dashed_path(
            draw,
            points[start:end],
            fill=theme.data_missing,
            width=width,
            dash=max(4, width * 2),
            gap=max(3, width),
        )
        return
    sample_positions = np.arange(len(values), dtype=float)
    values = np.interp(sample_positions, sample_positions[finite], values[finite])

    def draw_run(run_points: Sequence[tuple[int, int]], color: Optional[str]) -> None:
        assert color is not None
        draw.line(run_points, fill=color, width=width)

    run_start = start
    run_color = route_metric_color(style, values[start])
    for segment_index in range(start + 1, end - 1):
        color = route_metric_color(style, values[segment_index])
        if color != run_color:
            draw_run(points[run_start:segment_index + 1], run_color)
            run_start = segment_index
            run_color = color
    draw_run(points[run_start:end], run_color)


def draw_data_legend(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    style: str,
    tracks: Sequence[ProjectedCollectionTrack],
    *,
    i18n: Translator,
    theme: VisualTheme,
    scale: int,
    wide: bool,
) -> int:
    """Draw a compact, square-ended legend inside the editorial grid."""
    if style not in DATA_STYLE_SPECS:
        return y
    spec = DATA_STYLE_SPECS[style]
    field = spec["field"]
    covered = sum(
        1
        for track in tracks
        if np.any(np.isfinite(np.asarray(getattr(track, field), dtype=float)))
    )
    title_font = FontManager.get_font(11 * scale, bold=True)
    item_font = FontManager.get_font(10 * scale, bold=True)
    draw.text(
        (x, y),
        i18n.text(spec["legend_key"]).upper(),
        fill=theme.text_secondary,
        font=title_font,
    )
    coverage = i18n.text(
        "collection.legend.coverage_short", count=covered, total=len(tracks)
    )
    coverage_w = int(round(title_font.getlength(coverage)))
    draw.text(
        (x + width - coverage_w, y),
        coverage,
        fill=theme.text_muted,
        font=title_font,
    )

    items = [
        (color, label, False)
        for color, label in zip(spec["colors"], spec["labels"])
    ] + [(theme.data_missing, i18n.text("collection.legend.no_data"), True)]
    columns = 6 if wide else 3
    rows = int(math.ceil(len(items) / columns))
    item_w = width // columns
    item_y = y + 22 * scale
    for index, (color, label, missing) in enumerate(items):
        col = index % columns
        row = index // columns
        item_x = x + col * item_w
        current_y = item_y + row * 20 * scale
        if missing:
            draw.line(
                [(item_x, current_y + 6 * scale), (item_x + 6 * scale, current_y + 6 * scale)],
                fill=color,
                width=3 * scale,
            )
            draw.line(
                [(item_x + 12 * scale, current_y + 6 * scale), (item_x + 18 * scale, current_y + 6 * scale)],
                fill=color,
                width=3 * scale,
            )
        else:
            draw.line(
                [(item_x, current_y + 6 * scale), (item_x + 18 * scale, current_y + 6 * scale)],
                fill=color,
                width=3 * scale,
            )
        draw.text(
            (item_x + 25 * scale, current_y),
            str(label),
            fill=theme.text_muted,
            font=item_font,
        )
    return item_y + rows * 20 * scale + 8 * scale


def choose_map_legend_box(
    tracks: Sequence[ProjectedCollectionTrack],
    layout: VideoPartitionLayout,
    *,
    scale: int,
    wide: bool,
    has_attribution: bool,
) -> tuple[int, int, int, int]:
    """Pick the map corner with least route occupancy and greatest clearance."""
    padding = 28 * scale
    legend_w = min((760 if wide else 480) * scale, layout.map_rect.w - 2 * padding)
    legend_h = (62 if wide else 82) * scale
    candidates = [
        ("top_left", layout.map_rect.x0 + padding, layout.map_rect.y0 + padding),
        ("top_right", layout.map_rect.x1 - padding - legend_w, layout.map_rect.y0 + padding),
        ("bottom_left", layout.map_rect.x0 + padding, layout.map_rect.y1 - padding - legend_h),
        ("bottom_right", layout.map_rect.x1 - padding - legend_w, layout.map_rect.y1 - padding - legend_h),
    ]
    route_mask = Image.new("L", (layout.canvas_w, layout.canvas_h), 0)
    mask_draw = ImageDraw.Draw(route_mask)
    all_points: list[tuple[int, int]] = []
    for track in tracks:
        points = track.pixel_points
        if len(points) >= 2:
            mask_draw.line(points, fill=255, width=8 * scale)
            all_points.extend(points[::max(1, len(points) // 500)])

    scored = []
    safety = 14 * scale
    for name, x, y in candidates:
        expanded = (
            max(layout.map_rect.x0, x - safety),
            max(layout.map_rect.y0, y - safety),
            min(layout.map_rect.x1, x + legend_w + safety),
            min(layout.map_rect.y1, y + legend_h + safety),
        )
        collision_pixels = int(np.count_nonzero(np.asarray(route_mask.crop(expanded))))
        if all_points:
            distances = []
            for point_x, point_y in all_points:
                dx = max(x - point_x, 0, point_x - (x + legend_w))
                dy = max(y - point_y, 0, point_y - (y + legend_h))
                distances.append(math.hypot(dx, dy))
            clearance = min(distances)
        else:
            clearance = float("inf")
        reserved_penalty = 0
        if layout.aspect_ratio == "clean" and name == "top_left":
            reserved_penalty += 1_000_000
        if has_attribution and name == "bottom_left":
            reserved_penalty += 1_000_000
        scored.append((collision_pixels + reserved_penalty, -clearance, x, y))

    _, _, x, y = min(scored)
    return x, y, legend_w, legend_h


def draw_map_legend(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    style: str,
    tracks: Sequence[ProjectedCollectionTrack],
    *,
    i18n: Translator,
    theme: VisualTheme,
    scale: int,
    wide: bool,
) -> None:
    if style not in DATA_STYLE_SPECS:
        return
    x, y, width, height = box
    draw.rectangle(
        (x, y, x + width, y + height),
        fill=theme.panel_background,
        outline=theme.border,
        width=scale,
    )
    inset = 12 * scale
    draw_data_legend(
        draw,
        x + inset,
        y + inset,
        width - 2 * inset,
        style,
        tracks,
        i18n=i18n,
        theme=theme,
        scale=scale,
        wide=wide,
    )
