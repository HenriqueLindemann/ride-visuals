"""Director for ``video stretch``: rides unfurled end-to-end along a great circle."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np

from ride_visuals.i18n import DEFAULT_LOCALE, Translator
from ride_visuals.scene3d.camera import (
    EARTH_CIRCUMFERENCE_M,
    CameraTrack,
    ease_in_out_sine,
    envelope,
    fade_through_black,
    span,
    zoom_for_mpp,
)
from ride_visuals.scene3d.places import (
    DEFAULT_PLACES_CACHE_DIR,
    destination_for_distance,
    great_circle_destination,
    home_cluster,
    home_title,
)
from ride_visuals.scene3d.spec import Look, SceneSpec
from ride_visuals.scene3d.track import RideTrack, gaussian_smooth, haversine_m, local_xy

# Geometry budget for the whole scene (vertices across all rides), shared out
# by length so a few hundred rides keep the spec small without thinning any.
SPEC_VERTEX_BUDGET = 320_000
MIN_RIDE_VERTICES = 160
MAX_RIDE_VERTICES = 4_000
#: A "home loop" starts and ends this close to home (m); those open the film.
HOME_LOOP_START_M = 25_000.0
HOME_LOOP_END_M = 16_000.0
#: Without any home loop, the opening frames the rides that start this close to home.
HOME_START_FALLBACK_M = 30_000.0


@dataclass(frozen=True)
class SceneRide:
    """One ride in a collection scene."""

    activity_id: int
    start_date: date | datetime
    track: RideTrack
    distance_m: float
    elevation_gain_m: float = 0.0
    moving_time_s: float = 0.0


def _home_loops_first(
    rides: Sequence[SceneRide], home: tuple[float, float]
) -> tuple[list[SceneRide], list[SceneRide]]:
    """Rides in laying order (home loops first, longest first) and the home loops.

    Every ride is drawn and consumed along its own road; the loops ridden from
    home are the ones the opening frames, so they go first and the rides far
    away (trips, point-to-point days) follow as the camera backs off.
    """
    by_length = sorted(rides, key=lambda r: r.track.length_m, reverse=True)

    def from_home(index: int) -> np.ndarray:
        lon = np.array([r.track.lon[index] for r in by_length])
        lat = np.array([r.track.lat[index] for r in by_length])
        return haversine_m(np.full(len(lon), home[0]), np.full(len(lat), home[1]), lon, lat)

    start_d, end_d = from_home(0), from_home(-1)
    is_home = (start_d <= HOME_LOOP_START_M) & (end_d <= HOME_LOOP_END_M)
    if not is_home.any():
        # No loop closes at home: open on whatever starts there instead.
        is_home = start_d <= max(HOME_START_FALLBACK_M, float(start_d.min()))
    home_loops = [r for r, h in zip(by_length, is_home, strict=True) if h]
    others = [r for r, h in zip(by_length, is_home, strict=True) if not h]
    return home_loops + others, home_loops


def _laid_phase(u: np.ndarray | float, ease_in: float = 0.06, ease_out: float = 0.22) -> np.ndarray:
    """0..1 phase of the pull: linear ramps in and out, unit speed cruise between.

    The speed rises linearly over ``ease_in`` and falls linearly over
    ``ease_out`` (a short start, a long damped landing), so the phase is
    piecewise quadratic and its derivative is continuous.
    """
    u = np.clip(np.asarray(u, dtype=float), 0.0, 1.0)
    v = 1.0 / (1.0 - 0.5 * (ease_in + ease_out))  # cruise speed, so the phase ends at 1
    rise = np.minimum(u, ease_in)
    fall = np.maximum(u - (1.0 - ease_out), 0.0)
    phase = v * (
        rise * rise / (2.0 * ease_in)
        + np.clip(u - ease_in, 0.0, 1.0 - ease_in - ease_out)
        + fall - fall * fall / (2.0 * ease_out)
    )
    return np.clip(phase, 0.0, 1.0)


def _laid_schedule(
    t: np.ndarray,
    total_m: float,
    first_m: float,
    t_start: float,
    t_end: float,
    first_s: float = 2.6,
) -> np.ndarray:
    """Metres laid by each frame: one exponential, eased in briefly and landed softly.

    ``L0 * (exp(K * phase) - 1)`` speeds up at a constant rate in log space,
    which is also how the camera recedes, so the line reads as one steady,
    accelerating pull instead of a ride-by-ride stutter. ``K`` is fixed by
    ending at ``total_m``; ``L0`` is solved (bisection in log space) so the
    first ride (``first_m``) takes about ``first_s`` to lay.
    """
    dur = max(t_end - t_start, 1e-6)
    phase = _laid_phase((t - t_start) / dur)
    first_m = float(np.clip(first_m, 1.0, 0.5 * total_m))
    p_first = float(np.clip(_laid_phase(min(first_s / dur, 1.0)), 1e-3, 0.9))

    def laid_at(l0: float, ph: np.ndarray | float) -> np.ndarray | float:
        return l0 * np.expm1(np.log1p(total_m / l0) * ph)

    lo, hi = 1e-3, total_m
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        lo, hi = (mid, hi) if laid_at(mid, p_first) < first_m else (lo, mid)
    return np.clip(laid_at(lo, phase), 0.0, total_m)


def build_stretch_spec(  # noqa: PLR0913, PLR0915
    rides: Sequence[SceneRide],
    *,
    locale: str = DEFAULT_LOCALE,
    look: Look = "carbon",
    width: int = 1920,
    height: int = 1080,
    fps: int = 60,
    toward: str | None = None,
    home: tuple[float, float] | None = None,
    title_override: str | None = None,
    credits_on_screen: bool = False,
    places_cache_dir: Path = DEFAULT_PLACES_CACHE_DIR,
    offline: bool = False,
) -> SceneSpec:
    """Build the frame-by-frame spec for ``video stretch``."""
    valid_rides = [r for r in rides if len(r.track.lon) >= 2 and r.track.length_m >= 100.0]
    if not valid_rides:
        raise ValueError("No valid rides with GPS tracks found for the selected scope")

    i18n = Translator(locale)
    starts = [(float(r.track.lon[0]), float(r.track.lat[0])) for r in valid_rides]
    home_lon, home_lat = home or home_cluster(starts)

    # The biggest loops unfurl first, slowly, at regional scale.
    ordered, home_loops = _home_loops_first(valid_rides, (home_lon, home_lat))
    total_m = float(sum(r.track.length_m for r in ordered))
    total_km = float(sum((r.distance_m if r.distance_m > 0 else r.track.length_m) for r in ordered)) / 1000.0

    encoded_tracks: list[dict[str, list[int]]] = []
    story_rides = []
    before_m = 0.0
    for idx, ride in enumerate(ordered):
        length_m = float(ride.track.length_m)
        share = SPEC_VERTEX_BUDGET * length_m / total_m
        max_vertices = int(np.clip(share, MIN_RIDE_VERTICES, MAX_RIDE_VERTICES))
        track_index = len(encoded_tracks)
        encoded_tracks.append(ride.track.encode(tolerance_m=4.0, max_vertices=max_vertices))
        rank_frac = idx / max(1, len(ordered) - 1)
        story_rides.append(
            {
                "trackIndex": track_index,
                "lengthM": round(length_m, 1),
                "beforeM": round(before_m, 1),
                "restAlpha": round(0.54 - 0.24 * rank_frac, 3),
                "restWidth": round(1.65 - 0.35 * rank_frac, 2),
            }
        )
        before_m += length_m

    extra_sources: list[str] = []

    # Only an explicit --toward names a destination; an automatic "nearest city
    # at that distance" reads as random, so by default the line simply heads east.
    dest = None
    if toward is not None and toward.strip():
        dest = destination_for_distance(
            home_lon,
            home_lat,
            total_m,
            toward=toward,
            cache_dir=places_cache_dir,
            offline=offline,
        )
    if dest is not None and dest.place.source:
        extra_sources.append(dest.place.source)

    pull_bearing = dest.bearing_deg if dest is not None else 90.0

    # Opening & ending copy.
    # The total distance is the counter's punchline: the copy never states it
    # ahead of the count, nor repeats it after.
    kicker = i18n.text("scene3d.rides_count", count=len(ordered))
    opening_text, home_sources = home_title(
        (home_lon, home_lat), title_override, kicker, cache_dir=places_cache_dir, offline=offline
    )
    extra_sources.extend(home_sources)

    ending_accent: str | None = None
    dest_story = None
    if dest is not None:
        rel_diff = abs(dest.distance_m - total_m) / max(dest.distance_m, 1.0)
        place_name = dest.place.name
        ending_accent = place_name
        if rel_diff < 0.03:
            ending_text = i18n.text("scene3d.stretch.reach", place=place_name)
        else:
            ending_text = i18n.text("scene3d.stretch.toward", place=place_name)
        dest_story = {
            "name": place_name,
            "at": [round(dest.place.lon, 5), round(dest.place.lat, 5)],
            "distanceM": round(dest.distance_m, 1),
        }
    elif total_m >= 0.05 * EARTH_CIRCUMFERENCE_M:
        # Perspective on the total, not the total again.
        laps = total_m / EARTH_CIRCUMFERENCE_M
        earth_word = i18n.text("scene3d.stretch.earth_word")
        ending_accent = earth_word
        if laps >= 0.95:
            ending_text = i18n.text("scene3d.stretch.earth_laps", laps=i18n.number(laps, 2))
        else:
            ending_text = i18n.text("scene3d.stretch.earth_pct", pct=round(laps * 100.0))
    else:
        ending_text = i18n.text("scene3d.stretch.fallback")

    # Timeline (seconds).
    t_open = 2.3
    t_pull_end = 13.6

    t_end = t_pull_end + 5.0
    frames = max(60, int(round(t_end * fps)))
    t = np.arange(frames, dtype=float) / float(fps)
    laid = _laid_schedule(t, total_m, ordered[0].track.length_m, t_open, t_pull_end)

    # Camera path along the great circle on the globe.
    cam = CameraTrack(frames)
    cam.globe = np.ones(frames)
    # Opening: the home loops fit around home (each ride weighs the same, so a
    # long day out may run off the edge rather than shrink all). Rides far away
    # wait where they were ridden and come into frame as the camera backs off.
    picks = [np.linspace(0, len(r.track.lon) - 1, 120).astype(int) for r in home_loops]
    dx, dy = local_xy(
        np.concatenate([r.track.lon[k] for r, k in zip(home_loops, picks, strict=True)]),
        np.concatenate([r.track.lat[k] for r, k in zip(home_loops, picks, strict=True)]),
        (home_lon, home_lat),
    )
    reach_x = float(np.percentile(np.abs(dx), 98.5))
    reach_y = float(np.percentile(np.abs(dy), 98.5))
    # The first ride is the protagonist: it always fits whole.
    lead_x, lead_y = local_xy(home_loops[0].track.lon, home_loops[0].track.lat, (home_lon, home_lat))
    reach_x = max(reach_x, float(np.abs(lead_x).max()))
    reach_y = max(reach_y, float(np.abs(lead_y).max()))
    open_mpp = max(2.0 * reach_x / (0.86 * width), 2.0 * reach_y / (0.78 * height), 2.0)
    z0 = float(np.clip(zoom_for_mpp(open_mpp, home_lat) - 0.1, 7.5, 12.5))
    # The line fills a share of the frame along its own direction (an east
    # line in landscape gets the width, a north one the height).
    along_x = abs(math.sin(math.radians(pull_bearing)))
    along_y = abs(math.cos(math.radians(pull_bearing)))
    room_px = 1.0 / math.hypot(along_x / width, along_y / height)
    fill_px = 0.6 * room_px

    for i, ti in enumerate(t):
        cur_m = max(12_000.0, float(laid[i]) * 1.12)
        if ti < t_open:
            open_drift = ti / max(t_open, 1e-6)
            cam.lon[i] = home_lon
            cam.lat[i] = home_lat
            cam.zoom[i] = z0 + 0.10 * open_drift
            cam.bearing[i] = 0.0
        else:
            hold_drift = float(span(np.array([ti]), t_pull_end, t_end)[0])
            eff_m = cur_m * (1.0 + 0.08 * hold_drift)
            # Frame from home to the growing tip; on global scales follow the great circle at ~55% of the arc.
            mid_frac = 0.48 if eff_m < 8_000_000.0 else 0.58
            mid_lon, mid_lat = great_circle_destination(home_lon, home_lat, pull_bearing, min(eff_m * mid_frac, 18_000_000.0))
            mpp = eff_m / fill_px
            raw_z = float(zoom_for_mpp(mpp, mid_lat))
            soft_z = z0 - math.log2(1.0 + 2.0 ** (z0 - raw_z - 0.25))
            cam.zoom[i] = max(1.65, soft_z - 0.14 * hold_drift)
            blend = float(np.clip((z0 - cam.zoom[i]) / 1.4, 0.0, 1.0))
            cam.lon[i] = home_lon + (((mid_lon - home_lon + 540.0) % 360.0) - 180.0) * blend
            cam.lat[i] = home_lat * (1.0 - blend) + mid_lat * blend
            cam.bearing[i] = -6.0 * blend * (0.5 + 0.5 * hold_drift)

    cam.lon = np.degrees(np.unwrap(np.radians(cam.lon)))
    cam.lon = gaussian_smooth(cam.lon, max(2.0, 0.45 * fps))
    cam.lat = gaussian_smooth(cam.lat, max(2.0, 0.45 * fps))
    cam.zoom = gaussian_smooth(cam.zoom, max(2.0, 0.45 * fps))
    cam.bearing = gaussian_smooth(cam.bearing, max(2.0, 0.45 * fps)) % 360.0
    cam.map_opacity = np.full(frames, 0.92)

    opening_ch = envelope(t, 0.3, t_open + 0.3, 0.45)
    counter_ch = envelope(t, t_open + 0.1, t_pull_end + 0.2, 0.45)
    ending_ch = envelope(t, t_pull_end + 0.15, t_end - 0.55, 0.55)
    landed_ch = np.where(t < t_pull_end, 0.0, np.clip((t - t_pull_end) / 1.1, 0.0, 1.0))
    ghost_ch = envelope(t, t_pull_end + 0.25, t_end - 0.6, 0.55)
    fade_ch = 1.0 - 0.35 * ease_in_out_sine(span(t, t_end - 1.2, t_end))
    black_ch = fade_through_black(t, t_end, open_s=0.65)

    if look == "satellite":
        cam.satellite = np.clip(1.0 - 0.28 * np.maximum(opening_ch, ending_ch), 0.0, 1.0)

    channels = {
        "laid": laid,
        "opening": opening_ch,
        "counter": counter_ch,
        "km": (laid / max(total_m, 1.0)) * total_km,
        "landed": landed_ch,
        "ghost": ghost_ch,
        "ending": ending_ch,
        "fade": fade_ch,
        "black": black_ch,
    }

    story = {
        "home": [round(home_lon, 6), round(home_lat, 6)],
        "pullBearing": round(pull_bearing, 3),
        "totalM": round(total_m, 1),
        "totalKm": round(total_km, 1),
        "rides": story_rides,
        "opening": {
            "label": kicker,
            "text": opening_text,
        },
        "counter": {
            "label": i18n.text("scene3d.stretch.counter"),
            "unit": "km",
        },
        "ending": {
            "text": ending_text,
            "accent": ending_accent,
        },
        "destination": dest_story,
    }

    return SceneSpec(
        kind="stretch",
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
