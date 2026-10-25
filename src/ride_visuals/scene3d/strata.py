"""Director for ``video strata``: rides stacked in 3D layers by month or year."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from ride_visuals.i18n import DEFAULT_LOCALE, Translator
from ride_visuals.scene3d.camera import (
    CURTAIN_S,
    CameraTrack,
    ease_in_out_sine,
    envelope,
    fade_through_black,
    fit_zoom,
    glide,
    reading_hold_s,
    span,
    travel,
)
from ride_visuals.scene3d.framing import frame_points
from ride_visuals.scene3d.places import (
    DEFAULT_PLACES_CACHE_DIR,
    home_region,
    home_title,
)
from ride_visuals.scene3d.spec import Look, SceneSpec
from ride_visuals.scene3d.stretch import SceneRide
from ride_visuals.scene3d.track import from_local_xy, gaussian_smooth, local_xy

PeriodMode = Literal["auto", "month", "year"]


@dataclass(frozen=True)
class StrataBuildResult:
    """Built strata scene spec and count of rides outside the home region."""

    spec: SceneSpec
    kept_rides: int
    excluded_rides: int


def build_strata_spec(  # noqa: PLR0913, PLR0915
    rides: Sequence[SceneRide],
    *,
    period: PeriodMode = "auto",
    locale: str = DEFAULT_LOCALE,
    look: Look = "carbon",
    width: int = 1920,
    height: int = 1080,
    fps: int = 60,
    title_override: str | None = None,
    credits_on_screen: bool = False,
    places_cache_dir: Path = DEFAULT_PLACES_CACHE_DIR,
    offline: bool = False,
) -> StrataBuildResult:
    """Build the frame-by-frame spec for ``video strata``."""
    valid_rides = [r for r in rides if len(r.track.lon) >= 2 and r.track.length_m >= 100.0]
    if not valid_rides:
        raise ValueError("No valid rides with GPS tracks found for the selected scope")

    i18n = Translator(locale)
    (home_lon, home_lat), near = home_region([(float(r.track.lon[0]), float(r.track.lat[0])) for r in valid_rides])
    regional = [r for r, keep in zip(valid_rides, near.tolist(), strict=True) if keep]
    if not regional:
        regional = list(valid_rides)
    excluded_count = len(valid_rides) - len(regional)

    regional.sort(key=lambda r: r.start_date)
    first_dt = regional[0].start_date
    last_dt = regional[-1].start_date
    months_span = (last_dt.year - first_dt.year) * 12 + (last_dt.month - first_dt.month) + 1
    resolved_period: Literal["month", "year"] = (
        ("month" if months_span <= 14 else "year") if period == "auto" else period
    )
    multi_year = first_dt.year != last_dt.year

    # Group chronologically into floors.
    grouped: dict[str, list[int]] = defaultdict(list)
    floor_meta: dict[str, tuple[int, int]] = {}
    encoded_tracks: list[dict[str, list[int]]] = []
    for idx, ride in enumerate(regional):
        encoded_tracks.append(ride.track.encode(tolerance_m=4.5, max_vertices=3_500))
        dt = ride.start_date
        key = f"{dt.year:04d}-{dt.month:02d}" if resolved_period == "month" else f"{dt.year:04d}"
        grouped[key].append(idx)
        floor_meta[key] = (dt.year, dt.month)

    floor_keys = sorted(grouped)
    floor_count = len(floor_keys)

    # Plate around where the riding happens: every ride weighs the same (a
    # 200 km day out must not stretch the plate for 100 rides around home);
    # what runs beyond the plate is cut at its edge by the player.
    origin = (home_lon, home_lat)
    samples = [np.linspace(0, len(r.track.lon) - 1, 200).astype(int) for r in regional]
    all_lons = np.concatenate([r.track.lon[k] for r, k in zip(regional, samples, strict=True)])
    all_lats = np.concatenate([r.track.lat[k] for r, k in zip(regional, samples, strict=True)])
    all_x, all_y = local_xy(all_lons, all_lats, origin)
    x_min, x_max = np.percentile(all_x, [2.0, 98.0])
    y_min, y_max = np.percentile(all_y, [2.0, 98.0])
    span_x = max(float(x_max - x_min), 4_000.0)
    span_y = max(float(y_max - y_min), 4_000.0)
    pad_x = 0.08 * span_x
    pad_y = 0.08 * span_y
    x0, x1 = float(x_min - pad_x), float(x_max + pad_x)
    y0, y1 = float(y_min - pad_y), float(y_max + pad_y)
    plate_span = max(x1 - x0, y1 - y0)

    corner_x = np.array([x0, x1, x1, x0], dtype=float)
    corner_y = np.array([y0, y0, y1, y1], dtype=float)
    corner_lon, corner_lat = from_local_xy(corner_x, corner_y, origin)
    corners = [
        [round(float(lon), 6), round(float(lat), 6)]
        for lon, lat in zip(corner_lon.tolist(), corner_lat.tolist(), strict=True)
    ]

    # Scale tower height to plate span so vertical floor separation always reads cleanly.
    # Taller in portrait, where height is the room there is.
    tower_height_m = (2.3 if height > width else 0.8) * plate_span if floor_count > 1 else 0.14 * plate_span
    floor_step_m = tower_height_m / max(1, floor_count - 1) if floor_count > 1 else tower_height_m

    # Timeline (seconds).
    # One beat per floor: the plate lands, that period's rides draw on it, its
    # label comes in. The film grows with the number of floors.
    beat = 2.6 if resolved_period == "year" else (2.2 if floor_count <= 8 else 1.8)
    t_beats = 3.4
    t_final = t_beats + floor_count * beat + 0.6
    # The four totals fade in over 1 s, then hold until the curtain.
    t_end = t_final + 1.0 + reading_hold_s(4) + CURTAIN_S
    frames = max(60, int(round(t_end * fps)))
    t = np.arange(frames, dtype=float) / float(fps)
    beat_start = [t_beats + k * beat for k in range(floor_count)]
    floor_lifts = [k * floor_step_m if floor_count > 1 else 0.0 for k in range(floor_count)]

    portrait = height > width
    z_top, cx_plate, cy_plate = fit_zoom(
        corner_x,
        corner_y,
        bearing=0.0,
        lat=home_lat,
        width=float(width),
        height=float(height),
        fill=0.70 if not portrait else 0.76,
    )

    # Camera: top-down for the title, tilt, then a slow orbit that rises with the stack.
    cam = CameraTrack(frames)
    tilt = travel(span(t, 1.6, 3.8))
    orbit = ease_in_out_sine(span(t, 1.6, t_end))
    stack_top = np.zeros(frames)
    for k in range(floor_count):
        stack_top = np.maximum(stack_top, floor_lifts[k] * travel(span(t, beat_start[k], beat_start[k] + 0.9)))
    stack_top = gaussian_smooth(stack_top, 0.5 * fps)

    cam.pitch = gaussian_smooth(58.0 * tilt, max(2.0, 0.35 * fps))
    cam.bearing = (-14.0 * tilt - 48.0 * orbit) % 360.0
    # Frame the stack a beat ahead of itself, as one continuous rise: framing
    # each landing as it happens would bob the camera once per floor.
    ahead = np.interp(t + beat, t, stack_top)
    framed_top = np.maximum.accumulate(gaussian_smooth(np.maximum.accumulate(ahead), beat * fps))
    framed_top = np.maximum(framed_top, stack_top)
    cam.elevation = 0.5 * framed_top * tilt
    # The stack fills the space right of the label column; the camera dollies
    # out and up as it grows.
    label_col = (0.30 if portrait else 0.27) * tilt + 0.04 * (1.0 - tilt)
    # The whole height while building; a little room for the totals at the end.
    stats_in = ease_in_out_sine(span(t, t_final - 0.6, t_final + 1.0))
    # Portrait totals are two rows of larger text above the safe area.
    bottom = (0.9 - (0.21 if portrait else 0.1) * stats_in)
    heights = np.concatenate([np.zeros((frames, 4)), np.repeat(framed_top[:, None], 4, axis=1)], axis=1)
    cam_cx, cam_cy, cam.zoom = frame_points(
        np.full(frames, cx_plate), np.full(frames, cy_plate), cam.elevation, np.full(frames, z_top), cam.pitch,
        cam.bearing, home_lat, width, height, np.tile(corner_x, 2), np.tile(corner_y, 2), heights,
        (label_col, np.full(frames, 0.06), np.full(frames, 0.97), bottom),
        fps,
        fill=0.98,
    )
    # Once the stack starts growing the camera only ever backs away.
    peak = int(np.argmax(cam.zoom))
    cam.zoom[peak:] = np.minimum.accumulate(cam.zoom[peak:])
    cam.lon, cam.lat = from_local_xy(cam_cx, cam_cy, origin)
    cam.map_opacity = 1.0 - 0.45 * tilt

    opening_ch = envelope(t, 0.35, t_beats + 0.4, 0.45)
    final_ch = ease_in_out_sine(span(t, t_final - 0.4, t_final + 0.8))
    stats_ch = ease_in_out_sine(span(t, t_final, t_final + 1.0))
    fade_ch = 1.0 - 0.35 * ease_in_out_sine(span(t, t_end - 1.1, t_end))
    black_ch = fade_through_black(t, t_end, open_s=0.65)

    if look == "satellite":
        # Imagery under the title, carbon once the stack starts (floors read over black).
        cam.satellite = np.clip((1.0 - 0.25 * opening_ch) * (1.0 - tilt), 0.0, 1.0)

    channels: dict[str, np.ndarray] = {
        "opening": opening_ch,
        "final": final_ch,
        "stats": stats_ch,
        "fade": fade_ch,
        "black": black_ch,
    }

    story_floors = []
    for k, key in enumerate(floor_keys):
        indices = grouped[key]
        year, month = floor_meta[key]
        floor_km = sum(
            (regional[i].distance_m if regional[i].distance_m > 0 else regional[i].track.length_m)
            for i in indices
        ) / 1000.0
        if resolved_period == "month":
            label = i18n.month_name(month, year if multi_year else None)
        else:
            label = str(year)

        b0 = beat_start[k]
        channels[f"floor{k}"] = glide(span(t, b0, b0 + 0.9))
        channels[f"draw{k}"] = ease_in_out_sine(span(t, b0 + 0.25, b0 + beat + 0.2))
        channels[f"label{k}"] = ease_in_out_sine(span(t, b0 + 0.3, b0 + 0.9))
        # In focus during its own beat, calmer once the next period arrives.
        channels[f"focus{k}"] = np.clip(
            span(t, b0, b0 + 0.4) - span(t, b0 + beat, b0 + beat + 0.7), 0.0, 1.0
        )
        story_floors.append(
            {
                "id": key,
                "label": label,
                # Each floor reads as its distance alone: the stack is about how far, not how often.
                "value": i18n.number(round(floor_km)),
                "unit": "km",
                "targetLift": round(floor_lifts[k], 1),
                "step": round(floor_step_m, 1),
                "trackIndices": indices,
            }
        )

    extra_sources: list[str] = []
    opening_text, home_sources = home_title(
        (home_lon, home_lat), title_override, i18n.text("scene3d.rides_count", count=len(regional)), cache_dir=places_cache_dir, offline=offline
    )
    extra_sources.extend(home_sources)

    total_km = sum((r.distance_m if r.distance_m > 0 else r.track.length_m) for r in regional) / 1000.0
    total_gain = sum(max(0.0, r.elevation_gain_m) for r in regional)
    total_hours = sum(max(0.0, r.moving_time_s) for r in regional) / 3600.0

    story = {
        "corners": corners,
        "floors": story_floors,
        "excludedRides": excluded_count,
        "opening": {
            "label": i18n.text(
                "scene3d.strata.kicker",
                start=i18n.date(first_dt),
                end=i18n.date(last_dt),
            ),
            "text": opening_text,
        },
        "stats": [
            {"label": i18n.text("scene3d.rides"), "value": i18n.number(len(regional))},
            {"label": i18n.text("scene3d.distance"), "value": i18n.number(total_km, 1), "unit": "km"},
            {"label": i18n.text("scene3d.ascent"), "value": f"+{i18n.number(round(total_gain))}", "unit": "m"},
            {"label": i18n.text("scene3d.moving_time"), "value": i18n.number(max(0.1, total_hours), 1), "unit": "h"},
        ],
    }

    spec = SceneSpec(
        kind="strata",
        locale=i18n.locale,
        look=look,
        width=width,
        height=height,
        fps=fps,
        camera=cam,
        channels=channels,
        tracks=encoded_tracks,
        story=story,
        credits_on_screen=credits_on_screen,
        extra_sources=tuple(extra_sources),
    )
    return StrataBuildResult(spec=spec, kept_rides=len(regional), excluded_rides=excluded_count)
