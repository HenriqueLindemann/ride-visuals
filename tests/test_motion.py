"""Camera continuity of every director: no snaps, no stop-then-go, no dead stops."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from ride_visuals.scene3d.ascent import build_ascent_spec
from ride_visuals.scene3d.camera import meters_per_pixel
from ride_visuals.scene3d.flyover import MAX_BEARING_RATE_DEG_S, build_flyover_spec
from ride_visuals.scene3d.spec import SceneSpec
from ride_visuals.scene3d.strata import build_strata_spec
from ride_visuals.scene3d.stretch import SceneRide, build_stretch_spec
from ride_visuals.scene3d.territory import build_territory_spec
from ride_visuals.scene3d.track import RideTrack, from_local_xy, local_xy

HOME = (7.77, 49.44)
FPS = 30
#: A second difference may exceed its local (+-1 s) median by this factor at most...
SPIKE = 20.0
#: ...with a floor under that median (units per second squared: levels, degrees, screen px), so a calm
#: channel is not judged on rounding noise nobody can see.
FLOOR = {"zoom": 0.02, "pitch": 0.5, "bearing": 0.5, "elevation": 5.0, "centre_x": 5.0, "centre_y": 5.0}
#: The longest zoom or bearing may sit perfectly still once it has set off, while the scene is on screen (s).
MAX_STILL_S = 1.5


def _ride(day: dt.datetime, heading_deg: float = 90.0, length_km: float = 40.0, gain_m: float = 400.0) -> SceneRide:
    """A loop leaving home towards ``heading_deg``, circling to the left."""
    s = np.linspace(0.0, length_km * 1000.0, 600)
    a = 2.0 * np.pi * s / s[-1]
    r = s[-1] / (2.0 * np.pi)
    x, y = r * np.sin(a), r * (1.0 - np.cos(a))
    h = np.radians(90.0 - heading_deg)
    lon, lat = from_local_xy(x * np.cos(h) - y * np.sin(h), x * np.sin(h) + y * np.cos(h), HOME)
    alt = 180.0 + gain_m * np.exp(-(((s / s[-1]) - 0.45) / 0.12) ** 2)
    track = RideTrack.from_arrays(lon, lat, alt, s / 8.0)
    return SceneRide(int(day.timestamp()), day, track, track.length_m, gain_m, track.length_m / 8.0)


def _corridor(count: int, heading_deg: float = 5.0) -> list[SceneRide]:
    """Straight rides side by side: a long, thin territory, so the frame has to turn a long way."""
    rides = []
    for k in range(count):
        s = np.linspace(0.0, 25_000.0, 300)
        h = np.radians(heading_deg)
        side = 400.0 * (k - count / 2)
        lon, lat = from_local_xy(s * np.sin(h) + side * np.cos(h), s * np.cos(h) - side * np.sin(h), HOME)
        track = RideTrack.from_arrays(lon, lat, 200.0 + 0.01 * s, s / 8.0)
        day = dt.datetime(2026, 1 + k // 4, 1 + k % 4, 9, tzinfo=dt.UTC)
        rides.append(SceneRide(k + 1, day, track, track.length_m, 250.0, s[-1] / 8.0))
    return rides


def _archive(count: int, months: int = 8) -> list[SceneRide]:
    rides = []
    for k in range(count):
        day = dt.datetime(2026, 1 + k * months // count, 3 + k % 20, 9, tzinfo=dt.UTC)
        rides.append(_ride(day, heading_deg=40.0 * k, length_km=30.0 + 7.0 * (k % 5), gain_m=300.0 + 40.0 * k))
    return rides


def _flyover(heading: float) -> Callable[[Path], SceneSpec]:
    def build(tmp: Path) -> SceneSpec:
        track = _ride(dt.datetime(2026, 5, 1, tzinfo=dt.UTC), heading, 60.0, 420.0).track
        return build_flyover_spec(track, fps=FPS, places_cache_dir=tmp, offline=True)

    return build


def _strata(width: int, height: int) -> Callable[[Path], SceneSpec]:
    def build(tmp: Path) -> SceneSpec:
        return build_strata_spec(
            _archive(8), width=width, height=height, fps=FPS, places_cache_dir=tmp, offline=True, home=HOME
        ).spec

    return build


SCENES = {
    "flyover east": _flyover(90.0),
    "flyover south": _flyover(180.0),
    "flyover west": _flyover(270.0),
    "strata": _strata(1920, 1080),
    "strata portrait": _strata(1080, 1920),
    "stretch": lambda tmp: build_stretch_spec(_archive(10), fps=FPS, places_cache_dir=tmp, offline=True, home=HOME),
    "territory": lambda tmp: build_territory_spec(
        _archive(24), fps=FPS, places_cache_dir=tmp, offline=True, home=HOME
    ).spec,
    "territory corridor": lambda tmp: build_territory_spec(
        _corridor(12), fps=FPS, places_cache_dir=tmp, offline=True, home=HOME
    ).spec,
    "ascent": lambda tmp: build_ascent_spec(_archive(12), fps=FPS, places_cache_dir=tmp, offline=True, home=HOME),
}


def _channels(spec: SceneSpec) -> dict[str, tuple[np.ndarray, np.ndarray | float]]:
    """Camera series with the length of one unit of each (a screen pixel for those in metres)."""
    cam = spec.camera
    x, y = local_xy(cam.lon, cam.lat, HOME)
    mpp = meters_per_pixel(cam.zoom, cam.lat)
    return {
        "zoom": (cam.zoom, 1.0),
        "pitch": (cam.pitch, 1.0),
        "bearing": (np.degrees(np.unwrap(np.radians(cam.bearing))), 1.0),
        "elevation": (cam.elevation, mpp),
        "centre_x": (x, mpp),
        "centre_y": (y, mpp),
    }


def worst_spike(values: np.ndarray, unit: np.ndarray | float, fps: int, floor: float) -> tuple[float, float]:
    """The largest |second difference| against its local (+-1 s) median, as (ratio, time in s)."""
    accel = np.abs(np.diff(values, 2)) * fps**2 / (unit[1:-1] if np.ndim(unit) else unit)
    padded = np.pad(accel, fps, mode="edge")
    local = np.median(np.lib.stride_tricks.sliding_window_view(padded, 2 * fps + 1), axis=1)
    ratio = accel / np.maximum(local, floor)
    worst = int(np.argmax(ratio))
    return float(ratio[worst]), (worst + 1) / fps


def longest_rest(values: np.ndarray, visible: np.ndarray, fps: int) -> float:
    """Seconds the series sits still on screen, after it first moved."""
    moving = np.abs(np.diff(values, prepend=values[0])) > 1e-6
    started = np.cumsum(moving) > 0
    rest = ~moving & visible & started
    longest = run = 0
    for flag in rest.tolist():
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return longest / fps


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, SceneSpec]:
    tmp = tmp_path_factory.mktemp("motion")
    return {name: build(tmp) for name, build in SCENES.items()}


@pytest.mark.parametrize("name", SCENES)
def test_camera_never_snaps(name: str, built: dict[str, SceneSpec]) -> None:
    spec = built[name]
    snaps = []
    for channel, (values, unit) in _channels(spec).items():
        ratio, at = worst_spike(values, unit, spec.fps, FLOOR[channel])
        if ratio > SPIKE:
            snaps.append(f"{channel} jerks {ratio:.0f}x its local median at {at:.2f}s")
    assert not snaps, f"{name}: " + "; ".join(snaps)


@pytest.mark.parametrize("name", SCENES)
def test_camera_never_comes_to_rest_while_visible(name: str, built: dict[str, SceneSpec]) -> None:
    spec = built[name]
    visible = spec.channels["black"] < 0.5
    channels = _channels(spec)
    for channel in ("zoom", "bearing"):
        rest = longest_rest(channels[channel][0], visible, spec.fps)
        assert rest <= MAX_STILL_S, f"{name} {channel} rests for {rest:.1f}s"


@pytest.mark.parametrize("name", [n for n in SCENES if not n.startswith("flyover")])
def test_bearing_turns_under_the_shared_cap(name: str, built: dict[str, SceneSpec]) -> None:
    bearing = _channels(built[name])["bearing"][0]
    assert np.abs(np.diff(bearing)).max() * built[name].fps <= MAX_BEARING_RATE_DEG_S


@pytest.mark.parametrize(("name", "heading"), [("flyover east", 90.0), ("flyover south", 180.0), ("flyover west", 270.0)])
def test_flyover_opens_near_the_way_the_ride_heads(name: str, heading: float, built: dict[str, SceneSpec]) -> None:
    # Not north-up and then a spin round: a small swing off the chase bearing, eased into it.
    off = (built[name].camera.bearing[0] - heading + 180.0) % 360.0 - 180.0
    assert abs(off) < 45.0
