"""Director for ``video ascent``: the roads bend up off the map, pulled at home to the height they climbed."""

from __future__ import annotations

from collections.abc import Sequence
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
)
from ride_visuals.scene3d.framing import fit_view, principal_bearing
from ride_visuals.scene3d.places import DEFAULT_PLACES_CACHE_DIR, home_region, home_title
from ride_visuals.scene3d.spec import Look, SceneSpec
from ride_visuals.scene3d.stretch import SceneRide
from ride_visuals.scene3d.track import RideTrack, from_local_xy, gaussian_smooth, local_xy

#: Known heights anyone recognises: translation key and metres. Things stand beside the line at true scale;
#: the rest are levels round it.
HEIGHTS: tuple[tuple[str, float], ...] = (
    ("eiffel", 330.0),
    ("burj", 828.0),
    ("everest", 8_849.0),
    ("space", 100_000.0),
    ("iss", 408_000.0),
)
#: A thing starts drawing when the line reaches this share of its height.
HEIGHT_AHEAD = 0.45
Outline = tuple[tuple[float, float], ...]


def _mirrored(half: Outline) -> Outline:
    """A symmetric outline from its left half (base to top)."""
    return half + tuple((-x, z) for x, z in reversed(half[:-1]))


#: Side views of the things, as strokes of (x, z) metres: the Eiffel Tower (piers, platforms, arch, mast),
#: the Burj Khalifa's setbacks and spire, and Everest's skyline from the west with Lhotse (DEM, z12).
OUTLINES: dict[str, tuple[Outline, ...]] = {
    "eiffel": (
        _mirrored((
            (-62.5, 0.0), (-51.0, 26.0), (-42.0, 51.0), (-44.5, 57.6), (-44.5, 64.0), (-37.5, 64.0),
            (-29.0, 92.0), (-22.0, 115.7), (-24.0, 115.7), (-24.0, 122.0), (-19.0, 122.0), (-13.0, 165.0),
            (-9.0, 205.0), (-6.5, 245.0), (-5.0, 276.0), (-8.5, 276.0), (-8.5, 283.0), (-4.0, 283.0),
            (-3.0, 300.0), (-1.0, 300.0), (-1.0, 324.0), (0.0, 330.0),
        )),
        ((-36.5, 0.0), (-31.0, 8.0), (-28.7, 19.5), (-22.0, 29.0), (-11.9, 35.4), (0.0, 38.0),
         (11.9, 35.4), (22.0, 29.0), (28.7, 19.5), (31.0, 8.0), (36.5, 0.0)),
    ),
    "burj": (
        (
            (-50.0, 0.0), (-50.0, 140.0), (-45.0, 140.0), (-45.0, 210.0), (-40.0, 210.0), (-40.0, 280.0),
            (-35.0, 280.0), (-35.0, 350.0), (-30.0, 350.0), (-30.0, 420.0), (-24.0, 420.0), (-24.0, 490.0),
            (-18.0, 490.0), (-18.0, 555.0), (-12.0, 555.0), (-12.0, 600.0), (-7.0, 600.0), (-4.0, 700.0),
            (-2.0, 780.0), (0.0, 828.0), (2.0, 780.0), (4.0, 700.0), (6.0, 620.0), (9.0, 620.0), (9.0, 585.0),
            (14.0, 585.0), (14.0, 525.0), (20.0, 525.0), (20.0, 455.0), (26.0, 455.0), (26.0, 385.0),
            (31.0, 385.0), (31.0, 315.0), (36.0, 315.0), (36.0, 245.0), (41.0, 245.0), (41.0, 175.0),
            (46.0, 175.0), (46.0, 105.0), (50.0, 105.0), (50.0, 0.0),
        ),
    ),
    "everest": (
        (
            (-3100, 7093), (-2550, 7402), (-1950, 7909), (-1800, 7932), (-1500, 8253), (-1200, 8441),
            (-400, 8654), (-100, 8849), (450, 8627), (650, 8418), (1100, 8071), (1500, 7957), (1900, 8042),
            (2150, 8028), (2500, 8233), (2850, 8519), (2950, 8514), (3150, 8274), (3300, 8267), (3500, 8098),
            (3800, 7707), (4100, 7496), (5350, 6276),
        ),
    ),
}
#: A thing stands this share of its height clear of the line.
OUTLINE_GAP = 0.25
OPENING_S = 3.6
#: Zoom levels the camera backs away over the opening.
OPENING_PULL = 0.45
#: Seconds the line takes to rise, before and after scaling with the number of rides.
BUILD_S = (18.0, 34.0)
#: Pacing: this share of the rise goes by log height (each tenfold about as long), the rest by metres.
LOG_SHARE = 0.7
LOG_FLOOR_M = 300.0
#: A ride is drawn while the counter takes its climbing, within these bounds (s).
RIDE_DRAW_S = (0.4, 2.4)
#: The bend: a road ``r`` metres from home is lifted ``exp(-r / width)`` of the height climbed so far. The
#: width grows with that height (a needle at first) up to this share of how far the roads reach.
TENT_SHARE = 0.12
TENT_PER_M = 0.4
TENT_MIN_M = 40.0
#: A ride away from home is drawn this far across at most, at home.
AWAY_REACH_M = 250.0
REACH_PCT = 85.0
#: From looking down on the roads to looking across at the line (steeper shows the map's far edge).
PITCH = (36.0, 70.0)
ORBIT_DEG = 36.0
#: The line and the roads fill this box (fractions x0, y0, x1, y1), clear of the counters on top.
FRAME_BOX = (0.2, 0.27, 0.8, 0.86)
#: The frame makes room for what is drawn this far ahead (s).
FRAME_AHEAD_S = 1.0
FRAME_POINTS = 300
#: The roads are framed on their body: these percentiles per axis, never smaller than MIN_SPAN_M, and only
#: within GROUND_SHARE of the line's height from home, less in a narrow frame (long rides may run off).
EXTENT_PCT = 2.5
MIN_SPAN_M = 1_500.0
GROUND_SHARE = 0.8


def _reach_times(heights: np.ndarray, total: float, t_build: float, build_s: float) -> np.ndarray:
    """When the line reaches ``heights`` (s): log pacing eased in and out over the build."""
    pace = LOG_SHARE * np.log1p(heights / LOG_FLOOR_M) / np.log1p(total / LOG_FLOOR_M) + (1.0 - LOG_SHARE) * heights / total
    # Inverse of ease_in_out_sine.
    return t_build + build_s * np.arccos(1.0 - 2.0 * np.clip(pace, 0.0, 1.0)) / np.pi


def build_ascent_spec(  # noqa: PLR0913, PLR0915
    rides: Sequence[SceneRide],
    *,
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
    """Build the frame-by-frame spec for ``video ascent``."""
    ordered = sorted((r for r in rides if len(r.track.lon) >= 2), key=lambda r: r.start_date)
    gains = np.array([max(0.0, r.elevation_gain_m) for r in ordered])
    total = float(gains.sum())
    if total < 1.0:
        raise ValueError("The selected rides have no elevation gain to stack")
    i18n = Translator(locale)
    n = len(ordered)
    (home_lon, home_lat), near = home_region([(float(r.track.lon[0]), float(r.track.lat[0])) for r in ordered])
    origin = (home_lon, home_lat)

    # Timeline: the line rises by log height, so Everest and the edge of
    # space each get their moment; each ride climbs into place while the
    # counter takes its climbing.
    build_s = float(np.clip(BUILD_S[0] + 0.03 * n, *BUILD_S))
    t_build = OPENING_S + 0.2
    t_built = t_build + build_s
    t_end = t_built + 1.2 + reading_hold_s(2) + CURTAIN_S
    frames = max(60, int(round(t_end * fps)))
    t = np.arange(frames, dtype=float) / float(fps)
    cum = np.concatenate([[0.0], np.cumsum(gains)])
    reach = _reach_times(cum, total, t_build, build_s)
    grid = np.linspace(0.0, total, 4096)
    climbed = np.interp(t, _reach_times(grid, total, t_build, build_s), grid)
    climbed[t < t_build] = 0.0
    heights = []
    for key, metres in HEIGHTS:
        if metres > total:
            break
        when = _reach_times(np.array([HEIGHT_AHEAD * metres, metres]), total, t_build, build_s)
        strokes = [np.array(stroke, dtype=float) for stroke in OUTLINES.get(key, ())]
        shift = OUTLINE_GAP * metres - min((float(st[:, 0].min()) for st in strokes), default=0.0)
        heights.append({
            "at": metres,
            "outline": [[[round(float(x + shift), 1), round(float(z), 1)] for x, z in st] for st in strokes],
            "t0": round(float(when[0]), 3),
            "t": round(float(when[1]), 3),
            "name": i18n.text(f"scene3d.height.{key}"),
            "value": f"{i18n.number(metres)} m",
        })
    draw_s = np.clip(np.diff(reach), *RIDE_DRAW_S)

    # The roads: home rides where they were ridden, the others as a miniature
    # at home (they rise inside the bend, never posing as roads on this map).
    # The home roads as points every ~250 m with when each is drawn, for the frame.
    tracks: list[dict[str, list[int]]] = []
    pts: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for k, ride in enumerate(ordered):
        track = ride.track
        x, y = local_xy(track.lon, track.lat, origin)
        if not near[k]:
            k_away = AWAY_REACH_M / max(float(np.hypot(x - x[0], y - y[0]).max()), AWAY_REACH_M)
            x, y = k_away * (x - x[0]), k_away * (y - y[0])
            track = RideTrack(*from_local_xy(x, y, origin), track.alt, track.dist, track.elapsed)
        tracks.append(track.encode(tolerance_m=6.0, max_vertices=1_500))
        if not near[k] or track.length_m < 100.0:
            continue
        s = np.linspace(0.0, track.length_m, max(2, int(track.length_m / 250.0)))
        share = s / track.length_m
        pts.append((np.interp(s, track.dist, x), np.interp(s, track.dist, y), reach[k] + share * draw_s[k]))
    if pts:
        pts_x, pts_y, pts_t = (np.concatenate(v) for v in zip(*pts, strict=True))
        lo_x, hi_x = np.percentile(pts_x, [EXTENT_PCT, 100.0 - EXTENT_PCT])
        lo_y, hi_y = np.percentile(pts_y, [EXTENT_PCT, 100.0 - EXTENT_PCT])
        body = (pts_x >= lo_x) & (pts_x <= hi_x) & (pts_y >= lo_y) & (pts_y <= hi_y)
        pts_x, pts_y, pts_t = pts_x[body], pts_y[body], pts_t[body]
    else:
        pts_x = pts_y = pts_t = np.zeros(1)
    portrait = height > width

    def reach_at(top: float) -> float:
        """How far from home the frame keeps roads when the line is ``top`` metres tall."""
        return max(MIN_SPAN_M, GROUND_SHARE * top * min(1.0, width / height))

    # Camera: opens at street level over home and pulls back as one move,
    # looking down on the roads while they outsize the line, then across
    # at the line as it outgrows them.
    axis = principal_bearing(pts_x, pts_y) + (0.0 if portrait else 90.0) if len(pts_x) > 2 else 0.0
    axis = (axis + 90.0) % 180.0 - 90.0
    # A steady orbit from the first frame to the last: never still, never snapping.
    bearing = axis + ORBIT_DEG * (span(t, 0.0, t_end) - 0.5)
    keys = np.arange(0, frames, max(1, fps // 6))
    half = 0.5 * MIN_SPAN_M
    pitch_keys = np.zeros(len(keys))
    fit_keys = np.zeros((len(keys), 4))
    for j, i in enumerate(keys):
        ahead = t[i] + FRAME_AHEAD_S
        top = float(np.interp(ahead, t, climbed))
        shown = (pts_t <= ahead) & (np.hypot(pts_x, pts_y) <= reach_at(top))
        stride = max(1, int(shown.sum()) // FRAME_POINTS)
        sx, sy = pts_x[shown][::stride], pts_y[shown][::stride]
        ground = max(float(np.ptp(sx)) if len(sx) else 0.0, float(np.ptp(sy)) if len(sy) else 0.0, MIN_SPAN_M)
        rise = ease_in_out_sine(span(np.log10(max(top, 1.0) / ground), -1.3, 0.2))
        pitch_keys[j] = PITCH[0] + (PITCH[1] - PITCH[0]) * rise
        # The roads mirrored through home too: the line stays in the middle, its tags room on both sides.
        fx = np.concatenate([sx, -sx, [0.0, 0.0, -half, half, half, -half]])
        fy = np.concatenate([sy, -sy, [0.0, 0.0, -half, -half, half, half]])
        fz = np.concatenate([np.zeros(2 * len(sx)), [0.0, top, 0.0, 0.0, 0.0, 0.0]])
        # And the summits of the things standing beside it, as they draw (a wide ridge may run off).
        right = np.radians(bearing[i])
        for thing in heights:
            if thing["outline"] and thing["t0"] <= ahead:
                drawn = ease_in_out_sine(span(ahead, thing["t0"], thing["t"]))
                u, z = max((pt for stroke in thing["outline"] for pt in stroke), key=lambda pt: pt[1])
                u, z = drawn * u, drawn * z
                fx = np.concatenate([fx, [u * np.cos(right), -u * np.cos(right)]])
                fy = np.concatenate([fy, [-u * np.sin(right), u * np.sin(right)]])
                fz = np.concatenate([fz, [z, z]])
        fit_keys[j] = fit_view(fx, fy, fz, float(pitch_keys[j]), float(bearing[i]), home_lat, width, height, FRAME_BOX, lift=True)
    index = np.arange(frames)
    sigma = 0.6 * fps
    # Only ever tilting up, as one calm move.
    pitch = gaussian_smooth(np.maximum.accumulate(np.interp(index, keys, pitch_keys)), 2.0 * sigma)
    cx, cy, cz = (gaussian_smooth(np.interp(index, keys, fit_keys[:, c]), sigma) for c in range(3))
    # Only ever backing away, as one calm move.
    zoom = np.minimum.accumulate(np.interp(index, keys, fit_keys[:, 3]))
    zoom = gaussian_smooth(np.minimum(zoom, gaussian_smooth(zoom, sigma)), sigma)
    # Already backing away under the title, handing over to the framing without a seam.
    zoom = zoom + OPENING_PULL * (1.0 - span(t, 0.0, t_build + 3.0)) ** 2

    cam = CameraTrack(frames)
    cam.lon, cam.lat = from_local_xy(cx, cy, origin)
    cam.zoom = zoom
    cam.pitch = pitch
    cam.bearing = bearing % 360.0
    cam.elevation = cz
    across = span(pitch, PITCH[0], PITCH[1])
    cam.contours = 0.5 * (1.0 - across)
    cam.shade = 1.3 - 0.3 * across
    cam.map_opacity = 1.0 - 0.3 * across
    if look == "satellite":
        cam.satellite = 1.0 - across

    counter_ch = ease_in_out_sine(span(t, t_build - 0.3, t_build + 0.2))
    stats_ch = ease_in_out_sine(span(t, t_built + 0.4, t_built + 1.4))
    channels = {
        "opening": envelope(t, 0.35, OPENING_S + 0.2, 0.45),
        "counter": counter_ch,
        "climbed": climbed,
        "tent": np.clip(TENT_PER_M * climbed, TENT_MIN_M, max(TENT_MIN_M, TENT_SHARE * float(np.percentile(np.hypot(pts_x, pts_y), REACH_PCT)))),
        "ground": 1.0 - 0.5 * across,
        "stats": stats_ch,
        "fade": 1.0 - 0.3 * ease_in_out_sine(span(t, t_end - 1.1, t_end)),
        "black": fade_through_black(t, t_end, open_s=0.65),
    }

    multi_year = ordered[0].start_date.year != ordered[-1].start_date.year
    story_rides = [
        {
            "away": not bool(near[k]),
            "t0": round(float(reach[k]), 3),
            "dur": round(float(draw_s[k]), 3),
            "period": i18n.month_name(r.start_date.month, r.start_date.year if multi_year else None),
        }
        for k, r in enumerate(ordered)
    ]
    # Each year's stretch of the line, and when it is complete (multi-year only).
    years = []
    if multi_year:
        year_of = np.array([r.start_date.year for r in ordered])
        for year in sorted(set(year_of.tolist())):
            k = int(np.nonzero(year_of == year)[0][-1]) + 1
            if cum[k] > (years[-1]["to"] if years else 0.0):
                years.append({
                    "to": round(float(cum[k]), 1),
                    "t": round(float(reach[k]), 3),
                    "label": str(year),
                })
    opening_text, extra_sources = home_title(
        origin, title_override, i18n.text("scene3d.rides_count", count=n), cache_dir=places_cache_dir, offline=offline
    )
    story = {
        "home": [round(home_lon, 6), round(home_lat, 6)],
        "rides": story_rides,
        "years": years,
        "heights": heights,
        "opening": {
            "label": i18n.text(
                "scene3d.strata.kicker", start=i18n.date(ordered[0].start_date), end=i18n.date(ordered[-1].start_date)
            ),
            "text": opening_text,
        },
        "counter": {"label": i18n.text("scene3d.ascent"), "unit": "m"},
        "stats": [
            {"label": i18n.text("scene3d.ascent"), "value": f"+{i18n.number(total)}", "unit": "m"},
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
