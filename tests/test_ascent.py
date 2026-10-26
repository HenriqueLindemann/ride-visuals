"""Tests for the ascent scene: every ride's climbing chained into one profile, then folded into a line."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from ride_visuals.i18n import _MESSAGES, SUPPORTED_LOCALES
from ride_visuals.scene3d.ascent import NAME_FADE_S, NAME_READ_S, build_ascent_spec
from ride_visuals.scene3d.framing import project_points
from ride_visuals.scene3d.landmarks import LANDMARKS
from ride_visuals.scene3d.places import home_cluster, resolve_home
from ride_visuals.scene3d.stretch import SceneRide
from ride_visuals.scene3d.track import RideTrack, from_local_xy, local_xy

HOME = (7.77, 49.44)


def _ride(day: dt.date, gain: float, east_m: float = 0.0, length_m: float = 20_000.0) -> SceneRide:
    s = np.linspace(0.0, length_m, 200)
    lon, lat = from_local_xy(east_m + 0.5 * s, 0.3 * s, HOME)
    track = RideTrack.from_arrays(lon, lat, 200.0 + gain * s / length_m, s / 8.0)
    when = dt.datetime(day.year, day.month, day.day, 9, tzinfo=dt.UTC)
    return SceneRide(activity_id=day.toordinal(), start_date=when, track=track, distance_m=length_m, elevation_gain_m=gain)


def _archive() -> list[SceneRide]:
    days = [dt.date(2024, 3, 1), dt.date(2024, 9, 1), dt.date(2025, 2, 1), dt.date(2025, 8, 1)]
    return [_ride(day, gain) for day, gain in zip(days, (3_000.0, 4_000.0, 6_500.0, 6_000.0), strict=True)]


def _t(spec) -> np.ndarray:
    return np.arange(spec.frames) / spec.fps


def test_the_profile_rises_steadily_to_the_archives_total_climbing() -> None:
    spec = build_ascent_spec(_archive(), fps=10, offline=True)
    climbed = spec.channels["climbed"]
    assert climbed[0] == 0.0
    assert np.all(np.diff(climbed) >= -1e-6)
    assert climbed[-1] == pytest.approx(19_500.0)
    assert np.cumsum(spec.story["profile"]["z"])[-1] / 10 == pytest.approx(19_500.0, abs=0.5)
    assert spec.story["stats"][0]["value"] == "+19,500"


def test_years_divide_the_profile_and_months_do_within_one_year() -> None:
    years = build_ascent_spec(_archive(), fps=10, offline=True).story
    assert [(p["label"], p["value"]) for p in years["periods"]] == [("2024", "+7,000 m"), ("2025", "+12,500 m")]
    assert years["groups"] == []
    months = build_ascent_spec(_archive()[2:], fps=10, offline=True).story
    assert [p["label"] for p in months["periods"]] == ["FEB", "AUG"]


def test_months_over_several_years_are_grouped_in_their_years() -> None:
    story = build_ascent_spec(_archive(), period="month", fps=10, offline=True).story
    assert [p["label"] for p in story["periods"]] == ["MAR", "SEP", "FEB", "AUG"]
    assert [g["label"] for g in story["groups"]] == ["2024", "2025"]
    assert story["groups"][1]["x"] == [story["periods"][2]["x"][0], story["periods"][3]["x"][1]]
    one = build_ascent_spec(_archive()[2:], period="year", fps=10, offline=True).story
    assert one["periods"] == []


def test_heights_are_passed_in_order_and_named_one_at_a_time() -> None:
    spec = build_ascent_spec(_archive(), fps=10, offline=True)
    heights = spec.story["heights"]
    assert [h["key"] for h in heights] == ["eiffel", "burj", "fuji", "everest", "airliner", "concorde"]
    climbed, t = spec.channels["climbed"], _t(spec)
    for height in heights:
        assert np.interp(height["t"], t, climbed) == pytest.approx(height["at"], rel=0.02)
        assert height["t0"] <= height["t"]
    assert np.all(np.diff([h["named"] for h in heights]) >= 2 * NAME_FADE_S + NAME_READ_S - 1e-3)


def test_things_stand_left_of_home_at_true_height() -> None:
    spec = build_ascent_spec(_archive(), fps=10, offline=True)
    for thing in spec.story["heights"]:
        x, z = np.concatenate([np.array(stroke) for stroke in thing["strokes"]]).T
        assert z.max() == pytest.approx(thing["at"])
        if thing["shape"] != "level":
            assert x.max() < 0.0


def test_folded_the_line_is_ruled_in_everests_only() -> None:
    spec = build_ascent_spec(_archive(), fps=10, offline=True)
    assert spec.story["ruler"] == {"at": 8_849.0, "count": 2}
    assert [s["label"] for s in spec.story["stats"]] == ["Elevation gain", "Everest", "Rides"]
    assert spec.channels["fold"][0] == 0.0
    assert spec.channels["fold"][-1] == pytest.approx(1.0)
    short = build_ascent_spec(_archive()[:1], fps=10, offline=True)
    assert short.story["ruler"] is None
    assert len(short.story["stats"]) == 2


def test_only_what_the_line_reaches_is_shown() -> None:
    short = build_ascent_spec(_archive()[:1], fps=10, offline=True).story
    assert [h["key"] for h in short["heights"]] == ["eiffel", "burj"]
    days = [dt.date(2024, m, 1) for m in (3, 5, 7, 9)]
    high = build_ascent_spec([_ride(day, 9_000.0) for day in days], fps=10, offline=True).story
    assert high["heights"][-1]["key"] == "concorde"


def test_every_landmark_is_named_in_every_locale_and_levels_carry_their_glyphs() -> None:
    for locale in SUPPORTED_LOCALES:
        assert all(f"scene3d.height.{mark.key}" in _MESSAGES[locale] for mark in LANDMARKS)
    assert [m.key for m in LANDMARKS] == [m.key for m in sorted(LANDMARKS, key=lambda m: m.height_m)]
    heights = build_ascent_spec(_archive(), fps=10, offline=True).story["heights"]
    glyphs = {h["key"]: h["glyph"] for h in heights}
    assert glyphs["eiffel"] is None
    assert min(x for x, _ in glyphs["concorde"][0]) == 0.0


def test_glyphs_are_seen_from_above_at_their_real_length() -> None:
    lengths = {mark.key: max(x for stroke in mark.glyph for x, _ in stroke) for mark in LANDMARKS if mark.glyph}
    assert lengths == {"airliner": 37.6, "concorde": 61.7}
    for mark in LANDMARKS:
        for stroke in mark.glyph:
            assert sorted(z for _, z in stroke) == sorted(-z for _, z in stroke)



def test_the_camera_backs_away_with_home_held_still_on_screen() -> None:
    spec = build_ascent_spec(_archive(), fps=10, offline=True)
    cam, t = spec.camera, _t(spec)
    live = spec.channels["live"] > 0.999
    climbing = live & (t > t[live][0] + 1.5)
    assert np.all(np.diff(cam.zoom[climbing]) <= 1e-9)
    assert cam.pitch[-1] > cam.pitch[0] + 20.0
    cx, cy = local_xy(cam.lon, cam.lat, HOME)
    zero = np.zeros(1)
    seen = np.array([
        project_points(cx[i], cy[i], cam.elevation[i], cam.zoom[i], cam.pitch[i], cam.bearing[i], HOME[1], 1920, 1080, zero, zero, zero)[:2]
        for i in np.flatnonzero(climbing)
    ])[:, :, 0]
    assert np.ptp(seen[:, 1]) < 2.0
    assert np.all(np.abs(np.diff(seen[:, 0])) * spec.fps < 60.0)


def test_home_is_where_most_of_the_climbing_starts_unless_given() -> None:
    flat = [_ride(dt.date(2024, 5, d), 20.0, east_m=40_000.0) for d in range(1, 8)]
    hilly = [_ride(dt.date(2024, 6, 1), 2_000.0), _ride(dt.date(2024, 6, 2), 2_000.0)]
    spec = build_ascent_spec(flat + hilly, fps=10, offline=True)
    assert spec.story["home"] == pytest.approx(list(HOME), abs=1e-3)
    there = from_local_xy(np.array([40_000.0]), np.array([0.0]), HOME)
    given = build_ascent_spec(flat + hilly, home=(float(there[0][0]), float(there[1][0])), fps=10, offline=True)
    assert given.story["home"][0] == pytest.approx(float(there[0][0]), abs=1e-4)


def test_home_cluster_weights_and_resolve_home_coordinates() -> None:
    starts = [(7.77, 49.44), (7.771, 49.44), (8.5, 49.9)]
    assert home_cluster(starts)[0] == pytest.approx(7.7705, abs=1e-3)
    assert home_cluster(starts, [1.0, 1.0, 50.0])[0] == pytest.approx(8.5)
    assert resolve_home("49.9, 8.5", starts, offline=True) == (8.5, 49.9)
    with pytest.raises(ValueError, match="--home"):
        resolve_home("95, 8.5", starts, offline=True)


def test_rides_without_climbing_are_refused() -> None:
    with pytest.raises(ValueError, match="no elevation gain"):
        build_ascent_spec([_ride(dt.date(2024, 3, 1), 0.0)], fps=10, offline=True)


def test_every_month_gets_screen_time_even_when_climbing_is_tiny() -> None:
    gains = [4_600.0, 300.0, 5_400.0, 28.0, 6.0, 4_200.0, 6_600.0, 7_100.0, 2_400.0]
    lengths = [20_000.0, 8_000.0, 25_000.0, 5_000.0, 3_000.0, 22_000.0, 28_000.0, 30_000.0, 15_000.0]
    rides = [
        _ride(dt.date(2026, m + 1, 10), gain, length_m=length)
        for m, (gain, length) in enumerate(zip(gains, lengths, strict=True))
    ]
    spec = build_ascent_spec(rides, fps=30, offline=True)
    periods = spec.story["periods"]
    assert len(periods) == 9
    times = [p["t"] for p in periods]
    # Even the +6 m month gets a distinct, multi-frame slice of the build.
    assert np.all(np.diff(times) >= 0.15)
