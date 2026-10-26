"""Director for ``video territory``: every different road ridden, each drawn once.

New roads come in in the accent and cool into the territory; known roads only
light up while ridden again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ride_visuals.i18n import DEFAULT_LOCALE, Translator
from ride_visuals.scene3d.camera import (
    CURTAIN_S,
    CameraTrack,
    ease_in_out_sine,
    envelope,
    fade_through_black,
    reading_hold_s,
    span,
    travel,
)
from ride_visuals.scene3d.framing import fit_view, principal_bearing
from ride_visuals.scene3d.places import DEFAULT_PLACES_CACHE_DIR, home_region, home_title
from ride_visuals.scene3d.spec import Look, SceneSpec
from ride_visuals.scene3d.stretch import SceneRide
from ride_visuals.scene3d.track import from_local_xy, gaussian_smooth, local_xy

#: Road matching: samples every SAMPLE_M along a ride, on a grid of CELL_M; a
#: sample is known when any of the 3x3 cells around it was ridden before,
#: which absorbs GPS drift and the other side of the road.
SAMPLE_M = 10.0
CELL_M = 40.0
#: A ride meets its own trace again (an out-and-back) only this far behind.
SELF_LAG_M = 400.0
#: New stretches shorter than this are drift or a crossing, not a road; gaps
#: shorter than MERGE_M inside a new stretch do not split it.
MIN_FRESH_M = 120.0
MERGE_M = 60.0
#: A new stretch is drawn this much longer at each end, so a branch meets the road it leaves.
JOIN_M = 1.5 * CELL_M
#: Seconds of the build for the whole collection, before and after scaling with its size.
BUILD_S = (16.0, 36.0)
#: How long one ride takes to draw (s): longer rides take a little longer.
RIDE_DRAW_S = (0.6, 2.2)
OPENING_S = 3.6
TILT_PITCH = 44.0
TILT_PITCH_PORTRAIT = 34.0
ORBIT_DEG = 26.0
#: The territory is framed on its body: these percentiles of its roads (per axis), never smaller than MIN_SPAN_M,
#: judged on at most FRAME_POINTS of them.
EXTENT_PCT = 2.5
FRAME_POINTS = 400
#: Islands of the territory (see _main_territory): grid size, and the share that earns a place in the frame.
ISLAND_CELL_M = 2_000.0
ISLAND_SHARE = 0.08
MIN_SPAN_M = 4_000.0
#: The frame makes room for the roads drawn this far ahead (s).
FRAME_AHEAD_S = 1.2
#: Wear: the territory is cut into pieces about this long, each brightening
#: as it is ridden again, over this many steps up to the most ridden piece.
PIECE_M = 80.0
WEAR_LEVELS = 8


@dataclass(frozen=True)
class TerritoryBuildResult:
    """Built territory scene spec and how many rides were outside the home region."""

    spec: SceneSpec
    kept_rides: int
    excluded_rides: int
    distinct_km: float


def fresh_intervals(rides_xy: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]]) -> list[list[tuple[float, float]]]:
    """For each ride (x, y, distance arrays in local metres), the stretches (m) on roads not ridden before.

    Rides are taken in the given (chronological) order.
    """
    seen: dict[tuple[int, int], None] = {}
    out: list[list[tuple[float, float]]] = []
    for x, y, d in rides_xy:
        if len(d) < 2 or d[-1] <= 0:
            out.append([])
            continue
        s = np.arange(0.0, float(d[-1]), SAMPLE_M)
        cx = np.floor(np.interp(s, d, x) / CELL_M).astype(np.int64).tolist()
        cy = np.floor(np.interp(s, d, y) / CELL_M).astype(np.int64).tolist()
        mine: dict[tuple[int, int], float] = {}
        fresh = np.zeros(len(s), dtype=bool)
        for i, (a, b) in enumerate(zip(cx, cy, strict=True)):
            known = False
            for da in (-1, 0, 1):
                for db in (-1, 0, 1):
                    key = (a + da, b + db)
                    if key in seen or (key in mine and s[i] - mine[key] > SELF_LAG_M):
                        known = True
                        break
                if known:
                    break
            fresh[i] = not known
            mine.setdefault((a, b), float(s[i]))
        seen.update(dict.fromkeys(mine))
        out.append(_runs(s, fresh, float(d[-1])))
    return out


def _runs(s: np.ndarray, fresh: np.ndarray, length: float) -> list[tuple[float, float]]:
    runs: list[list[float]] = []
    start = None
    for i, flag in enumerate(fresh.tolist()):
        if flag and start is None:
            start = float(s[i])
        elif not flag and start is not None:
            runs.append([start, float(s[i])])
            start = None
    if start is not None:
        runs.append([start, length])
    merged: list[list[float]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] < MERGE_M:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [(round(a, 1), round(b, 1)) for a, b in merged if b - a >= MIN_FRESH_M]


def _pass_times(d: np.ndarray, s: np.ndarray, t0: float, dur: float) -> np.ndarray:
    """When the player's head reaches distances ``s`` along a ride (s); it eases as ``travel``."""
    share = np.linspace(0.0, 1.0, 257)
    return t0 + dur * np.interp(s / max(float(d[-1]), 1.0), travel(share), share)


def wear_steps(
    rides_xy: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]],
    fresh: Sequence[Sequence[tuple[float, float]]],
    t0: np.ndarray,
    draw_s: np.ndarray,
) -> tuple[list[list[list[list[float]]]], list[int]]:
    """When each piece of new road reaches each wear level (s), and the ride counts of the levels.

    Per ride, per new stretch, per piece (PIECE_M): the times it is ridden
    for the 2nd, ... time at each level's count; counts grow geometrically up
    to the most ridden piece. A ride counts once per piece.
    """
    keys: list[np.ndarray] = []
    owners: list[np.ndarray] = []
    born: list[float] = []
    layout: list[list[int]] = []
    for k, ((x, y, d), runs) in enumerate(zip(rides_xy, fresh, strict=True)):
        counts = []
        for a, b in runs:
            n = max(1, int(round((b - a) / PIECE_M)))
            counts.append(n)
            s = np.arange(a, b, SAMPLE_M)
            piece = len(born) + np.minimum((s - a) / (b - a) * n, n - 1).astype(np.int64)
            keys.append(_cell_keys(np.interp(s, d, x), np.interp(s, d, y)))
            owners.append(piece)
            born.extend(_pass_times(d, a + (np.arange(n) + 0.5) * (b - a) / n, float(t0[k]), float(draw_s[k])).tolist())
        layout.append(counts)
    if not born:
        return [[] for _ in rides_xy], [1]
    all_keys = np.concatenate(keys)
    all_owners = np.concatenate(owners)
    # The first piece to claim a cell owns it.
    order = np.argsort(all_keys, kind="stable")
    cell_keys, first = np.unique(all_keys[order], return_index=True)
    cell_owner = all_owners[order][first]

    passes: list[list[float]] = [[] for _ in born]
    for k, (x, y, d) in enumerate(rides_xy):
        if len(d) < 2 or d[-1] <= 0:
            continue
        s = np.arange(0.0, float(d[-1]), SAMPLE_M)
        cx = np.floor(np.interp(s, d, x) / CELL_M).astype(np.int64)
        cy = np.floor(np.interp(s, d, y) / CELL_M).astype(np.int64)
        found = np.full(len(s), -1, dtype=np.int64)
        for da, db in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            probe = _pack(cx + da, cy + db)
            at = np.minimum(np.searchsorted(cell_keys, probe), len(cell_keys) - 1)
            hit = (found < 0) & (cell_keys[at] == probe)
            found[hit] = cell_owner[at[hit]]
        on = found >= 0
        if not on.any():
            continue
        pieces, idx = np.unique(found[on], return_index=True)
        when = _pass_times(d, s[on][idx], float(t0[k]), float(draw_s[k]))
        for piece, t_pass in zip(pieces.tolist(), when.tolist(), strict=True):
            # A pass before the piece is drawn is the neighbourhood's slack, not a ride on it.
            if t_pass >= born[piece] - 0.05:
                passes[piece].append(t_pass)

    top = max(len(p) for p in passes)
    levels = sorted({int(np.ceil(top ** (j / WEAR_LEVELS))) for j in range(WEAR_LEVELS + 1)} - {1})
    steps = []
    for p in passes:
        p.sort()
        steps.append([round(p[c - 1], 3) for c in levels if c <= len(p)])
    out: list[list[list[list[float]]]] = []
    cursor = 0
    for counts in layout:
        ride_steps = []
        for n in counts:
            ride_steps.append(steps[cursor:cursor + n])
            cursor += n
        out.append(ride_steps)
    return out, [1, *levels]


def _pack(cx: np.ndarray, cy: np.ndarray) -> np.ndarray:
    return (cx + (1 << 30)) * (1 << 31) + (cy + (1 << 30))


def _cell_keys(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return _pack(np.floor(x / CELL_M).astype(np.int64), np.floor(y / CELL_M).astype(np.int64))


def _territory_points(
    rides_xy: Sequence[tuple[np.ndarray, np.ndarray, np.ndarray]],
    fresh: Sequence[Sequence[tuple[float, float]]],
    t0: np.ndarray,
    draw_s: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Points every ~100 m along every new road (local metres), and when the player draws each (s)."""
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    when: list[np.ndarray] = []
    for k, ((x, y, d), runs) in enumerate(zip(rides_xy, fresh, strict=True)):
        for a, b in runs:
            s = np.linspace(a, b, max(2, int((b - a) / 100.0)))
            xs.append(np.interp(s, d, x))
            ys.append(np.interp(s, d, y))
            when.append(_pass_times(d, s, float(t0[k]), float(draw_s[k])))
    if not xs:
        return np.zeros(1), np.zeros(1), np.zeros(1)
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(when)


def _main_territory(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Mask of the connected parts of the territory worth framing: home's, and any holding a real share of it.

    Points are joined into islands on a grid of ISLAND_CELL_M; a trip out to
    a lone road far from the rest (a day at the coast) is left out of the
    frame rather than shrinking everything else into a corner.
    """
    cells = [tuple(c) for c in np.stack([x // ISLAND_CELL_M, y // ISLAND_CELL_M], axis=1).astype(np.int64).tolist()]
    occupied = set(cells)
    label: dict[tuple[int, int], int] = {}
    for start in occupied:
        if start in label:
            continue
        group = len(set(label.values()))
        label[start] = group
        stack = [start]
        while stack:
            cx, cy = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nb = (cx + dx, cy + dy)
                    if nb in occupied and nb not in label:
                        label[nb] = group
                        stack.append(nb)
    groups = np.array([label[c] for c in cells])
    counts = np.bincount(groups)
    # Home is the local origin: its island is the one nearest to it.
    home = groups[int(np.argmin(np.hypot(x, y)))]
    keep = (groups == home) | (counts[groups] >= ISLAND_SHARE * len(x))
    return keep


def _draw_progress(t: np.ndarray, t0: float, dur: float) -> np.ndarray:
    """Share of a ride drawn at times ``t`` (the player eases the same way: smootherstep)."""
    return travel(span(t, t0, t0 + dur))


def build_territory_spec(  # noqa: PLR0913, PLR0915
    rides: Sequence[SceneRide],
    *,
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
) -> TerritoryBuildResult:
    """Build the frame-by-frame spec for ``video territory``."""
    valid = [r for r in rides if len(r.track.lon) >= 2 and r.track.length_m >= 100.0]
    if not valid:
        raise ValueError("No valid rides with GPS tracks found for the selected scope")
    i18n = Translator(locale)

    (home_lon, home_lat), near = home_region([(float(r.track.lon[0]), float(r.track.lat[0])) for r in valid], home=home)
    regional = sorted((r for r, keep in zip(valid, near.tolist(), strict=True) if keep), key=lambda r: r.start_date)
    excluded = len(valid) - len(regional)
    origin = (home_lon, home_lat)
    n = len(regional)

    rides_xy = []
    for ride in regional:
        x, y = local_xy(ride.track.lon, ride.track.lat, origin)
        rides_xy.append((x, y, ride.track.dist))
    fresh = fresh_intervals(rides_xy)
    distinct_m = sum(b - a for runs in fresh for a, b in runs)

    # Timeline: rides placed half by order, half by date, so a quiet season
    # still reads as quiet without crowding a busy one.
    build_s = float(np.clip(BUILD_S[0] + 0.05 * n, *BUILD_S))
    stamps = np.array([r.start_date.timestamp() for r in regional], dtype=float)
    by_date = (stamps - stamps[0]) / max(stamps[-1] - stamps[0], 1.0)
    by_rank = np.arange(n) / max(n - 1, 1)
    place = 0.5 * by_date + 0.5 * by_rank
    draw_s = np.clip(RIDE_DRAW_S[0] + np.array([r.track.length_m for r in regional]) / 60_000.0, *RIDE_DRAW_S)
    t_build = OPENING_S + 0.4
    t0 = t_build + place * (build_s - draw_s.max() * 0.5)
    t_built = float(np.max(t0 + draw_s)) + 0.6
    t_end = t_built + 1.0 + reading_hold_s(3) + CURTAIN_S
    frames = max(60, int(round(t_end * fps)))
    t = np.arange(frames, dtype=float) / float(fps)

    wear, wear_counts = wear_steps(rides_xy, fresh, t0, draw_s)

    # Distinct distance revealed, exactly as the player draws it.
    revealed = np.zeros(frames)
    for k, runs in enumerate(fresh):
        if not runs:
            continue
        drawn = _draw_progress(t, float(t0[k]), float(draw_s[k])) * regional[k].track.length_m
        for a, b in runs:
            revealed += np.clip(drawn - a, 0.0, b - a)

    # Camera: opens top-down on home, then one continuous move out to the
    # whole territory, framed from the start so nothing ever leaves the frame
    # while it is being drawn. What is framed is the territory itself (every
    # new road, sampled evenly along it), so each road weighs its length once
    # however often it was ridden.
    pts_x, pts_y, pts_t = _territory_points(rides_xy, fresh, t0, draw_s)
    keep = _main_territory(pts_x, pts_y)
    pts_x, pts_y, pts_t = pts_x[keep], pts_y[keep], pts_t[keep]
    portrait = height > width
    # The territory's long axis runs across the frame (down it in portrait),
    # so an elongated city fills the screen instead of a corner of it.
    axis_deg = principal_bearing(pts_x, pts_y) + (0.0 if portrait else 90.0)
    # An axis has two directions: take the one nearer north-up, the smaller turn from the opening.
    axis_deg = (axis_deg + 90.0) % 180.0 - 90.0
    view = np.radians(axis_deg)
    # The territory's extremes (a long road ridden once) may run off the edge;
    # the frame is for its body. Trimmed in the view's own axes (u right, v up).
    u = pts_x * np.cos(view) - pts_y * np.sin(view)
    v = pts_x * np.sin(view) + pts_y * np.cos(view)
    lo_u, hi_u = np.percentile(u, [EXTENT_PCT, 100.0 - EXTENT_PCT])
    lo_v, hi_v = np.percentile(v, [EXTENT_PCT, 100.0 - EXTENT_PCT])
    body = (u >= lo_u) & (u <= hi_u) & (v >= lo_v) & (v <= hi_v)
    pts_x, pts_y, pts_t = pts_x[body], pts_y[body], pts_t[body]

    tilt = travel(span(t, OPENING_S - 1.2, OPENING_S + 2.4))
    orbit = ease_in_out_sine(span(t, OPENING_S - 1.2, t_end))
    # Less tilt in portrait: a frame limited by its width has height to spare.
    pitch = (TILT_PITCH_PORTRAIT if portrait else TILT_PITCH) * tilt
    # The orbit swings across the axis, centred on it.
    bearing = (axis_deg * tilt + ORBIT_DEG * (0.5 - orbit) * tilt) % 360.0

    # The frame holds what will be drawn a moment from now, grows side by side
    # (never shrinks), and stays within the whole territory's box; home, at
    # the origin, is where it starts.
    keys = np.arange(0, frames, max(1, fps // 6))
    zoom_keys = np.zeros(len(keys))
    mids = np.zeros((len(keys), 2))
    half = 0.5 * MIN_SPAN_M
    for j, i in enumerate(keys):
        shown = pts_t <= t[i] + FRAME_AHEAD_S
        sx, sy = pts_x[shown], pts_y[shown]
        stride = max(1, len(sx) // FRAME_POINTS)
        # Home, and a minimum span around what is shown, so a few short rides are not framed at street level.
        mx = 0.5 * (min(sx.min(initial=0.0), 0.0) + max(sx.max(initial=0.0), 0.0))
        my = 0.5 * (min(sy.min(initial=0.0), 0.0) + max(sy.max(initial=0.0), 0.0))
        fx = np.concatenate([sx[::stride], [0.0, mx - half, mx + half, mx + half, mx - half]])
        fy = np.concatenate([sy[::stride], [0.0, my - half, my - half, my + half, my + half]])
        mid_x, mid_y, _, zoom_keys[j] = fit_view(
            fx, fy, np.zeros(len(fx)), float(pitch[i]), float(bearing[i]), home_lat, width, height,
            (0.05, 0.21, 0.95, 0.93), zoom_range=(5.0, 15.5),
        )
        mids[j] = (mid_x, mid_y)
    index = np.arange(frames)
    # Only ever backing away, as one calm move; the guard keeps the smoothing
    # from closing in on a road about to be drawn.
    zoom = np.minimum.accumulate(np.interp(index, keys, zoom_keys))
    zoom = gaussian_smooth(np.minimum(zoom, gaussian_smooth(zoom, 0.6 * fps)), 0.6 * fps)
    cx = gaussian_smooth(np.interp(index, keys, mids[:, 0]), 0.6 * fps)
    cy = gaussian_smooth(np.interp(index, keys, mids[:, 1]), 0.6 * fps)

    cam = CameraTrack(frames)
    cam.lon, cam.lat = from_local_xy(cx, cy, origin)
    cam.zoom = zoom
    cam.pitch = gaussian_smooth(pitch, max(2.0, 0.3 * fps))
    cam.bearing = bearing
    cam.contours = 0.55 * tilt
    cam.shade = 1.0 + 0.4 * tilt
    cam.map_opacity = 1.0 - 0.25 * tilt
    opening_ch = envelope(t, 0.35, OPENING_S + 0.2, 0.45)
    if look == "satellite":
        cam.satellite = np.clip(1.0 - 0.7 * tilt, 0.0, 1.0)

    # The counter holds to the end: the totals join it in its row.
    counter_ch = ease_in_out_sine(span(t, t_build - 0.2, t_build + 0.3))
    stats_ch = ease_in_out_sine(span(t, t_built + 0.4, t_built + 1.4))
    channels = {
        "opening": opening_ch,
        "counter": counter_ch,
        "km": revealed / 1000.0,
        "stats": stats_ch,
        "fade": 1.0 - 0.3 * ease_in_out_sine(span(t, t_end - 1.1, t_end)),
        "black": fade_through_black(t, t_end, open_s=0.65),
    }

    # The period of the ride being drawn, shown small in the opposite corner.
    multi_year = regional[0].start_date.year != regional[-1].start_date.year
    story_rides = []
    for k, ride in enumerate(regional):
        dt = ride.start_date
        story_rides.append(
            {
                "trackIndex": k,
                "t0": round(float(t0[k]), 3),
                "dur": round(float(draw_s[k]), 3),
                "fresh": [
                    [round(max(0.0, a - JOIN_M), 1), round(min(regional[k].track.length_m, b + JOIN_M), 1)]
                    for a, b in fresh[k]
                ],
                "wear": wear[k],
                "period": i18n.month_name(dt.month, dt.year if multi_year else None),
            }
        )

    extra_sources: list[str] = []
    opening_text, home_sources = home_title(
        (home_lon, home_lat), title_override, i18n.text("scene3d.rides_count", count=n),
        cache_dir=places_cache_dir, offline=offline,
    )
    extra_sources.extend(home_sources)

    total_km = sum((r.distance_m if r.distance_m > 0 else r.track.length_m) for r in regional) / 1000.0
    story = {
        "home": [round(home_lon, 6), round(home_lat, 6)],
        "rides": story_rides,
        "wearCounts": wear_counts,
        "opening": {
            "label": i18n.text(
                "scene3d.strata.kicker", start=i18n.date(regional[0].start_date), end=i18n.date(regional[-1].start_date)
            ),
            "text": opening_text,
        },
        "counter": {"label": i18n.text("scene3d.territory.distinct"), "unit": "km"},
        "stats": [
            {"label": i18n.text("scene3d.territory.distinct"), "value": i18n.number(distinct_m / 1000.0), "unit": "km"},
            {"label": i18n.text("scene3d.distance"), "value": i18n.number(total_km), "unit": "km"},
            {"label": i18n.text("scene3d.rides"), "value": i18n.number(n)},
        ],
    }
    spec = SceneSpec(
        kind="territory",
        locale=i18n.locale,
        look=look,
        width=width,
        height=height,
        fps=fps,
        camera=cam,
        channels=channels,
        tracks=[r.track.encode(tolerance_m=4.5, max_vertices=3_500) for r in regional],
        story=story,
        credits_on_screen=credits_on_screen,
        extra_sources=tuple(extra_sources),
    )
    return TerritoryBuildResult(spec=spec, kept_rides=n, excluded_rides=excluded, distinct_km=distinct_m / 1000.0)
