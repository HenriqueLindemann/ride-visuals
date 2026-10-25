"""Tests for the territory scene, the closing highlight, and 3D stills."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from ride_visuals.commands.video_scene3d import parse_stills
from ride_visuals.i18n import Translator
from ride_visuals.scene3d.highlights import RideRecord, ride_highlight
from ride_visuals.scene3d.stretch import SceneRide
from ride_visuals.scene3d.territory import build_territory_spec, fresh_intervals, wear_steps
from ride_visuals.scene3d.track import RideTrack, from_local_xy


def _line(x0: float, y0: float, x1: float, y1: float, n: int = 200) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.linspace(x0, x1, n)
    y = np.linspace(y0, y1, n)
    d = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    return x, y, d


def _length(runs: list[tuple[float, float]]) -> float:
    return sum(b - a for a, b in runs)


def test_a_road_is_new_once_even_when_ridden_again_with_gps_drift() -> None:
    first = _line(0.0, 0.0, 5_000.0, 0.0)
    # The same road again, 15 m to the side (the other lane, a drifting GPS).
    again = _line(0.0, 15.0, 5_000.0, 15.0)
    runs = fresh_intervals([first, again])
    assert _length(runs[0]) == pytest.approx(5_000.0, abs=30.0)
    assert runs[1] == []


def test_an_out_and_back_counts_its_road_once() -> None:
    x = np.concatenate([np.linspace(0.0, 3_000.0, 150), np.linspace(3_000.0, 0.0, 150)])
    y = np.zeros_like(x)
    d = np.concatenate([[0.0], np.cumsum(np.abs(np.diff(x)))])
    runs = fresh_intervals([(x, y, d)])
    assert _length(runs[0]) == pytest.approx(3_000.0, abs=450.0)
    assert _length(runs[0]) < 3_500.0


def test_a_new_branch_off_a_known_road_is_the_only_new_part() -> None:
    known = _line(0.0, 0.0, 4_000.0, 0.0)
    branch_x = np.concatenate([np.linspace(0.0, 2_000.0, 100), np.full(100, 2_000.0)])
    branch_y = np.concatenate([np.zeros(100), np.linspace(0.0, 2_000.0, 100)])
    d = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(branch_x), np.diff(branch_y)))])
    runs = fresh_intervals([known, (branch_x, branch_y, d)])
    assert len(runs[1]) == 1
    a, b = runs[1][0]
    assert a == pytest.approx(2_000.0, abs=120.0)
    assert b - a == pytest.approx(2_000.0, abs=120.0)


def test_a_road_ridden_again_wears_brighter_and_a_road_ridden_once_does_not() -> None:
    commute = _line(0.0, 0.0, 3_000.0, 0.0)
    detour = _line(0.0, 0.0, 0.0, 3_000.0)
    rides = [commute, detour] + [_line(0.0, 10.0, 3_000.0, 10.0) for _ in range(7)]
    fresh = fresh_intervals(rides)
    t0 = np.arange(len(rides), dtype=float)
    steps, counts = wear_steps(rides, fresh, t0, np.full(len(rides), 0.5))
    assert counts[0] == 1 and counts[-1] == 8
    # Every piece of the commute reaches the top level, after the 8th ride starts.
    assert all(len(piece) == len(counts) - 1 for piece in steps[0][0])
    assert all(piece[-1] >= t0[-1] for piece in steps[0][0])
    assert all(piece == [] for piece in steps[1][0])
    assert steps[2] == []


def _ride(k: int, points: list[tuple[float, float]], day: int) -> SceneRide:
    origin = (7.77, 49.44)
    xs = np.concatenate([np.linspace(a[0], b[0], 120) for a, b in zip(points, points[1:], strict=False)])
    ys = np.concatenate([np.linspace(a[1], b[1], 120) for a, b in zip(points, points[1:], strict=False)])
    lon, lat = from_local_xy(xs, ys, origin)
    seconds = np.arange(len(lon), dtype=float) * 5.0
    track = RideTrack.from_arrays(lon, lat, np.full(len(lon), 250.0), seconds)
    return SceneRide(
        activity_id=k,
        start_date=dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=day),
        track=track,
        distance_m=track.length_m,
        elevation_gain_m=0.0,
        moving_time_s=float(seconds[-1]),
    )


def test_territory_counts_up_to_the_different_roads_and_frames_home_first() -> None:
    loop = [(0.0, 0.0), (6_000.0, 0.0), (6_000.0, 3_000.0), (0.0, 0.0)]
    rides = [_ride(k, loop, k) for k in range(6)] + [_ride(9, [(0.0, 0.0), (-8_000.0, 5_000.0)], 30)]
    result = build_territory_spec(rides, fps=10, offline=True)
    spec = result.spec
    km = spec.channels["km"]
    assert np.all(np.diff(km) >= -1e-9)
    assert km[-1] == pytest.approx(result.distinct_km, rel=1e-6)
    # Six laps of one loop and one new road: the loop is counted once.
    loop_km = (6_000.0 + 3_000.0 + np.hypot(6_000.0, 3_000.0)) / 1000.0
    assert result.distinct_km == pytest.approx(loop_km + np.hypot(8_000.0, 5_000.0) / 1000.0, rel=0.08)
    # The camera only backs away once the build starts, and opens over home.
    zoom = spec.camera.zoom
    assert np.all(np.diff(zoom) <= 1e-6)
    assert spec.camera.pitch[0] == pytest.approx(0.0)
    assert [ride["t0"] for ride in spec.story["rides"]] == sorted(ride["t0"] for ride in spec.story["rides"])


def test_highlight_names_the_strongest_true_fact_or_nothing() -> None:
    i18n = Translator("en")
    base = dt.datetime(2026, 1, 1)
    archive = [RideRecord(k, base + dt.timedelta(days=k), 40_000.0 + 1_000.0 * k, 300.0) for k in range(10)]
    record = RideRecord(99, base + dt.timedelta(days=50), 60_000.0, 1_200.0)
    best = ride_highlight(record, [*archive, record], i18n)
    assert best is not None and best.metrics == ("ascent", "distance")
    # A tie is not a record, and an ordinary ride says nothing.
    assert ride_highlight(archive[3], archive, i18n) is None
    # Too little history: no claim at all.
    assert ride_highlight(record, [*archive[:3], record], i18n) is None
    # The first ride past a round mark, though a later one climbed more.
    later = RideRecord(100, base + dt.timedelta(days=60), 140_000.0, 1_500.0)
    first = ride_highlight(record, [*archive, record, later], i18n)
    assert first is not None and first.text == "First ride over 1,000 m of climbing"


def test_parse_stills_reads_seconds_and_rejects_nonsense() -> None:
    assert parse_stills("4, 22.5,70") == [4.0, 22.5, 70.0]
    for bad in ("", "a,b", "-1"):
        with pytest.raises(ValueError):
            parse_stills(bad)
