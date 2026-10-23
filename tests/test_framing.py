"""Tests for the generalised chase-camera framing and tag layout."""

from __future__ import annotations

import numpy as np

from ride_visuals.scene3d.climbs import Climb
from ride_visuals.scene3d.flyover import _tag_windows
from ride_visuals.scene3d.framing import (
    HEAD_Y,
    MAX_BEARING_RATE_DEG_S,
    adaptive_exaggeration,
    frame_points,
    occlusion,
    project_points,
    rate_limited_floor,
    solve_chase,
    window_bearing,
    zoom_to_fill,
)


def _serpentine(length_m: float = 30_000.0, step: float = 10.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A road heading north that zig-zags 120 m left and right every 400 m."""
    d = np.arange(0.0, length_m + step, step)
    y = d * 0.95
    x = 120.0 * np.sin(2.0 * np.pi * d / 800.0)
    return d, x, y


def test_window_bearing_ignores_zigzag() -> None:
    d, x, y = _serpentine()
    head = np.linspace(1_000.0, 25_000.0, 200)
    bearing = window_bearing(head, head + 1_500.0, head - 500.0, d, x, y)
    deviation = (bearing + 180.0) % 360.0 - 180.0
    assert np.abs(deviation).max() < 12.0


def test_solve_chase_is_smooth_and_composes_head_in_lower_third() -> None:
    fps = 30
    d, x, y = _serpentine()
    # A long curve to the east after the serpentine.
    theta = np.linspace(0.0, np.pi / 2, 400)
    cx, cy = x[-1] + 4_000.0 * (1 - np.cos(theta)), y[-1] + 4_000.0 * np.sin(theta)
    d2 = np.concatenate([d, d[-1] + np.cumsum(np.hypot(np.diff(cx, prepend=cx[0]), np.diff(cy, prepend=cy[0])))[1:]])
    x2 = np.concatenate([x, cx[1:]])
    y2 = np.concatenate([y, cy[1:]])
    grid = np.arange(0.0, d2[-1], 10.0)
    gx, gy = np.interp(grid, d2, x2), np.interp(grid, d2, y2)
    alt = 200.0 + 150.0 * np.sin(grid / 3_000.0)
    t = np.arange(0, 20 * fps) / fps
    head = np.interp(t, [0, 20], [0.0, grid[-1] * 0.98])

    cam = solve_chase(t, head, grid, alt, gx, gy, lat=49.4, width=1920, height=1080, fps=fps)
    for series in (cam.cx, cam.cy, cam.zoom, cam.pitch, cam.bearing):
        assert np.isfinite(series).all()
    rate = np.abs((np.diff(cam.bearing) + 180.0) % 360.0 - 180.0) * fps
    assert rate.max() <= MAX_BEARING_RATE_DEG_S * 1.15
    assert np.abs(np.diff(cam.zoom)).max() * fps < 1.5
    assert (cam.pitch >= 50.0).all() and (cam.pitch <= 66.0).all()

    # The head lands near its composition line on a flat ground plane.
    hx, hy = np.interp(head, grid, gx), np.interp(head, grid, gy)
    for i in range(fps * 2, len(t) - fps * 2, fps):
        _, sy, ok = project_points(
            cam.cx[i], cam.cy[i], 0.0, cam.zoom[i], cam.pitch[i], cam.bearing[i], 49.4, 1920, 1080,
            np.array([hx[i]]), np.array([hy[i]]), np.array([0.0]),
        )
        assert ok[0]
        assert abs(sy[0] / 1080.0 - HEAD_Y) < 0.12


def test_adaptive_exaggeration_reads_relief_at_fixed_fraction() -> None:
    view = 30_000.0
    flat = adaptive_exaggeration(view, 20.0)
    hills = adaptive_exaggeration(view, 350.0)
    alps = adaptive_exaggeration(view, 1_800.0)
    assert flat == 2.6
    assert alps == 1.25
    assert alps < hills < flat


def test_occlusion_sees_walls() -> None:
    def wall(x: np.ndarray, _y: np.ndarray) -> np.ndarray:
        return np.where(np.abs(x - 500.0) < 50.0, 800.0, 0.0)

    eye = (np.array([0.0]), np.array([0.0]), np.array([300.0]))
    blocked = occlusion(*eye, np.array([[1_000.0]]), np.array([[0.0]]), np.array([[0.0]]), wall)
    clear = occlusion(*eye, np.array([[1_000.0]]), np.array([[0.0]]), np.array([[0.0]]), lambda x, y: np.zeros_like(x))
    assert blocked[0] == 1.0
    assert clear[0] == 0.0
    # Above the ceiling nothing is sampled, so a far-away wall is ignored.
    skipped = occlusion(*eye, np.array([[1_000.0]]), np.array([[0.0]]), np.array([[0.0]]), wall, ceiling=-1.0)
    assert skipped[0] == 0.0


def test_tag_windows_never_overlap() -> None:
    def climb(start: float, end: float, gain: float) -> Climb:
        return Climb(start_m=start, end_m=end, start_alt=100.0, end_alt=100.0 + gain)

    climbs = [climb(1_000.0, 3_000.0, 150.0), climb(3_200.0, 4_000.0, 120.0), climb(9_000.0, 12_000.0, 300.0)]
    t = np.arange(0, 600) / 30.0
    head = np.interp(t, [0, 20], [0.0, 14_000.0])
    windows = _tag_windows(climbs, None, head, t, 0.0, 0.0)
    shown = sorted((s, e) for s, e, _ in windows if e > s)
    assert len(shown) >= 2
    for (_, e1), (s2, _) in zip(shown, shown[1:], strict=False):
        assert s2 >= e1


def test_rate_limited_floor_caps_both_directions_and_stays_below() -> None:
    raw = np.array([12.0, 12.0, 15.0, 15.0, 12.0, 12.0, 9.0, 12.0])
    out = rate_limited_floor(raw, 0.5)
    assert np.all(out <= raw + 1e-9)
    assert np.abs(np.diff(out)).max() <= 0.5 + 1e-9
    # A fall is anticipated: the floor starts dropping before the dip.
    assert out[5] < raw[5]


def test_zoom_to_fill_frames_the_projected_extent() -> None:
    # A 3 km climb seen from the side at pitch 64: it must span the box, not shrink.
    x = np.linspace(-1_500.0, 1_500.0, 40)
    y = np.zeros_like(x)
    z = np.linspace(0.0, 300.0, 40)
    box = (0.2, 0.25, 0.8, 0.72)
    zoom = zoom_to_fill(0.0, 0.0, 150.0, 64.0, 0.0, 49.4, 1920, 1080, x, y, z, box)
    sx, sy, ok = project_points(0.0, 0.0, 150.0, zoom, 64.0, 0.0, 49.4, 1920, 1080, x, y, z)
    assert ok.all()
    assert sx.min() >= 0.2 * 1920 - 1 and sx.max() <= 0.8 * 1920 + 1
    assert sy.min() >= 0.25 * 1080 - 1 and sy.max() <= 0.72 * 1080 + 1
    # Fills the box along its tighter axis.
    assert (sx.max() - sx.min()) / (0.6 * 1920) > 0.95 or (sy.max() - sy.min()) / (0.47 * 1080) > 0.95


def test_frame_points_centres_and_fills_a_growing_stack() -> None:
    fps = 30
    frames = 4 * fps
    corners_x = np.array([-10_000.0, 10_000.0, 10_000.0, -10_000.0])
    corners_y = np.array([-8_000.0, -8_000.0, 8_000.0, 8_000.0])
    top = np.linspace(0.0, 16_000.0, frames)
    heights = np.concatenate([np.zeros((frames, 4)), np.repeat(top[:, None], 4, axis=1)], axis=1)
    pitch = np.full(frames, 58.0)
    bearing = np.linspace(0.0, -30.0, frames)
    safe = (np.full(frames, 0.27), np.full(frames, 0.06), np.full(frames, 0.97), np.full(frames, 0.9))
    cx, cy, zoom = frame_points(
        np.zeros(frames), np.zeros(frames), 0.5 * top, np.full(frames, 9.0), pitch, bearing, 49.4, 1920, 1080,
        np.tile(corners_x, 2), np.tile(corners_y, 2), heights, safe, fps,
    )
    # The camera only ever backs off as the stack grows (no bobbing).
    assert np.all(np.diff(zoom[fps:-fps]) <= 1e-3)
    for i in range(fps, frames - fps, fps // 2):
        sx, sy, ok = project_points(
            cx[i], cy[i], 0.5 * top[i], zoom[i], pitch[i], bearing[i], 49.4, 1920, 1080,
            np.tile(corners_x, 2), np.tile(corners_y, 2), heights[i],
        )
        assert ok.all()
        assert sx.min() >= 0.27 * 1920 - 2 and sx.max() <= 0.97 * 1920 + 2
        assert sy.min() >= 0.06 * 1080 - 2 and sy.max() <= 0.9 * 1080 + 2
        fill_x = (sx.max() - sx.min()) / (0.70 * 1920)
        fill_y = (sy.max() - sy.min()) / (0.84 * 1080)
        assert max(fill_x, fill_y) > 0.8


def test_occlusion_ignores_the_slope_a_road_lies_on_but_not_a_ridge() -> None:
    # A road cut into a 30% hillside seen from below and in front: the slope
    # right behind the road must not hide it; a ridge between does.
    eye = (np.array([0.0]), np.array([-3_000.0]), np.array([1_500.0]))
    road = (np.array([[0.0]]), np.array([[0.0]]), np.array([[4.0]]))

    def hillside(_x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return np.maximum(0.0, 0.3 * (y + 20.0))

    def ridge(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return hillside(x, y) + np.where(np.abs(y + 600.0) < 60.0, 1_400.0, 0.0)

    assert occlusion(*eye, *road, hillside)[0] == 0.0
    assert occlusion(*eye, *road, ridge)[0] == 1.0
