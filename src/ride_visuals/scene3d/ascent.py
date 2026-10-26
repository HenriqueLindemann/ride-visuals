"""Director for ``video ascent``: every ride's climbing chained into one profile, then folded into a line."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from itertools import groupby
from pathlib import Path

import numpy as np

from ride_visuals.i18n import DEFAULT_LOCALE, Translator
from ride_visuals.scene3d.camera import (
    CURTAIN_S,
    CameraTrack,
    ease_in_out_sine,
    envelope,
    fade_through_black,
    glide,
    reading_hold_s,
    span,
    travel,
)
from ride_visuals.scene3d.framing import fit_held, fit_view, hold_at, project_points, rate_limited_floor, smooth_cover
from ride_visuals.scene3d.landmarks import LANDMARKS
from ride_visuals.scene3d.places import DEFAULT_PLACES_CACHE_DIR, home_region, home_title
from ride_visuals.scene3d.spec import Look, SceneSpec
from ride_visuals.scene3d.strata import PeriodMode, resolve_period
from ride_visuals.scene3d.stretch import SceneRide
from ride_visuals.scene3d.track import (
    RideTrack,
    delta_encode,
    from_local_xy,
    gaussian_smooth,
    simplify_indices,
)

#: The profile stands in a vertical plane through home, running east: distance is drawn
#: shorter, heights are true. It is this many times as wide as it is tall (portrait, landscape).
AXIS_DEG = 90.0
ASPECT = (0.5, 1.0)
#: Climbing is read off the altitude smoothed over CLIMB_SIGMA_M, every CLIMB_STEP_M.
CLIMB_SIGMA_M = 60.0
CLIMB_STEP_M = 20.0
#: Profile detail kept: this share of the height reached by then, never finer than PROFILE_MIN_M.
PROFILE_SHARE = 4e-4
PROFILE_MIN_M = 0.5

OPENING_S = 3.4
#: Seconds the profile takes to build, before and after scaling with the number of rides.
BUILD_S = (16.0, 30.0)
#: The build sets off and lands over these shares of it, at one steady speed in between,
#: slowed wherever the line would outgrow the frame faster than this (doublings per second).
BUILD_EASE = (0.12, 0.3)
GROWTH_RATE = 0.4
#: Pacing: this share by log height (each tenfold about as long), the rest by height and distance.
LOG_SHARE = 0.65
LOG_FLOOR_M = 300.0
#: The accent trails the head by this long (s).
TAIL_S = 0.8
FOLD_S = 2.8
#: Folded, the line is ruled in Everests, tick by tick over this long (s).
RULER_S = 1.6
#: One name at a time: a thing is named as the line nears its top, a level just after it is crossed;
#: each stays this long once in (and NAME_FADE_S coming in, TAG_FADE_S in ascent.ts) before the next.
NAME_READ_S = 1.6
NAME_FADE_S = 0.6
#: A thing stands this share of its height clear of the profile (and of the thing before it).
OUTLINE_GAP = 0.25
#: A level runs this share of its height left of home.
LEVEL_REACH = 0.15

#: From over home's streets, to across at the profile, to level with the line (deg).
PITCH = (55.0, 78.0, 84.0)
#: The film opens this close over home, its streets' buildings in 3D (map zoom), swinging
#: round it this far (deg) and settling into the slow orbit as the line sets off.
OPENING_ZOOM = 16.8
OPENING_SWING = 24.0
ORBIT_DEG = 14.0
#: The content fills this box (fractions x0, y0, x1, y1): under the counters, room for names on the left.
FRAME_BOX = {False: (0.2, 0.28, 0.9, 0.84), True: (0.24, 0.3, 0.92, 0.8)}
#: The frame makes room for what is drawn this far ahead (s), and for a thing over FRAME_EASE_S before it comes in.
FRAME_AHEAD_S = 1.0
FRAME_EASE_S = 3.5
#: While the line climbs the frame holds this much room over it (never past the top it ends at);
#: a thing comes in, whole, once it fits in that room.
HEADROOM = 1.45
#: A skyline fades out over this share of its width at each end, and may run on past the box into the margin;
#: in portrait only this share of it either side of the summit is drawn (portrait, landscape).
SKYLINE_FADE = 0.2
SKYLINE_ROOM = 0.6
SKYLINE_SPAN = (0.6, 1.0)
#: Zoom levels per second the camera moves at most; and drifts back while the totals are read.
ZOOM_RATE = 0.55
PULL_SMOOTH_S = 2.2
CLOSING_DRIFT = 0.25
FRAME_POINTS = 300


def climbing(track: RideTrack, gain_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Distance along a ride and the climbing done by then (m), scaled to the recorded gain."""
    grid = np.append(np.arange(0.0, track.length_m, CLIMB_STEP_M), track.length_m)
    known = np.isfinite(track.alt)
    climb = np.zeros(len(grid))
    if known.sum() >= 2:
        alt = gaussian_smooth(np.interp(grid, track.dist[known], track.alt[known]), CLIMB_SIGMA_M / CLIMB_STEP_M)
        climb[1:] = np.cumsum(np.maximum(0.0, np.diff(alt)))
    if climb[-1] > 1e-6:
        return grid, climb * (gain_m / climb[-1])
    # No usable altitude: the recorded gain, spread evenly.
    return grid, gain_m * grid / max(grid[-1], 1e-9)


def _pace(x: np.ndarray, z: np.ndarray, span_xs: np.ndarray | None = None) -> np.ndarray:
    """Progress (0..1) at each profile vertex: by log height, then by height and period span."""
    x0 = x[0]
    x, z = x - x0, z - z[0]
    log = np.log1p(z / LOG_FLOOR_M) / np.log1p(max(z[-1], 1.0) / LOG_FLOOR_M)
    if span_xs is not None and len(span_xs) >= 2:
        along = np.interp(x + x0, span_xs, np.linspace(0.0, 1.0, len(span_xs)))
    else:
        along = x / max(x[-1], 1e-9)
    return LOG_SHARE * log + (1.0 - LOG_SHARE) * 0.5 * (z / max(z[-1], 1.0) + along)


def _build_plan(progress: np.ndarray, heights: np.ndarray, length: float) -> tuple[np.ndarray, float]:
    """Seconds into the build each vertex is reached, and the build's length (lengthened if it must be).

    The build sets off and lands softly, at one speed in between, but the
    line never outgrows the frame faster than GROWTH_RATE (heights from the
    first thing's up), so the camera can back away at an even pace.
    """
    tau = np.linspace(0.0, 1.0, 2001)
    speed = travel(tau / BUILD_EASE[0]) * travel((1.0 - tau) / BUILD_EASE[1])
    done = np.concatenate([[0.0], np.cumsum(0.5 * (speed[1:] + speed[:-1]))])
    grid = np.linspace(0.0, 1.0, 2001)
    story = np.diff(np.interp(grid, done / done[-1], tau))
    growth = np.diff(np.log2(np.maximum(np.interp(grid, progress, heights), LANDMARKS[0].height_m))) / GROWTH_RATE
    growth = smooth_cover(growth, 12.0)
    length = max(length, 1.25 * float(growth.sum()))
    lo, hi = 0.0, length
    for _ in range(40):
        k = 0.5 * (lo + hi)
        lo, hi = (k, hi) if np.maximum(k * story, growth).sum() < length else (lo, k)
    step = np.maximum(gaussian_smooth(np.maximum(lo * story, growth), 6.0), growth)
    at = np.concatenate([[0.0], np.cumsum(step)])
    return np.interp(progress, grid, at), float(at[-1])


def _around_summit(stroke: np.ndarray, share: float) -> np.ndarray:
    """A skyline cut to this share of its reach either side of the summit."""
    if share >= 1.0:
        return stroke
    x, z = stroke.T
    peak = x[int(np.argmax(z))]
    lo, hi = peak - share * (peak - x[0]), peak + share * (x[-1] - peak)
    inside = (x > lo) & (x < hi)
    ends = [[lo, float(np.interp(lo, x, z))], [hi, float(np.interp(hi, x, z))]]
    return np.vstack([ends[0], stroke[inside], ends[1]])


def _first_time(t: np.ndarray, values: np.ndarray, level: float) -> float:
    """When a non-decreasing series first reaches ``level`` (s), interpolated between frames."""
    i = int(np.searchsorted(values, level))
    if i <= 0:
        return float(t[0])
    if i >= len(values):
        return float(t[-1])
    f = (level - values[i - 1]) / max(values[i] - values[i - 1], 1e-9)
    return float(t[i - 1] + f * (t[i] - t[i - 1]))


def _spans(  # noqa: PLR0913
    ordered: Sequence[SceneRide],
    key: Callable[[SceneRide], tuple[int, ...]],
    label: Callable[[SceneRide], str],
    x_at: np.ndarray,
    floors: np.ndarray,
    done_at: Callable[[float], float],
    i18n: Translator,
) -> list[dict[str, object]]:
    """Consecutive rides grouped by ``key``: each group's stretch of the profile, its climbing, and when done."""
    out: list[dict[str, object]] = []
    k = 0
    for _, group in groupby(ordered, key=key):
        k1 = k + len(list(group))
        out.append({
            "label": label(ordered[k]),
            "x": [round(float(x_at[k]), 2), round(float(x_at[k1]), 2)],
            "z": [round(float(floors[k]), 1), round(float(floors[k1]), 1)],
            "value": f"+{i18n.number(floors[k1] - floors[k])} m",
            "t": round(done_at(float(x_at[k1])), 3),
        })
        k = k1
    return out


def build_ascent_spec(  # noqa: PLR0913, PLR0915
    rides: Sequence[SceneRide],
    *,
    period: PeriodMode = "auto",
    locale: str = DEFAULT_LOCALE,
    look: Look = "carbon",
    width: int = 1920,
    height: int = 1080,
    fps: int = 60,
    home: tuple[float, float] | None = None,
    title_override: str | None = None,
    credits_on_screen: bool = False,
    places_cache_dir: Path = DEFAULT_PLACES_CACHE_DIR,
    offline: bool = False,
) -> SceneSpec:
    """Build the frame-by-frame spec for ``video ascent`` (home by default: where most of the climbing starts)."""
    ordered = sorted((r for r in rides if len(r.track.lon) >= 2 and r.track.length_m > 0), key=lambda r: r.start_date)
    gains = np.array([max(0.0, r.elevation_gain_m) for r in ordered])
    total = float(gains.sum())
    if total < 1.0:
        raise ValueError("The selected rides have no elevation gain to stack")
    i18n = Translator(locale)
    n = len(ordered)
    portrait = height > width
    starts = [(float(r.track.lon[0]), float(r.track.lat[0])) for r in ordered]
    (home_lon, home_lat), near = home_region(starts, home=home, weights=gains)
    origin = (home_lon, home_lat)
    ux, uy = np.sin(np.radians(AXIS_DEG)), np.cos(np.radians(AXIS_DEG))

    # The profile: each ride's climbing over its distance, chained, so
    # the line rises by exactly what was climbed. Plane metres per metre
    # ridden make it ASPECT times as wide as it is tall.
    lengths = np.array([r.track.length_m for r in ordered])
    scale = ASPECT[0 if portrait else 1] * total / float(lengths.sum())
    starts_m = np.concatenate([[0.0], np.cumsum(lengths)])
    floors = np.concatenate([[0.0], np.cumsum(gains)])
    xs, zs = [], []
    for k, ride in enumerate(ordered):
        grid, climb = climbing(ride.track, gains[k])
        px, pz = scale * (starts_m[k] + grid), floors[k] + climb
        keep = simplify_indices(px, pz, max(PROFILE_MIN_M, PROFILE_SHARE * floors[k + 1]))
        xs.append(px[keep][1 if k else 0 :])
        zs.append(pz[keep][1 if k else 0 :])
    prof_x, prof_z = np.concatenate(xs), np.concatenate(zs)

    # Head: where the profile is drawn to, by time, from home's doorstep.
    # Its vertices are reached on a log-height pace, eased off and in (see
    # _build_plan), with each period given an equal share of the distance term
    # so short or low-gain months are never skipped.
    def year(r: SceneRide) -> tuple[int, ...]:
        return (r.start_date.year,)

    def month(r: SceneRide) -> tuple[int, ...]:
        return (r.start_date.year, r.start_date.month)

    by_month = resolve_period(ordered[0].start_date, ordered[-1].start_date, period) == "month"
    x_at = scale * starts_m
    span_breaks = [0]
    for _, group in groupby(ordered, key=month if by_month else year):
        span_breaks.append(span_breaks[-1] + len(list(group)))
    span_xs = x_at[span_breaks]

    t_build = OPENING_S + 0.2
    build_s = min(float(np.clip(BUILD_S[0] + 0.03 * n, *BUILD_S)), 2.5 + 2.2 * n)
    if len(prof_x) >= 2:
        reach, build_s = _build_plan(np.clip(_pace(prof_x, prof_z, span_xs), 0.0, 1.0), prof_z, build_s)
    t_built = t_build + build_s
    t_fold = t_built + 0.9
    t_folded = t_fold + FOLD_S

    # Things anyone knows, in order: only those the line reaches.
    passed = [mark for mark in LANDMARKS if mark.height_m <= total]
    # Folded, the line is ruled in Everests, the height cyclists climb in one ride when they go Everesting.
    everest = next(mark for mark in LANDMARKS if mark.key == "everest")
    times = int(total // everest.height_m)
    ruled = times >= 2
    t_end = t_folded + 0.6 + (RULER_S if ruled else 0.0) + reading_hold_s(2) + CURTAIN_S
    frames = max(60, int(round(t_end * fps)))
    t = np.arange(frames, dtype=float) / float(fps)

    if len(prof_x) >= 2:
        head = np.interp(t, t_build + reach, prof_x)
        climbed = np.interp(t, t_build + reach, prof_z)
    else:
        head = np.full(frames, prof_x[-1])
        climbed = np.full(frames, total)
    climbed = np.maximum.accumulate(climbed)
    tail = np.interp(t - TAIL_S, t, head)
    fold = travel(span(t, t_fold, t_folded))

    # Things stand left of home at true scale, each clear of those before
    # it at the same heights; levels run across from where the line crosses them.
    heights: list[dict[str, object]] = []
    stood: list[tuple[float, float]] = []
    named = -np.inf
    for mark in passed:
        t_at = _first_time(t, climbed, mark.height_m)
        if mark.shape == "level":
            x_hi = float(np.interp(t_at, t, head))
            strokes = [[[round(-LEVEL_REACH * mark.height_m, 1), mark.height_m], [round(x_hi, 1), mark.height_m]]]
            t0 = t_at
        else:
            marks = [np.array(st, dtype=float) for st in mark.strokes]
            if mark.shape == "skyline":
                marks = [_around_summit(st, SKYLINE_SPAN[0 if portrait else 1]) for st in marks]
            pts = np.concatenate(marks)
            bottom = float(pts[:, 1].min())
            right = min([-OUTLINE_GAP * mark.height_m] + [end for end, high in stood if high >= bottom])
            shift = right - float(pts[:, 0].max())
            stood.append((shift + float(pts[:, 0].min()) - OUTLINE_GAP * 0.4 * mark.height_m, mark.height_m))
            strokes = [[[round(x + shift, 1), round(z, 1)] for x, z in st] for st in marks]
            t0 = min(_first_time(t, climbed, mark.height_m / HEADROOM), t_at - 0.4)
        named = max(t_at + NAME_FADE_S if mark.shape == "level" else t0 + 0.6 * (t_at - t0), named + 2 * NAME_FADE_S + NAME_READ_S)
        heights.append({
            "key": mark.key,
            "at": mark.height_m,
            "shape": mark.shape,
            "strokes": strokes,
            "t0": round(t0, 3),
            "t": round(t_at, 3),
            "named": round(named, 3),
            "glyph": [[list(pt) for pt in st] for st in mark.glyph] or None,
            "name": i18n.text(f"scene3d.height.{mark.key}"),
            "value": f"{i18n.number(mark.height_m)} m",
        })

    # Camera: opens low over home's streets, tilts up across the plane as
    # the line sets off from the doorstep, backs away as it rises, and
    # comes level with it as it folds.
    swing = OPENING_SWING * (1.0 - glide(span(t, 0.0, t_build + 2.0), power=2.0))
    bearing = AXIS_DEG - 90.0 + ORBIT_DEG * (span(t, 0.0, t_end) - 0.5) - swing
    climbing_on = travel(span(t, t_build - 1.0, t_build + 1.5))
    pitch_of = PITCH[0] + (PITCH[1] - PITCH[0]) * ease_in_out_sine(span(t, t_build - 1.0, t_build + 1.5))
    pitch = pitch_of + (PITCH[2] - PITCH[1]) * ease_in_out_sine(span(t, t_built - 2.0, t_folded))
    keys = np.arange(0, frames, max(1, round(fps / 6)))
    box = FRAME_BOX[portrait]
    shots = []
    for i in keys:
        ahead = min(t[i] + FRAME_AHEAD_S, t_built)
        h = float(np.interp(ahead, t, head))
        shown = prof_x <= h
        stride = max(1, int(shown.sum()) // FRAME_POINTS)
        squash = 1.0 - float(fold[i])
        along = np.append(prof_x[shown][::stride], h) * squash
        up = np.append(prof_z[shown][::stride], float(np.interp(ahead, t, climbed)))
        # The ground under it too, so the base stays in frame, and the room it
        # climbs into: from the first thing's height, never past where it ends.
        room = 1.0 + (HEADROOM - 1.0) * float(climbing_on[i])
        # (a soft minimum, so the frame settles onto the top rather than stopping at it).
        reach = max(room * float(climbed[i]), float(climbing_on[i]) * LANDMARKS[0].height_m, 1.0)
        roof = (reach**-3 + total**-3) ** (-1 / 3)
        along = np.concatenate([along, [0.0, along.max(), 0.0]])
        up = np.concatenate([up, [0.0, 0.0, roof]])
        # And the things and levels, eased into the frame as they come in.
        for thing in heights:
            weight = float(travel((t[i] + FRAME_AHEAD_S - thing["t0"] + FRAME_EASE_S) / (FRAME_EASE_S + 0.5)))
            if weight <= 0.0:
                continue
            pts = np.array([pt for st in thing["strokes"] for pt in st], dtype=float)
            peak = float(pts[:, 1].max())
            # A skyline's ends fade out (THING.taper in ascent.ts) and need no room.
            far = float(pts[:, 0].min())
            if thing["shape"] == "skyline":
                far = SKYLINE_ROOM * (far + SKYLINE_FADE * float(np.ptp(pts[:, 0])))
            # Its top is in the room above the line by the time it comes in.
            along = np.concatenate([along, [weight * far]])
            up = np.concatenate([up, [min(peak, roof)]])
        shots.append((along * ux, along * uy, up))

    # Home holds its height on screen while the line climbs, and drifts
    # across only one way, as slowly as it can (no sway or bob as things
    # come and go): where a free frame would put it, made monotone and
    # smooth. It moves to the centre as the profile folds onto it. The zoom
    # is the closest that keeps everything in the box with home held there.
    zero = np.zeros(1)
    seen = np.zeros((len(keys), 2))
    free_zoom = np.zeros(len(keys))
    for j, i in enumerate(keys):
        free = fit_view(*shots[j], float(pitch[i]), float(bearing[i]), home_lat, width, height, box, lift=True, zoom_range=(3.0, OPENING_ZOOM))
        free_zoom[j] = free[3]
        seen[j] = [v[0] for v in project_points(*free, float(pitch[i]), float(bearing[i]), home_lat, width, height, zero, zero, zero)[:2]]
    building = climbing_on[keys][:, None]
    held = np.average(seen, axis=0, weights=building[:, 0] * (1.0 - fold[keys]) + 1e-9)
    climbing_keys = (building[:, 0] > 0.999) & (fold[keys] < 0.001)
    if climbing_keys.sum() >= 2:
        across = seen[climbing_keys, 0]
        sign = 1.0 if across[-1] >= across[0] else -1.0
        drift = 0.5 * (sign * np.maximum.accumulate(sign * across) + (sign * np.minimum.accumulate((sign * across)[::-1]))[::-1])
        held_x = np.interp(t[keys], t[keys][climbing_keys], gaussian_smooth(drift, 3.0 * fps / max(1, fps // 6)))
        held = np.column_stack([held_x, np.full(len(keys), held[1])])
    anchors = seen + (held - seen) * building
    anchors[:, 0] += (0.5 * width - anchors[:, 0]) * fold[keys]
    fit_zoom = np.array([
        fit_held(
            *shots[j], float(pitch[i]), float(bearing[i]), home_lat, width, height, box, (0.0, 0.0, 0.0), tuple(anchors[j]),
            lift=True, zoom_range=(free_zoom[j] - 4.0, free_zoom[j] + 0.05),
        )
        for j, i in enumerate(keys)
    ])

    index = np.arange(frames)
    sigma = 0.6 * fps
    zoom = np.interp(index, keys, fit_zoom)
    # The fold is a move of its own: folded, the line is narrower, and the
    # camera may close in on it in step (until then it only backs away).
    i_fold = int(np.searchsorted(t, t_fold))
    folded = float(zoom[min(int(np.searchsorted(t, t_folded)), frames - 1) :].min())
    zoom[i_fold:] = zoom[i_fold - 1]
    # Only ever backing away, from the first frame on.
    zoom = np.minimum.accumulate(zoom)
    # One steady pull: backing away starts early rather than ever rushing,
    # and its speed swells and settles in one curve (smoothed as a speed),
    # let out only where it would come closer than the frame allows.
    floor = rate_limited_floor(zoom, ZOOM_RATE / fps)
    pull = floor[0] + np.cumsum(gaussian_smooth(np.diff(floor, prepend=floor[0]), PULL_SMOOTH_S * fps))
    zoom = pull - smooth_cover(np.maximum(0.0, pull - floor), PULL_SMOOTH_S * fps)
    zoom = np.minimum.accumulate(zoom)
    zoom = gaussian_smooth(np.minimum(zoom, gaussian_smooth(zoom, sigma)), sigma)
    zoom = zoom + max(0.0, folded - float(zoom[i_fold])) * fold
    # Never still: the pull settles into a slow drift back while the line lands and the totals are read.
    zoom = zoom - CLOSING_DRIFT * ease_in_out_sine(span(t, t_built - 6.0, t_end + 1.0))
    # Where the camera looks: whatever puts home on its mark at that zoom.
    marks = np.column_stack([gaussian_smooth(np.interp(index, keys, anchors[:, c]), sigma) for c in range(2)])
    aim = np.zeros((frames, 3))
    for i in index:
        start = (0.0, 0.0, 0.0) if i == 0 else tuple(aim[i - 1])
        aim[i] = hold_at((0.0, 0.0, 0.0), tuple(marks[i]), float(zoom[i]), float(pitch[i]), float(bearing[i]), home_lat, width, height, start, lift=True)
    cx, cy, cz = aim.T

    cam = CameraTrack(frames)
    cam.lon, cam.lat = from_local_xy(cx, cy, origin)
    cam.zoom = zoom
    cam.pitch = pitch
    cam.bearing = bearing % 360.0
    cam.elevation = cz
    # Home's streets stand in 3D while the camera is close, and sink back into the flat map
    # over two zoom levels, ending where the map stops holding buildings (zoom 13).
    cam.buildings = travel(span(zoom, 13.4, 15.6))
    across = span(pitch, PITCH[0], PITCH[1])
    cam.contours = 0.5 * (1.0 - across)
    cam.shade = 1.3 - 0.3 * across
    cam.map_opacity = 1.0 - 0.35 * across
    if look == "satellite":
        cam.satellite = 1.0 - across

    # Folded, the line is ruled in Everests, then the totals come in.
    t_ruler = t_folded - 0.2
    stats_t = t_ruler + RULER_S - 0.4 if ruled else t_folded + 0.2
    channels = {
        "opening": envelope(t, 0.35, OPENING_S + 0.2, 0.45),
        "counter": ease_in_out_sine(span(t, t_build, t_build + 0.6)),
        "climbed": climbed,
        "head": head,
        "tail": tail,
        "live": ease_in_out_sine(span(t, t_build - 0.3, t_build + 0.1)) * (1.0 - ease_in_out_sine(span(t, t_built, t_built + 0.8))),
        "fold": fold,
        "ruler": span(t, t_ruler, t_ruler + RULER_S) if ruled else np.zeros(frames),
        "stats": ease_in_out_sine(span(t, stats_t, stats_t + 1.0)),
        "fade": 1.0 - 0.3 * ease_in_out_sine(span(t, t_end - 1.1, t_end)),
        "black": fade_through_black(t, t_end, open_s=0.65),
    }

    # The map: rides ridden from home, drawn flat as their climbing joins the profile.
    tracks: list[dict[str, list[int]]] = []
    story_rides = []
    multi_year = ordered[0].start_date.year != ordered[-1].start_date.year
    for k, ride in enumerate(ordered):
        index_k = None
        if near[k]:
            index_k = len(tracks)
            tracks.append(ride.track.encode(tolerance_m=6.0, max_vertices=1_500))
        story_rides.append({
            "x0": round(float(scale * starts_m[k]), 2),
            "track": index_k,
            "period": i18n.month_name(ride.start_date.month, ride.start_date.year if multi_year else None),
        })

    # How it grew: each year or month divided off along the base, with its
    # climbing once done. Months over several years are grouped in years.
    reached = np.maximum.accumulate(head)

    def done_at(x: float) -> float:
        return _first_time(t, reached, x - 1e-3)

    def year_label(r: SceneRide) -> str:
        return str(r.start_date.year)

    def month_label(r: SceneRide) -> str:
        return i18n.month_short(r.start_date)

    periods = _spans(ordered, *((month, month_label) if by_month else (year, year_label)), x_at, floors, done_at, i18n)
    groups = _spans(ordered, year, year_label, x_at, floors, done_at, i18n) if by_month and multi_year else []
    if len(periods) < 2:
        periods = []

    opening_text, extra_sources = home_title(
        origin, title_override, i18n.text("scene3d.rides_count", count=n), cache_dir=places_cache_dir, offline=offline
    )
    story = {
        "home": [round(home_lon, 6), round(home_lat, 6)],
        "axis": AXIS_DEG,
        "scale": scale,
        "profile": {"x": delta_encode(prof_x, 10.0), "z": delta_encode(prof_z, 10.0)},
        "rides": story_rides,
        "periods": periods,
        "groups": groups,
        "heights": heights,
        "ruler": {"at": everest.height_m, "count": times} if ruled else None,
        "opening": {
            "label": i18n.text(
                "scene3d.strata.kicker", start=i18n.date(ordered[0].start_date), end=i18n.date(ordered[-1].start_date)
            ),
            "text": opening_text,
        },
        "counter": {"label": i18n.text("scene3d.ascent"), "unit": "m"},
        "stats": [
            {"label": i18n.text("scene3d.ascent"), "value": f"+{i18n.number(total)}", "unit": "m"},
            *([{"label": i18n.text("scene3d.height.everest"), "value": f"{times}×"}] if ruled else []),
            {"label": i18n.text("scene3d.rides"), "value": i18n.number(n)},
        ],
    }
    return SceneSpec(
        kind="ascent",
        locale=i18n.locale,
        look=look,
        width=width,
        height=height,
        fps=fps,
        camera=cam,
        channels=channels,
        tracks=tracks,
        story=story,
        credits_on_screen=credits_on_screen,
        extra_sources=extra_sources,
    )
