"""Tests for the ascent scene: the roads bend up off the map, pulled at home to the height they climbed."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from ride_visuals.scene3d.ascent import build_ascent_spec
from ride_visuals.scene3d.stretch import SceneRide
from ride_visuals.scene3d.track import RideTrack, from_local_xy

HOME = (7.77, 49.44)


def _ride(day: dt.date, gain: float, east_m: float = 0.0, length_m: float = 20_000.0) -> SceneRide:
    s = np.linspace(0.0, length_m, 200)
    lon, lat = from_local_xy(east_m + 0.5 * s, 0.3 * s, HOME)
    track = RideTrack.from_arrays(lon, lat, np.zeros_like(s), s / 8.0)
    when = dt.datetime(day.year, day.month, day.day, 9, tzinfo=dt.UTC)
    return SceneRide(activity_id=day.toordinal(), start_date=when, track=track, distance_m=length_m, elevation_gain_m=gain)


def _archive() -> list[SceneRide]:
    days = [dt.date(2024, 3, 1), dt.date(2024, 9, 1), dt.date(2025, 2, 1), dt.date(2025, 8, 1)]
    return [_ride(day, gain) for day, gain in zip(days, (3_000.0, 4_000.0, 2_500.0, 1_000.0), strict=True)]


def test_the_line_rises_steadily_to_the_archives_total_climbing() -> None:
    spec = build_ascent_spec(_archive(), fps=10, offline=True)
    column = spec.channels["climbed"]
    assert column[0] == 0.0
    assert np.all(np.diff(column) >= -1e-6)
    assert column[-1] == pytest.approx(10_500.0)
    assert spec.story["stats"][0]["value"] == "+10,500"


def test_only_the_heights_it_passes_are_named_in_the_order_it_passes_them() -> None:
    spec = build_ascent_spec(_archive(), fps=10, offline=True)
    heights = spec.story["heights"]
    assert [h["at"] for h in heights] == [330.0, 828.0, 8_849.0]
    assert np.all(np.diff([h["t"] for h in heights]) > 0)
    column, t = spec.channels["climbed"], np.arange(spec.frames) / spec.fps
    for height in heights:
        assert np.interp(height["t"], t, column) == pytest.approx(height["at"], rel=0.02)


def test_each_ride_is_drawn_in_turn_and_a_ride_far_from_home_joins_the_bend() -> None:
    rides = [*_archive(), _ride(dt.date(2025, 9, 1), 900.0, east_m=900_000.0)]
    spec = build_ascent_spec(rides, fps=10, offline=True)
    story_rides = spec.story["rides"]
    assert np.all(np.diff([r["t0"] for r in story_rides]) >= 0)
    assert [r["away"] for r in story_rides] == [False] * 4 + [True]
    assert len(spec.tracks) == 5
    assert spec.channels["climbed"][-1] == pytest.approx(11_400.0)


def test_things_stand_clear_of_the_line_at_their_true_height() -> None:
    spec = build_ascent_spec(_archive(), fps=10, offline=True)
    for thing in spec.story["heights"]:
        if not thing["outline"]:
            continue
        x, z = np.concatenate([np.array(stroke) for stroke in thing["outline"]]).T
        assert z.max() == pytest.approx(thing["at"])
        assert x.min() > 0.0
        assert thing["t0"] < thing["t"]


def test_years_split_the_line_only_when_the_archive_spans_several() -> None:
    spec = build_ascent_spec(_archive(), fps=10, offline=True)
    assert [(y["label"], y["to"]) for y in spec.story["years"]] == [("2024", 7_000.0), ("2025", 10_500.0)]
    one_year = build_ascent_spec(_archive()[:2], fps=10, offline=True)
    assert one_year.story["years"] == []


def test_the_camera_only_backs_away_and_turns_to_look_across_at_the_line() -> None:
    spec = build_ascent_spec(_archive(), fps=10, offline=True)
    assert np.all(np.diff(spec.camera.zoom) <= 1e-9)
    assert spec.camera.pitch[-1] > spec.camera.pitch[0] + 20.0
    assert spec.camera.elevation[-1] > 1_000.0


def test_an_archive_without_climbing_is_refused() -> None:
    with pytest.raises(ValueError, match="no elevation gain"):
        build_ascent_spec([_ride(dt.date(2025, 1, 1), 0.0)], fps=10, offline=True)
