"""Map-first collection framing and a quiet, distance-only footer."""

from dataclasses import replace

from PIL import Image, ImageDraw, ImageFilter

from ride_visuals.design import VisualTheme
from ride_visuals.i18n import Translator
from ride_visuals.video.collection_data import (
    CollectionTrack, CollectionProjection, project_collection_tracks,
)
from ride_visuals.video.fonts import FontManager
from ride_visuals.video.layout import Rect, VideoPartitionLayout


def minimal_layout(
    width: int, height: int, *, safe_left: int = 0, safe_right: int = 0,
    reserve_legend: bool = False, counter_width_px: int | None = None,
) -> VideoPartitionLayout:
    """Reserve breathing room for the counter before fitting the routes."""
    vertical = height > width
    scale = height / (1920 if vertical else 1080)
    side = round(54 * scale)
    top = round(((120 if vertical else 48) + (100 if reserve_legend else 0)) * scale)
    bottom = round((360 if vertical else 184) * scale)
    content_width = width - safe_left - safe_right
    counter_width = min(counter_width_px or round(560 * scale), content_width - 2 * side)
    return VideoPartitionLayout(
        width, height, "minimal",
        Rect(safe_left + side, top, content_width - 2 * side, height - top - bottom),
        Rect(width - safe_right - side - counter_width, height - bottom, counter_width,
             round(150 * scale)),
    )


def distance_counter_width(total_km: float, *, i18n: Translator, scale: float) -> int:
    """Reserve the actual final readout width, so unused space stays with the map."""
    number = FontManager.get_font(max(1, round(76 * scale)), bold=True)
    unit = FontManager.get_font(max(1, round(24 * scale)))
    label = FontManager.get_font(max(1, round(18 * scale)), bold=True)
    return round(max(
        number.getlength(i18n.number(total_km, 1)) + 12 * scale + unit.getlength("km"),
        label.getlength(i18n.text("metric.distance").upper()),
    )) + 1


def fit_minimal_map(
    tracks: list[CollectionTrack], layout: VideoPartitionLayout, *, margin_px: int,
) -> tuple[VideoPartitionLayout, CollectionProjection]:
    """Expand into unused footer space only when every route clears the counter.

    Test full geometry, including segments between samples, so the framing stays
    fixed and safe throughout the animation. Search largest-first; the original
    partition is always a safe fallback.
    """
    vertical = layout.canvas_h > layout.canvas_w
    scale = layout.canvas_h / (1920 if vertical else 1080)
    bottom_margin = round((210 if vertical else 48) * scale)
    full_height = layout.canvas_h - bottom_margin - layout.map_rect.y0
    reserved = layout.telemetry_rect
    clearance = round(16 * scale)
    collision_box = (
        reserved.x0 - clearance, reserved.y0 - clearance,
        reserved.x1 + clearance, reserved.y1 + clearance,
    )
    for step in range(17):
        height = round(full_height - (full_height - layout.map_rect.h) * step / 16)
        candidate = replace(layout, map_rect=replace(layout.map_rect, h=height))
        projection = project_collection_tracks(tracks, candidate, margin_px=margin_px)
        mask = Image.new("1", (layout.canvas_w, layout.canvas_h))
        draw = ImageDraw.Draw(mask)
        for track in projection.tracks:
            if len(track.pixel_points) >= 2:
                draw.line(track.pixel_points, fill=1, width=max(1, round(10 * scale)))
        if mask.crop(collision_box).getbbox() is None:
            return candidate, projection
    raise ValueError("Could not fit collection routes clear of the distance counter")


def draw_minimal_distance(
    image: Image.Image, layout: VideoPartitionLayout, distance_km: float,
    total_distance_km: float, *, i18n: Translator, theme: VisualTheme,
    has_basemap: bool,
) -> None:
    """Stable right-aligned tabular numerals; no card, chart, or panel."""
    vertical = image.height > image.width
    scale = image.height / (1920 if vertical else 1080)
    box = layout.telemetry_rect
    size = max(1, round(76 * scale))
    unit_font = FontManager.get_font(max(1, round(24 * scale)))
    label_font = FontManager.get_font(max(1, round(18 * scale)), bold=True)
    gap = round(12 * scale)
    unit_width = unit_font.getlength("km")
    # Fit against the final total, so typography never jumps as digits accumulate.
    while size > 1:
        number_font = FontManager.get_font(size, bold=True)
        if number_font.getlength(i18n.number(total_distance_km, 1)) + gap + unit_width <= box.w:
            break
        size -= 1
    baseline = box.y0 + round(118 * scale)
    unit_x = box.x1 - unit_width
    layer = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(layer)
    draw.text((box.x1, box.y0 + round(22 * scale)),
              i18n.text("metric.distance").upper(), font=label_font,
              fill=theme.text_secondary, anchor="rt")
    draw.text((unit_x - gap, baseline), i18n.number(distance_km, 1),
              font=number_font, fill=theme.text_primary, anchor="rs")
    draw.text((unit_x, baseline), "km", font=unit_font,
              fill=theme.text_secondary, anchor="ls")
    if has_basemap:
        shadow = Image.new("RGBA", image.size, theme.canvas)
        shadow.putalpha(layer.getchannel("A").filter(ImageFilter.GaussianBlur(4 * scale)))
        image.paste(shadow, (0, 0), shadow)
    image.paste(layer, (0, 0), layer)
