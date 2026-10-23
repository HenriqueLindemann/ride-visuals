"""Director for ``video flyover``: one ride in 3D relief, ending as its profile."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np

from ride_visuals.i18n import DEFAULT_LOCALE, Translator, sanitize_display_text
from ride_visuals.scene3d.camera import (
    CURTAIN_S,
    CameraTrack,
    bearing_deg,
    ease_in_out_sine,
    envelope,
    eye_offset,
    fade_through_black,
    lerp_angle,
    limit_rate,
    meters_per_pixel,
    reading_hold_s,
    smooth_angles,
    span,
    travel,
    zoom_for_mpp,
)
from ride_visuals.scene3d.climbs import Climb, detect_climbs, featured_climbs, hero_climb
from ride_visuals.scene3d.framing import (
    adaptive_exaggeration,
    occlusion,
    solve_chase,
    visible_bearing_offset,
    zoom_to_fill,
)
from ride_visuals.scene3d.places import DEFAULT_PLACES_CACHE_DIR, nearest_place
from ride_visuals.scene3d.spec import Look, SceneSpec
from ride_visuals.scene3d.terrain import DemSampler
from ride_visuals.scene3d.track import (
    RideTrack,
    from_local_xy,
    gaussian_smooth,
    local_xy,
)
from ride_visuals.video.instagram import INSTAGRAM_STORY

MIN_RIDE_LENGTH_M = 500.0
MAX_BEARING_RATE_DEG_S = 24.0  # hard cap; the chase solver aims for 22
MIN_EYE_CLEARANCE_M = 45.0
SIDE_PITCH = 84.0
# Real relief at the level view: an exaggerated skyline would hide the route.
SIDE_EXAGGERATION = 1.0
SIDE_ORBIT_RATE_DEG_S = 72.0
#: The hero climb is seen three-quarter on (start lower left, summit upper
#: right): a 60-odd degree orbit off the chase, eased over HERO_FADE_S. The
#: view starts from the most dramatic angle (HERO_PITCH) and only rises
#: towards the vertical when the relief would hide the road (HERO_PITCHES).
HERO_VIEW_ANGLE_DEG = 62.0
HERO_VIEW_ANGLES_DEG = (62.0, 50.0, 74.0)
HERO_FADE_S = 2.8
HERO_ORBIT_RATE_DEG_S = 42.0
HERO_PITCH = 64.0
HERO_PITCHES = (64.0, 58.0, 52.0, 46.0, 40.0)
#: While the hero beat holds, the camera keeps drifting: this much orbit and
#: dolly-in over the beat, so it never reads as a frozen frame.
HERO_ORBIT_DRIFT_DEG = 8.0
HERO_DOLLY_ZOOM = 0.16
#: Road samples the hero view is judged on (fine enough to see a short gap).
HERO_VIEW_SAMPLES = 160
#: Cost of each degree of pitch given up, of each degree off the 3/4 angle,
#: and of seeing the climb run right to left, against the hidden fraction.
HERO_PITCH_COST = 0.0015
HERO_ANGLE_COST = 0.002
HERO_MIRROR_COST = 0.05
#: Where the road is drawn above the relief (ROUTE_LIFT_M in flyover.ts).
ROUTE_LIFT_M = 4.0

#: Text, and what is sized by it, is set this much larger in portrait (mirrors
#: PORTRAIT_TEXT in renderer/src/scene3d/core/layout.ts).
PORTRAIT_TEXT = 1.4
#: Height of a live counter (label line, gap, 68 px value) at text scale 1.
_COUNTER_TEXT_H = 17.0 + 10.0 + 68.0
#: Screen layout at a 1080 px short side (see _Layout; frameMargins in
#: layout.ts): side margins and one vertical margin for the top and the bottom,
#: the Instagram Story safe area in portrait. The other entries are sized by
#: text, so they grow with it in portrait.
LAYOUT_1080: dict = {
    "landscape": {"margin_x": 112.0, "margin_y": 88.0, "trace_w": 360.0},
    "portrait": {"margin_x": 72.0, "margin_y": float(INSTAGRAM_STORY.profile_safe_px), "trace_w_frac": 0.4},
    "counter_w": 440.0,
    #: The climb trace hangs this far under the counters, this tall: the
    #: gain figure, the line, and the climb's length and grade under it.
    "trace_gap": 30.0,
    "trace_h": 170.0,
}

#: Local metres (x east, y north) -> ground height (m), NaN where unknown.
GroundXY = Callable[[np.ndarray, np.ndarray], np.ndarray]
#: Climb trace: every featured climb ridden over at least this long on screen,
#: drawn from this many samples of the climb, and held this long once the
#: summit is reached (the hero climb: through its summit beat).
TRACE_MIN_S = 0.5
TRACE_SAMPLES = 96
TRACE_HOLD_S = 2.4
#: The summary under a trace fades in over this long after the summit.
TRACE_SUMMIT_S = 1.4
#: The climb of the day only gets the hero treatment when it is a real climb.
HERO_MIN_GAIN_M = 100.0
#: Sides and bottom of the box the hero climb fills (fractions of the frame);
#: its top keeps clear of the counters and the climb trace (_Layout.hero_box).
HERO_BOX_X = (0.2, 0.8)
HERO_BOX_BOTTOM = 0.76
CLIMB_TIME_WEIGHT = 3.5
#: Screen-time ground speed on the flats (m/s): low enough that the chase
#: camera can stay close (~z12) without the land streaming past.
FLAT_SPEED_M_S = 3600.0
CRUISE_RAMP_S = 1.4
TYPICAL_CHASE_ZOOM = 12.4
#: Levels the opening establishing shot sits above the chase zoom.
OPENING_ZOOM_DROP = 1.5


@dataclass(frozen=True)
class FlyoverMetadata:
    """Catalog or stream metadata for the activity being flown."""

    activity_id: int = 0
    name: str | None = None
    start_date: date | datetime | str | None = None
    distance_m: float | None = None
    elevation_gain_m: float | None = None
    moving_time_s: float | None = None


def _cruise(u: np.ndarray, ramp: float) -> np.ndarray:
    """Position along a leg (0..1) at constant speed, easing in and out over ``ramp``.

    A sine ease over a whole leg peaks at pi/2 times the mean speed, which is
    what decides how high the camera must fly; a cruise keeps the peak low.
    """
    u = np.clip(np.asarray(u, dtype=float), 0.0, 1.0)
    r = float(np.clip(ramp, 1e-3, 0.5))
    v = 1.0 / (1.0 - r)  # cruise speed, so the leg still ends at 1
    rise = np.minimum(u, r)
    fall = np.maximum(u - (1.0 - r), 0.0)
    eased_in = v * (rise - r / np.pi * np.sin(np.pi * rise / r)) / 2.0
    cruise = v * np.clip(u - r, 0.0, 1.0 - 2.0 * r)
    eased_out = v * (fall + r / np.pi * np.sin(np.pi * fall / r)) / 2.0
    return np.clip(eased_in + cruise + eased_out, 0.0, 1.0)


def _format_date(raw: date | datetime | str | None, i18n: Translator) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (date, datetime)):
        return i18n.date(raw)
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text[:10])
        return i18n.date(parsed)
    except ValueError:
        return text[:10]


def _format_hours(seconds: float, i18n: Translator) -> tuple[str, str]:
    """Moving time as "54 min" under an hour, else "6:36 h"."""
    minutes = max(1, int(round(seconds / 60.0)))
    if minutes < 60:
        return str(minutes), "min"
    return f"{minutes // 60}:{minutes % 60:02d}", "h"


@dataclass(frozen=True)
class _SideView:
    """Level camera beside the ride and the vertical plane the route unfolds into."""

    cx: float
    cy: float
    zoom: float
    bearing: float
    elevation: float
    #: Screen-right unit vector (east, north) and the line's length; the line
    #: is centred on (cx, cy), right under the camera.
    right: tuple[float, float]
    line_m: float
    base_z: float
    vertical: float
    min_alt: float

    def story(self, origin: tuple[float, float], prof_alt: np.ndarray) -> dict[str, object]:
        lon, lat = from_local_xy(np.array([self.cx]), np.array([self.cy]), origin)
        return {
            "center": [round(float(lon[0]), 6), round(float(lat[0]), 6)],
            "right": [round(self.right[0], 5), round(self.right[1], 5)],
            "lineM": round(self.line_m, 1),
            "baseZ": round(self.base_z, 2),
            "vertical": round(self.vertical, 4),
            "minAlt": round(self.min_alt, 1),
            "altRange": round(max(60.0, float(prof_alt.max() - self.min_alt)), 1),
        }


def _side_view(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    prof_d: np.ndarray,
    prof_alt: np.ndarray,
    total_m: float,
    exaggeration: float,
    width: int,
    height: int,
    lat: float,
) -> _SideView:
    """Look across the ride's main axis, start on the left, profile filling the frame.

    The route's principal axis becomes screen-right (signed so distance grows
    to the right); the profile plane sits through the route's centroid, so the
    unfold moves each point the least. Heights in the plane use their own
    vertical scale so the profile reads at ~28% of the frame (18% portrait).
    """
    mx, my = float(grid_x.mean()), float(grid_y.mean())
    ex, ey = grid_x - mx, grid_y - my
    _, vecs = np.linalg.eigh(np.cov(np.vstack([ex, ey])))
    axis = vecs[:, -1]
    proj = ex * axis[0] + ey * axis[1]
    if np.cov(proj, prof_d)[0, 1] < 0.0:
        axis, proj = -axis, -proj
    rx_, ry_ = float(axis[0]), float(axis[1])
    pmin, pmax = float(proj.min()), float(proj.max())
    line_m = max(pmax - pmin, 0.3 * total_m)
    mid = 0.5 * (pmin + pmax)
    line_cx, line_cy = mx + rx_ * mid, my + ry_ * mid

    portrait = height > width
    fill = 0.86 if portrait else 0.78
    mpp = max(line_m / (fill * width), 0.5)
    min_alt = float(prof_alt.min())
    alt_range = max(60.0, float(prof_alt.max()) - min_alt)
    vertical = (0.18 if portrait else 0.28) * height * mpp / alt_range
    base_z = min_alt * exaggeration
    base_row = 0.58 if portrait else 0.6
    return _SideView(
        cx=line_cx,
        cy=line_cy,
        zoom=float(zoom_for_mpp(mpp, lat)),
        bearing=float(np.degrees(np.arctan2(-ry_, rx_)) % 360.0),
        elevation=base_z + (base_row - 0.5) * height * mpp,
        right=(rx_, ry_),
        line_m=line_m,
        base_z=base_z,
        vertical=vertical,
        min_alt=min_alt,
    )


@dataclass(frozen=True)
class _HeroView:
    bearing: float
    pitch: float
    zoom: float
    hidden: float


def _hero_view(
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    centre: tuple[float, float, float],
    exaggeration: float,
    ground_xy: GroundXY | None,
    lat: float,
    width: int,
    height: int,
    ceiling_m: float,
) -> _HeroView:
    """Camera that shows the whole hero climb: as oblique as the relief allows.

    Every candidate (side, angle off the climb's direction, pitch) is framed
    to fill the layout's hero box and scored by the fraction of the road the relief hides
    from it, as the player will draw it, plus small costs for giving up the
    low dramatic angle or the start-left, summit-right reading.
    """
    cx, cy, mid_alt = centre
    climb_dir = float(bearing_deg(px[-1] - px[0], py[-1] - py[0]))
    if ground_xy is not None:
        road = ground_xy(px, py)
        road_z = (np.where(np.isfinite(road), road, pz) + ROUTE_LIFT_M) * exaggeration
    else:
        road_z = (pz + ROUTE_LIFT_M) * exaggeration
    candidates = [
        (side, angle, pitch)
        for side in (-1.0, 1.0)
        for angle in HERO_VIEW_ANGLES_DEG
        for pitch in HERO_PITCHES
    ]
    if ground_xy is None:
        candidates = candidates[:1]
    n = len(candidates)
    box = _Layout.for_frame(width, height).hero_box(width, height)
    bearings = np.array([(climb_dir + side * angle) % 360.0 for side, angle, _ in candidates])
    pitches = np.array([pitch for _, _, pitch in candidates])
    zooms = np.array([
        zoom_to_fill(
            cx, cy, mid_alt * exaggeration, pitch, bearing, lat, width, height,
            px, py, pz * exaggeration, box, zoom_range=(11.0, 14.0),
        )
        for bearing, pitch in zip(bearings, pitches, strict=True)
    ])
    hidden = np.zeros(n)
    if ground_xy is not None:
        # Judged over the whole beat (where the drift starts and where it
        # ends), every candidate in one pass over the DEM.
        dx, dy, dz = eye_offset(
            np.concatenate([zooms, zooms + HERO_DOLLY_ZOOM]),
            np.tile(pitches, 2),
            np.concatenate([bearings, bearings + HERO_ORBIT_DRIFT_DEG]),
            np.full(2 * n, lat),
            float(height),
        )
        seen = occlusion(
            cx + dx, cy + dy, mid_alt * exaggeration + dz,
            np.tile(px, (2 * n, 1)), np.tile(py, (2 * n, 1)), np.tile(road_z, (2 * n, 1)),
            lambda x, y: np.nan_to_num(ground_xy(x, y), nan=-1e4) * exaggeration,
            ceiling=ceiling_m * exaggeration,
        )
        hidden = np.maximum(seen[:n], seen[n:])
    best: _HeroView | None = None
    best_cost = np.inf
    for k, (side, angle, pitch) in enumerate(candidates):
        cost = (
            hidden[k]
            + HERO_PITCH_COST * (HERO_PITCH - pitch)
            + HERO_ANGLE_COST * abs(angle - HERO_VIEW_ANGLE_DEG)
            + (HERO_MIRROR_COST if side > 0 else 0.0)
        )
        if cost < best_cost:
            best = _HeroView(float(bearings[k]), pitch, float(zooms[k]), float(hidden[k]))
            best_cost = cost
    assert best is not None
    return best


@dataclass(frozen=True)
class _Layout:
    """Where the screen furniture sits (px): the single source for director and player.

    Sizes are given for a 1080 px short side (LAYOUT_1080) and scaled. All
    live text sits along the top: the route is never drawn ahead of the rider,
    so the top of the frame is land still to come, while the road behind runs
    down through the bottom, winding into either corner (in a portrait frame,
    under bottom corner counters most of the ride). The two counters take the
    top corners, as the opening title did. While a climb is ridden, its trace
    sits centred under them: the climb's profile drawn as it is ridden, and
    the metres it has gained.
    """

    scale: float
    margin_x: float
    top_y: float
    #: Top of the corner counters (their label row), and their height.
    counters_y: float
    counter_h: float
    counter_w: float
    #: The climb trace's box (px).
    trace: tuple[float, float, float, float]

    @classmethod
    def for_frame(cls, width: int, height: int) -> _Layout:
        portrait = height > width
        ref = LAYOUT_1080["portrait" if portrait else "landscape"]
        scale = min(width, height) / 1080.0
        text = scale * (PORTRAIT_TEXT if portrait else 1.0)
        margin_x = ref["margin_x"] * scale
        top_y = ref["margin_y"] * scale
        trace_w = ref["trace_w_frac"] * width if portrait else ref["trace_w"] * scale
        trace_y = top_y + _COUNTER_TEXT_H * text + LAYOUT_1080["trace_gap"] * text
        return cls(
            scale=scale,
            margin_x=margin_x,
            top_y=top_y,
            counters_y=top_y,
            counter_h=_COUNTER_TEXT_H * text,
            counter_w=LAYOUT_1080["counter_w"] * text,
            trace=(0.5 * (width - trace_w), trace_y, 0.5 * (width + trace_w), trace_y + LAYOUT_1080["trace_h"] * text),
        )

    def hero_box(self, width: int, height: int) -> tuple[float, float, float, float]:
        """Where the hero climb sits (fractions of the frame): under the climb trace."""
        top = self.trace[3] / height + 0.04
        return (HERO_BOX_X[0], top, HERO_BOX_X[1], HERO_BOX_BOTTOM)

    def story(self) -> dict[str, object]:
        def r(v: float) -> float:
            return round(v, 1)

        return {
            "marginX": r(self.margin_x),
            "topY": r(self.top_y),
            "countersY": r(self.counters_y),
            "routeLift": ROUTE_LIFT_M,
            "trace": [r(v) for v in self.trace],
        }


def _trace_windows(
    climbs: list[Climb],
    hero: Climb | None,
    head: np.ndarray,
    t: np.ndarray,
    riding: np.ndarray,
    t_hero_end: float,
) -> list[tuple[float, float, float] | None]:
    """(start, summit, end) seconds of each climb's trace, or None when too brief.

    It comes in as the head reaches the foot and stays a moment past the
    summit (the hero climb: through its summit beat), so the climb can be
    taken in whole; it never overlaps the next climb's trace.
    """
    ride_t = t[riding]
    ride_head = head[riding]
    windows: list[tuple[float, float, float] | None] = []
    for climb in climbs:
        t_foot = float(np.interp(climb.start_m, ride_head, ride_t))
        t_top = float(np.interp(climb.end_m, ride_head, ride_t))
        t_out = t_top + TRACE_HOLD_S
        if climb == hero:
            t_out = max(t_out, t_hero_end + 0.3)
        windows.append((t_foot - 0.3, t_top, t_out) if t_top - t_foot >= TRACE_MIN_S else None)
    for k in range(len(windows) - 1):
        cur, nxt = windows[k], windows[k + 1]
        if cur is not None and nxt is not None and cur[2] > nxt[0] - 0.1:
            windows[k] = (cur[0], cur[1], max(cur[1], nxt[0] - 0.1))
    return windows


def _tag_windows(
    climbs: list[Climb],
    hero: Climb | None,
    head: np.ndarray,
    t: np.ndarray,
    t_hero_start: float,
    t_hero_end: float,
) -> list[tuple[float, float, float]]:
    """(start, end, fade) seconds for each summit tag, never two on screen at once.

    Back-to-back climbs would otherwise stack their tags: windows are granted
    in order of importance (hero first, then score), a window that collides
    with an accepted one is first pushed later, and dropped if it still collides.
    """
    windows: list[tuple[float, float, float]] = []
    for climb in climbs:
        if climb == hero and t_hero_end > t_hero_start:
            windows.append((t_hero_start - 0.3, t_hero_end + 0.3, 0.45))
        else:
            t_hit = float(t[int(np.argmin(np.abs(head - climb.end_m)))])
            windows.append((t_hit - 0.9, t_hit + 0.9, 0.35))
    gap = 0.2
    order = sorted(range(len(climbs)), key=lambda i: (climbs[i] != hero, -climbs[i].score))
    accepted: list[tuple[float, float]] = []
    out: list[tuple[float, float, float]] = [(0.0, 0.0, 0.35)] * len(climbs)

    def collides(start: float, end: float) -> bool:
        return any(start < e + gap and end + gap > s for s, e in accepted)

    for i in order:
        start, end, fade = windows[i]
        if collides(start, end):
            # Linger a little after the summit instead (at most 0.8 s late).
            later = max((e for s, e in accepted if s < end + gap), default=start) + gap
            if later - start > 0.8 or collides(later, later + (end - start)):
                continue
            start, end = later, later + (end - start)
        accepted.append((start, end))
        out[i] = (start, end, fade)
    return out


def _time_weights(grid_s: np.ndarray, climbs: list[Climb], hero: Climb | None) -> np.ndarray:
    """Screen time per metre (1 on the flats): climbs are slow and close, flats a fast transit."""
    weights = np.ones_like(grid_s)
    for climb in climbs:
        mask = (grid_s >= climb.start_m) & (grid_s <= climb.end_m)
        weights[mask] = CLIMB_TIME_WEIGHT * (1.25 if climb == hero else 1.0)
    return gaussian_smooth(weights, 18.0)


def _ride_duration(length_m: float, climbs: list[Climb], hero: Climb | None) -> float:
    """Seconds of chase: flats cross at FLAT_SPEED_M_S, climbs CLIMB_TIME_WEIGHT times slower.

    The eased ends of each leg are paid for with a little extra time (sized
    for a typical ~30 s chase), so the cruise itself runs at that speed.
    """
    grid_s = np.linspace(0.0, length_m, 1200)
    weighted_m = float(np.mean(_time_weights(grid_s, climbs, hero))) * length_m
    return float(np.clip(weighted_m / FLAT_SPEED_M_S / (1.0 - CRUISE_RAMP_S / 30.0), 14.0, 60.0))


def _build_head_schedule(
    t: np.ndarray,
    *,
    t_start: float,
    t_end: float,
    length_m: float,
    climbs: list[Climb],
    hero: Climb | None,
    hero_pause_s: float,
) -> tuple[np.ndarray, float, float]:
    """Monotonic distance along the ride, slowed on climbs and pausing at the hero summit.

    Each leg cruises at constant (weighted) speed with short eased ends, so
    the flats never peak faster than they have to.
    """
    grid_s = np.linspace(0.0, length_m, 1200)
    cum = np.cumsum(_time_weights(grid_s, climbs, hero))
    cum = (cum - cum[0]) / max(cum[-1] - cum[0], 1e-9)

    def leg(start: float, end: float) -> np.ndarray:
        return _cruise(span(t, start, end), CRUISE_RAMP_S / max(end - start, 1e-6))

    if hero is None:
        head = np.interp(leg(t_start, t_end), cum, grid_s)
        return np.maximum.accumulate(head), 0.0, 0.0

    # Split the ride around the hero summit so the camera can orbit the crest.
    crest_start_m = max(hero.start_m + 0.75 * hero.length_m, hero.end_m - min(90.0, 0.12 * hero.length_m))
    u_crest = float(np.interp(crest_start_m, grid_s, cum))
    u_summit = float(np.interp(hero.end_m, grid_s, cum))
    active_dur = max(4.0, (t_end - t_start) - hero_pause_s)
    leg1_dur = max(2.2, active_dur * max(0.18, min(0.82, u_summit)))
    t_hero_start = t_start + leg1_dur
    t_hero_end = min(t_end - 1.2, t_hero_start + hero_pause_s)

    u = np.zeros_like(t)
    mask1 = (t >= t_start) & (t < t_hero_start)
    u[mask1] = u_crest * leg(t_start, t_hero_start)[mask1]
    mask_hero = (t >= t_hero_start) & (t < t_hero_end)
    u[mask_hero] = u_crest + (u_summit - u_crest) * ease_in_out_sine(
        span(t[mask_hero], t_hero_start, t_hero_end)
    )
    mask2 = t >= t_hero_end
    u[mask2] = u_summit + (1.0 - u_summit) * leg(t_hero_end, t_end)[mask2]
    u[t >= t_end] = 1.0
    head = np.interp(np.clip(u, 0.0, 1.0), cum, grid_s)
    return np.maximum.accumulate(head), t_hero_start, t_hero_end


def _ground_below(
    sampler: DemSampler | None,
    lon: np.ndarray,
    lat: np.ndarray,
    z: np.ndarray,
    ceiling: np.ndarray,
    fallback: np.ndarray,
) -> np.ndarray:
    """Ground height under points that could be near it; an eye far above any land keeps ``fallback``."""
    out = np.asarray(fallback, dtype=float).copy()
    low = z < ceiling
    if sampler is not None and low.any():
        values = sampler.sample(lon[low], lat[low])
        out[low] = np.where(np.isfinite(values), values, out[low])
    return out


def _enforce_eye_clearance(
    cam: CameraTrack,
    cx: np.ndarray,
    cy: np.ndarray,
    ground_m: np.ndarray,
    origin: tuple[float, float],
    sampler: DemSampler | None,
    height_px: int,
    fps: int,
    ceiling: float,
    limit: np.ndarray | None = None,
) -> None:
    """Reduce pitch where a ridge behind the camera would clip the eye."""
    active = (cam.terrain > 0.05) & (cam.pitch > 5.0)
    if limit is not None:
        active &= limit
    if not active.any():
        return
    for _ in range(5):
        dx, dy, dz = eye_offset(cam.zoom, cam.pitch, cam.bearing, cam.lat, float(height_px))
        eye_lon, eye_lat = from_local_xy(cx + dx, cy + dy, origin)
        mid_lon, mid_lat = from_local_xy(cx + 0.55 * dx, cy + 0.55 * dy, origin)
        eye_z = cam.elevation + dz
        mid_z = cam.elevation + 0.55 * dz
        eye_ground = _ground_below(sampler, eye_lon, eye_lat, eye_z, ceiling * cam.terrain, ground_m)
        mid_ground = _ground_below(sampler, mid_lon, mid_lat, mid_z, ceiling * cam.terrain, ground_m)
        req_eye = eye_ground * cam.terrain + MIN_EYE_CLEARANCE_M * cam.terrain
        req_mid = mid_ground * cam.terrain + 0.7 * MIN_EYE_CLEARANCE_M * cam.terrain
        low = active & ((eye_z < req_eye) | (mid_z < req_mid))
        if not low.any():
            break
        cam.pitch[low] = np.maximum(15.0, cam.pitch[low] * 0.82 - 4.0)
        cam.pitch = gaussian_smooth(cam.pitch, max(2.0, 0.35 * fps))
        cam.pitch[cam.terrain <= 0.01] = 0.0

    # Final hard guarantee against any steep local spike under the eye.
    dx, dy, dz = eye_offset(cam.zoom, cam.pitch, cam.bearing, cam.lat, float(height_px))
    eye_lon, eye_lat = from_local_xy(cx + dx, cy + dy, origin)
    eye_ground = _ground_below(sampler, eye_lon, eye_lat, cam.elevation + dz, ceiling * cam.terrain, ground_m)
    needed = eye_ground * cam.terrain + MIN_EYE_CLEARANCE_M * cam.terrain - dz
    lift_mask = active & (cam.elevation < needed)
    if lift_mask.any():
        cam.elevation = np.maximum(cam.elevation, np.where(lift_mask, needed, cam.elevation))


def build_flyover_spec(  # noqa: PLR0913, PLR0915
    track: RideTrack,
    *,
    metadata: FlyoverMetadata | None = None,
    sampler: DemSampler | None = None,
    locale: str = DEFAULT_LOCALE,
    look: Look = "carbon",
    width: int = 1920,
    height: int = 1080,
    fps: int = 60,
    title_override: str | None = None,
    credits_on_screen: bool = False,
    places_cache_dir: Path = DEFAULT_PLACES_CACHE_DIR,
    offline: bool = False,
) -> SceneSpec:
    """Build the frame-by-frame spec for a single-ride 3D flyover."""
    if len(track.lon) < 2 or track.length_m < MIN_RIDE_LENGTH_M:
        raise ValueError(
            f"Activity route is too short for a 3D flyover ({track.length_m:.0f} m < {MIN_RIDE_LENGTH_M:.0f} m)"
        )

    meta = metadata or FlyoverMetadata()
    i18n = Translator(locale)
    track = track.fill_altitude(sampler)
    total_m = track.length_m
    total_km = (meta.distance_m / 1000.0) if meta.distance_m and meta.distance_m > 0 else total_m / 1000.0

    origin = (float(track.lon.mean()), float(track.lat.mean()))
    rx, ry = local_xy(track.lon, track.lat, origin)
    anchor_lon, anchor_lat = float(track.lon[0]), float(track.lat[0])

    prof_d, prof_alt = track.smoothed_altitude(sigma_m=60.0, step_m=10.0)
    all_climbs = detect_climbs(prof_d, prof_alt)
    hero = hero_climb(all_climbs, min_gain_m=HERO_MIN_GAIN_M)
    climbs = featured_climbs(all_climbs, limit=3, include=hero)
    grid_x = gaussian_smooth(np.interp(prof_d, track.dist, rx), 6.0)
    grid_y = gaussian_smooth(np.interp(prof_d, track.dist, ry), 6.0)
    side = _side_view(grid_x, grid_y, prof_d, prof_alt, total_m, SIDE_EXAGGERATION, width, height, origin[1])

    # Act durations (seconds). The route is never shown ahead of the rider, so
    # the film opens on the start itself: a flat establishing shot centred on
    # it, from which the camera tilts and dives into the chase. The dive takes
    # longer the farther it falls (and so does the pull-back to the side view),
    # so neither moves faster than ~1.6 zoom levels/s.
    z_ov = TYPICAL_CHASE_ZOOM - OPENING_ZOOM_DROP
    cx_ov, cy_ov = float(rx[0]), float(ry[0])
    t_open_end = 3.5
    t_rise_end = t_open_end + float(np.clip(1.17 * (TYPICAL_CHASE_ZOOM - z_ov), 3.3, 5.5))
    base_ride_dur = _ride_duration(total_m, climbs, hero)
    hero_pause_s = 4.4 if hero is not None else 0.0
    t_ride_end = t_rise_end + base_ride_dur + hero_pause_s
    # Ending: the camera comes down beside the ride to the horizon, the route
    # lifts off the land and straightens into its own elevation profile.
    t_side_end = t_ride_end + float(np.clip(1.17 * (TYPICAL_CHASE_ZOOM - side.zoom), 3.6, 5.5))
    t_unfold_end = t_side_end + 4.4
    # The three totals (distance, ascent, moving time) fade in by +1.3 s, then hold.
    t_end = t_unfold_end + 1.3 + reading_hold_s(3) + CURTAIN_S

    frames = max(60, int(round(t_end * fps)))
    t = np.arange(frames, dtype=float) / float(fps)

    # Head progress & smoothed chase geometry.
    head, t_hero_start, t_hero_end = _build_head_schedule(
        t,
        t_start=t_rise_end,
        t_end=t_ride_end,
        length_m=total_m,
        climbs=climbs,
        hero=hero,
        hero_pause_s=hero_pause_s,
    )

    chase = solve_chase(
        t, head, prof_d, prof_alt, grid_x, grid_y, lat=origin[1], width=width, height=height, fps=fps
    )
    riding = (t >= t_rise_end) & (t <= t_ride_end)

    def ground_xy(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        if sampler is None:
            return np.full(np.shape(x), np.nan)
        lon, lat = from_local_xy(np.asarray(x), np.asarray(y), origin)
        return sampler.sample(lon, lat)

    # Exaggeration that makes this ride's relief readable at the chase scale.
    view_width_m = float(np.median(width * meters_per_pixel(chase.zoom[riding], origin[1])))
    exaggeration = adaptive_exaggeration(view_width_m, float(np.percentile(chase.local_relief[riding], 75)))

    # Nothing on the land around this ride stands higher than this (m, unscaled).
    relief_ceiling = float(prof_alt.max()) + 900.0

    # Swing the bearing towards the side where the relief hides the least road.
    chase_bearing = chase.bearing.copy()
    if sampler is not None:
        stride = max(1, fps // 4)
        keys = np.arange(0, frames, stride)
        ahead_pts = np.minimum(total_m, head[keys, None] + np.array([0.0, 250.0, 600.0, 1100.0])[None, :])
        tx = np.interp(ahead_pts, prof_d, grid_x)
        ty = np.interp(ahead_pts, prof_d, grid_y)
        tz = np.interp(ahead_pts, prof_d, prof_alt) + 3.0
        centre_ground = np.nan_to_num(ground_xy(chase.cx[keys], chase.cy[keys]), nan=float(np.median(prof_alt)))
        offset_keys = visible_bearing_offset(
            chase.bearing[keys],
            chase.pitch[keys],
            chase.zoom[keys],
            chase.cx[keys],
            chase.cy[keys],
            origin[1],
            height,
            tx,
            ty,
            tz,
            exaggeration,
            lambda x, y: np.nan_to_num(ground_xy(x, y), nan=-1e4),
            centre_ground * exaggeration,
            ceiling_m=relief_ceiling,
        )
        offset = gaussian_smooth(np.interp(np.arange(frames), keys, offset_keys), 1.1 * fps)
        chase_bearing = (chase.bearing + offset * riding) % 360.0
    chase_cx, chase_cy = chase.cx, chase.cy
    chase_zoom, chase_pitch = chase.zoom.copy(), chase.pitch.copy()

    # Hero climb seen three-quarter on (start lower left, summit upper right),
    # from whichever side sees more of it. The relief never changes scale
    # mid-ride: only the camera moves.
    beat = np.zeros(frames)
    hero_blend = np.zeros(frames)
    hero_window = np.zeros(frames, dtype=bool)
    hero_alt = np.zeros(frames)
    if hero is not None and t_hero_end > t_hero_start:
        hero_path = np.linspace(hero.start_m, hero.end_m, HERO_VIEW_SAMPLES)
        hero_px = np.interp(hero_path, prof_d, grid_x)
        hero_py = np.interp(hero_path, prof_d, grid_y)
        hero_pz = np.interp(hero_path, prof_d, prof_alt)
        mid_x, mid_y = float(hero_px.mean()), float(hero_py.mean())
        hero_mid_alt = float(np.interp(0.5 * (hero.start_m + hero.end_m), prof_d, prof_alt))
        view = _hero_view(
            hero_px, hero_py, hero_pz, (mid_x, mid_y, hero_mid_alt), exaggeration,
            ground_xy if sampler is not None else None, origin[1], width, height, relief_ceiling,
        )
        hero_zoom, hero_pitch, side_bearing = view.zoom, view.pitch, view.bearing
        # Fully in shortly after the crest leg starts, out before it ends: the
        # orbit in and out is one eased move each, never a snap.
        hero_blend = envelope(t, t_hero_start - 0.6 * HERO_FADE_S, t_hero_end + 0.6 * HERO_FADE_S, HERO_FADE_S)
        hero_window = (t > t_hero_start - 0.6 * HERO_FADE_S) & (t < t_hero_end + 0.6 * HERO_FADE_S)
        beat = envelope(t, t_hero_start - 0.5, t_hero_end + 0.3, 0.65)
        orbit_drift = span(t, t_hero_start - 0.5, t_hero_end + 0.5)
        hero_alt = np.full(frames, hero_mid_alt)
        chase_cx = chase_cx * (1.0 - hero_blend) + mid_x * hero_blend
        chase_cy = chase_cy * (1.0 - hero_blend) + mid_y * hero_blend
        chase_zoom = chase_zoom * (1.0 - hero_blend) + (hero_zoom + HERO_DOLLY_ZOOM * orbit_drift) * hero_blend
        chase_pitch = chase_pitch * (1.0 - hero_blend) + hero_pitch * hero_blend
        chase_bearing = lerp_angle(
            chase_bearing, side_bearing + HERO_ORBIT_DRIFT_DEG * orbit_drift, hero_blend
        )

    # Assemble full-timeline camera in local metres.
    cx = np.zeros(frames)
    cy = np.zeros(frames)
    zoom = np.zeros(frames)
    pitch = np.zeros(frames)
    bearing = np.zeros(frames)
    terrain = np.zeros(frames)
    contours = np.zeros(frames)
    map_opacity = np.ones(frames)

    for i, ti in enumerate(t):
        if ti < t_rise_end:
            w_rise = float(travel(span(np.array([ti]), t_open_end, t_rise_end)[0]))
            open_push = 0.10 * float(ease_in_out_sine(ti / max(t_rise_end, 1e-6)))
            cx[i] = cx_ov * (1.0 - w_rise) + chase_cx[i] * w_rise
            cy[i] = cy_ov * (1.0 - w_rise) + chase_cy[i] * w_rise
            zoom[i] = (z_ov - 0.05 + open_push) * (1.0 - w_rise) + chase_zoom[i] * w_rise
            pitch[i] = chase_pitch[i] * w_rise
            bearing[i] = float(lerp_angle(0.0, chase_bearing[i], w_rise))
            terrain[i] = exaggeration * float(travel(span(np.array([ti]), t_open_end, t_rise_end - 0.3)[0]))
            contours[i] = float(ease_in_out_sine(span(np.array([ti]), t_open_end + 0.5, t_rise_end)[0]))
        elif ti < t_ride_end:
            cx[i] = chase_cx[i]
            cy[i] = chase_cy[i]
            zoom[i] = chase_zoom[i]
            pitch[i] = chase_pitch[i]
            bearing[i] = chase_bearing[i]
            terrain[i] = exaggeration
            contours[i] = 1.0
        elif ti < t_side_end:
            # Orbit down beside the ride until the view is almost level.
            w_side = float(travel(span(np.array([ti]), t_ride_end, t_side_end)[0]))
            cx[i] = chase_cx[i] * (1.0 - w_side) + side.cx * w_side
            cy[i] = chase_cy[i] * (1.0 - w_side) + side.cy * w_side
            zoom[i] = chase_zoom[i] * (1.0 - w_side) + side.zoom * w_side
            pitch[i] = chase_pitch[i] * (1.0 - w_side) + SIDE_PITCH * w_side
            bearing[i] = float(lerp_angle(chase_bearing[i], side.bearing, w_side))
            terrain[i] = exaggeration * (1.0 - w_side) + SIDE_EXAGGERATION * w_side
            contours[i] = 1.0 - w_side
        else:
            # Level view held with a slow dolly (never a dead stop) while the
            # route unfolds and the land dissolves to black.
            drift = float(span(np.array([ti]), t_side_end, t_end)[0])
            cx[i] = side.cx
            cy[i] = side.cy
            zoom[i] = side.zoom + 0.06 * drift
            pitch[i] = SIDE_PITCH
            bearing[i] = side.bearing + 1.5 * drift
            terrain[i] = SIDE_EXAGGERATION
            contours[i] = 0.0
            map_opacity[i] = 1.0 - float(
                ease_in_out_sine(span(np.array([ti]), t_side_end + 0.03 * (t_unfold_end - t_side_end), t_side_end + 0.5 * (t_unfold_end - t_side_end))[0])
            )

    # Bearing: smoothed, then rate-limited: gently while chasing, a wider sweep
    # is allowed for the orbit down to the side view.
    bearing = smooth_angles(bearing, sigma=max(2.0, 0.65 * fps))
    max_rate = np.where(t <= t_ride_end, MAX_BEARING_RATE_DEG_S, SIDE_ORBIT_RATE_DEG_S) / float(fps)
    max_rate[hero_window] = HERO_ORBIT_RATE_DEG_S / float(fps)
    bearing = limit_rate(bearing, max_rate) % 360.0

    cam = CameraTrack(frames)
    cam.lon, cam.lat = from_local_xy(cx, cy, origin)
    cam.zoom = gaussian_smooth(zoom, max(1.5, 0.25 * fps))
    cam.pitch = np.where(terrain > 0.005, gaussian_smooth(pitch, max(1.5, 0.25 * fps)), 0.0)
    cam.bearing = bearing
    cam.terrain = terrain
    cam.globe = np.zeros(frames)
    cam.map_opacity = map_opacity
    cam.contours = contours
    # Relief shading deepens with the 3D.
    cam.shade = 1.0 + 0.9 * np.clip(terrain / max(exaggeration, 1e-6), 0.0, 1.0)

    # Explicit smoothed ground elevation so the camera never bobs over individual ridges.
    track_alt_at_head = np.interp(head, prof_d, prof_alt)
    if sampler is not None:
        sampled_ground = sampler.sample_blurred(cam.lon, cam.lat, radius_m=600.0)
        ground_m = np.where(np.isfinite(sampled_ground), sampled_ground, track_alt_at_head)
    else:
        ground_m = track_alt_at_head
    ground_m = gaussian_smooth(ground_m, max(2.0, 0.8 * fps))
    # While chasing, aim at the rider's own (time-smoothed) altitude: the head
    # then sits on its composition line even when the land ahead rises three
    # times exaggerated, and the camera climbs with the ride instead of bobbing.
    head_alt = gaussian_smooth(track_alt_at_head, max(2.0, 0.8 * fps))
    follow = envelope(t, t_open_end, t_ride_end + 0.6, 1.2)
    ground_m = ground_m * (1.0 - follow) + head_alt * follow
    # Over the hero climb, aim at its middle so it sits centred instead of floating.
    ground_m = ground_m * (1.0 - hero_blend) + hero_alt * hero_blend
    cam.elevation = np.where(cam.terrain > 0.0, ground_m * cam.terrain, 0.0)

    _enforce_eye_clearance(cam, cx, cy, ground_m, origin, sampler, height, fps, relief_ceiling, t < t_ride_end)
    # The level view aims at a fixed height so the profile baseline sits on its row.
    side_w = travel(span(t, t_ride_end, t_side_end))
    cam.elevation = cam.elevation * (1.0 - side_w) + side.elevation * side_w

    title_ch = envelope(t, 0.35, t_open_end + 0.1, 0.5)
    if look == "satellite":
        cam.satellite = np.clip((1.0 - 0.32 * title_ch) * cam.map_opacity, 0.0, 1.0)

    # Animated scalar channels.
    # The route is never shown ahead of the rider: it draws itself behind the
    # head and is whole only once the ride is over. The opening marks the start.
    head_dot = np.maximum(
        envelope(t, 0.45, t_rise_end - 0.45, 0.25),
        envelope(t, t_rise_end - 0.4, t_ride_end + 0.3, 0.35),
    )
    counters = envelope(t, t_rise_end - 0.2, t_ride_end + 0.2, 0.45)

    # Cumulative ascent scaled to the official catalog elevation gain.
    pos_diffs = np.maximum(0.0, np.diff(prof_alt, prepend=prof_alt[0]))
    cum_ascent = np.cumsum(pos_diffs)
    raw_total_gain = float(cum_ascent[-1])
    official_gain = (
        float(meta.elevation_gain_m)
        if meta.elevation_gain_m is not None and meta.elevation_gain_m > 0
        else raw_total_gain
    )
    if raw_total_gain > 1.0:
        cum_ascent = cum_ascent * (official_gain / raw_total_gain)
    ascent_ch = np.interp(head, prof_d, cum_ascent)

    tag_windows = _tag_windows(climbs, hero, head, t, t_hero_start, t_hero_end)
    traces = _trace_windows(climbs, hero, head, t, riding, t_hero_end)

    unfold_ch = travel(span(t, t_side_end, t_unfold_end))
    chart_ch = ease_in_out_sine(span(t, t_unfold_end - 0.5, t_unfold_end + 0.7))
    stats_ch = ease_in_out_sine(span(t, t_unfold_end + 0.2, t_unfold_end + 1.3))
    black_ch = fade_through_black(t, t_end, open_s=0.7, power=3.4)

    channels: dict[str, np.ndarray] = {
        "head": head,
        "headDot": head_dot,
        "title": title_ch,
        "counters": counters,
        # Scaled so the counter lands exactly on the catalog distance.
        "km": head / max(total_m, 1.0) * total_km,
        "ascent": ascent_ch,
        "beat": beat,
        "unfold": unfold_ch,
        "chart": chart_ch,
        "stats": stats_ch,
        "black": black_ch,
    }

    story_climbs = []
    for k, (start_s, end_s, fade_s) in enumerate(tag_windows):
        climb = climbs[k]
        summit_idx = int(np.searchsorted(track.dist, climb.end_m, side="left"))
        summit_idx = min(len(track.lon) - 1, max(0, summit_idx))
        channels[f"climb{k}"] = envelope(t, start_s, end_s, fade_s) if end_s > start_s else np.zeros(frames)
        trace = traces[k]
        if trace is not None:
            channels[f"trace{k}"] = envelope(t, trace[0], trace[2], 0.45) * counters
            channels[f"summit{k}"] = span(t, trace[1], trace[1] + TRACE_SUMMIT_S)
        climb_alt = np.interp(np.linspace(climb.start_m, climb.end_m, TRACE_SAMPLES), prof_d, prof_alt)
        story_climbs.append(
            {
                "lon": round(float(track.lon[summit_idx]), 6),
                "lat": round(float(track.lat[summit_idx]), 6),
                "alt": round(climb.end_alt, 1),
                "startAlt": round(climb.start_alt, 1),
                "startM": round(climb.start_m, 1),
                "endM": round(climb.end_m, 1),
                "hero": climb == hero,
                # The climb summed up under its trace once the summit is reached.
                "summary": f"{i18n.number(climb.length_m / 1000.0, 1)} km · {i18n.number(climb.grade_pct, 1)}%",
                "trace": trace is not None,
                # Metres above the climb's foot along it (evenly spaced), for its trace.
                "rise": np.round(climb_alt - climb_alt[0], 1).tolist(),
            }
        )

    # Opening headline: explicit --title > nearest place (<= 30 km) > distance fallback.
    extra_sources: list[str] = []
    if title_override is not None and title_override.strip():
        headline = sanitize_display_text(title_override.strip())
    else:
        near = nearest_place(
            anchor_lon,
            anchor_lat,
            max_distance_km=30.0,
            cache_dir=places_cache_dir,
            offline=offline,
        )
        if near is not None:
            headline = near.place.name
            if near.place.source:
                extra_sources.append(near.place.source)
        else:
            headline = f"{i18n.number(total_km, 1)} km"

    # Normalized profile (~600 samples) with a minimum 60 m vertical scale so flat rides stay calm.
    prof_grid = np.linspace(0.0, total_m, 600)
    prof_samples = np.interp(prof_grid, prof_d, prof_alt)
    min_alt = float(prof_samples.min())
    max_alt = float(prof_samples.max())
    alt_range = max(60.0, max_alt - min_alt)
    prof_norm = np.round(np.clip((prof_samples - min_alt) / alt_range, 0.0, 1.0), 4).tolist()
    peak_idx = int(np.argmax(prof_samples))
    peak_fraction = round(peak_idx / max(1, len(prof_samples) - 1), 4)

    moving_s = (
        float(meta.moving_time_s)
        if meta.moving_time_s and meta.moving_time_s > 0
        else float(track.elapsed[-1])
        if len(track.elapsed)
        else total_m / 7.5
    )
    hours_val, hours_unit = _format_hours(moving_s, i18n)

    story = {
        "title": {
            "label": _format_date(meta.start_date, i18n),
            "text": headline,
        },
        "labels": {
            "distance": i18n.text("scene3d.distance"),
            "ascent": i18n.text("scene3d.ascent"),
            "kmUnit": "km",
            "mUnit": "m",
            "peakAlt": f"{i18n.number(round(max_alt))} m",
        },
        "unfold": side.story(origin, prof_alt),
        "layout": _Layout.for_frame(width, height).story(),
        "totalM": round(total_m, 1),
        "profile": prof_norm,
        "peakFraction": peak_fraction,
        "climbs": story_climbs,
        "stats": [
            {"label": i18n.text("scene3d.distance"), "value": i18n.number(total_km, 1), "unit": "km"},
            {"label": i18n.text("scene3d.ascent"), "value": f"+{i18n.number(round(official_gain))}", "unit": "m"},
            {"label": i18n.text("scene3d.moving_time"), "value": hours_val, "unit": hours_unit},
        ],
    }

    return SceneSpec(
        kind="flyover",
        locale=i18n.locale,
        look=look,
        width=width,
        height=height,
        fps=fps,
        camera=cam,
        channels=channels,
        tracks=[track.encode()],
        story=story,
        credits_on_screen=credits_on_screen,
        extra_sources=tuple(extra_sources),
    )
