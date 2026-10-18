"""Camera maths and timeline easing shared by the scene directors (MapLibre conventions).

Positions are handled in local metres (x east, y north) around an origin and
converted to longitude/latitude only when the track is written. Zoom follows
MapLibre's 512 px tiles; pitch 0 looks straight down and bearing is the
compass direction the top of the frame faces.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ride_visuals.scene3d.track import gaussian_smooth

EARTH_CIRCUMFERENCE_M = 40_075_016.686
#: MapLibre's default vertical field of view.
FOV_DEG = 36.87


def meters_per_pixel(zoom: np.ndarray | float, lat: np.ndarray | float) -> np.ndarray | float:
    return EARTH_CIRCUMFERENCE_M * np.cos(np.radians(lat)) / (512.0 * 2.0**zoom)


def zoom_for_mpp(mpp: np.ndarray | float, lat: np.ndarray | float) -> np.ndarray | float:
    return np.log2(EARTH_CIRCUMFERENCE_M * np.cos(np.radians(lat)) / (512.0 * np.asarray(mpp)))


def fit_zoom(
    x: np.ndarray,
    y: np.ndarray,
    *,
    bearing: float,
    lat: float,
    width: float,
    height: float,
    fill: float = 0.8,
) -> tuple[float, float, float]:
    """Zoom and centre (local metres) that fit points in ``fill`` of a top-down frame."""
    b = math.radians(bearing)
    # Screen axes for a camera facing `bearing`: right = (cos b, -sin b), up = (sin b, cos b).
    sx = x * math.cos(b) - y * math.sin(b)
    sy = x * math.sin(b) + y * math.cos(b)
    span_x = max(float(sx.max() - sx.min()), 1.0)
    span_y = max(float(sy.max() - sy.min()), 1.0)
    mpp = max(span_x / (width * fill), span_y / (height * fill))
    cx_s = (sx.max() + sx.min()) / 2
    cy_s = (sy.max() + sy.min()) / 2
    cx = cx_s * math.cos(b) + cy_s * math.sin(b)
    cy = -cx_s * math.sin(b) + cy_s * math.cos(b)
    return float(zoom_for_mpp(mpp, lat)), float(cx), float(cy)


def smooth_angles(degrees: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian smoothing of a compass series without the 359 -> 0 jump."""
    unwrapped = np.degrees(np.unwrap(np.radians(degrees)))
    return gaussian_smooth(unwrapped, sigma)


def limit_rate(values: np.ndarray, max_step: np.ndarray | float) -> np.ndarray:
    """Clamp the per-frame change of a series (one limit, or one per frame)."""
    out = np.asarray(values, dtype=float).copy()
    limit = np.broadcast_to(np.asarray(max_step, dtype=float), out.shape)
    for i in range(1, len(out)):
        step = out[i] - out[i - 1]
        if abs(step) > limit[i]:
            out[i] = out[i - 1] + math.copysign(limit[i], step)
    return out


def eye_offset(zoom: np.ndarray, pitch: np.ndarray, bearing: np.ndarray, lat: np.ndarray, height_px: float):
    """Eye position relative to the look-at point: (dx east, dy north, dz up) in metres."""
    distance_px = 0.5 * height_px / math.tan(math.radians(FOV_DEG) / 2)
    distance_m = distance_px * meters_per_pixel(zoom, lat)
    p = np.radians(pitch)
    b = np.radians(bearing)
    horizontal = distance_m * np.sin(p)
    return -horizontal * np.sin(b), -horizontal * np.cos(b), distance_m * np.cos(p)


def bearing_deg(dx: np.ndarray | float, dy: np.ndarray | float) -> np.ndarray | float:
    """Compass bearing of a local-metre vector."""
    return np.degrees(np.arctan2(dx, dy)) % 360.0


def travel(t: np.ndarray | float) -> np.ndarray | float:
    """Symmetric ease (cubic-bezier 0.65, 0, 0.35, 1 approximated by smootherstep)."""
    t = np.clip(t, 0.0, 1.0)
    return t * t * t * (t * (t * 6 - 15) + 10)


def ease_in_out_sine(t: np.ndarray | float) -> np.ndarray | float:
    t = np.clip(t, 0.0, 1.0)
    return -(np.cos(np.pi * t) - 1) / 2


def glide(t: np.ndarray | float, power: float = 3.2) -> np.ndarray | float:
    """Decisive start, long soft landing: for things arriving on screen."""
    u = np.clip(t, 0.0, 1.0)
    return 1.0 - (1.0 - u) ** power


def span(t: np.ndarray, start: float, end: float) -> np.ndarray:
    """Linear progress of ``t`` from ``start`` to ``end``, clamped to 0..1."""
    return np.clip((t - start) / max(end - start, 1e-9), 0.0, 1.0)


def envelope(t: np.ndarray, start: float, end: float, fade: float) -> np.ndarray:
    """Opacity that fades in over ``fade`` after ``start`` and out over ``fade`` before ``end``."""
    enter = ease_in_out_sine(span(t, start, start + fade))
    leave = 1.0 - ease_in_out_sine(span(t, end - fade, end))
    return np.clip(enter * leave, 0.0, 1.0)


def fade_through_black(t: np.ndarray, end: float, *, open_s: float, power: float = 3.2) -> np.ndarray:
    """Black curtain: lifts over ``open_s`` at the start, falls in the last 0.85 s."""
    return np.maximum(1.0 - glide(span(t, 0.0, open_s), power), ease_in_out_sine(span(t, end - 0.85, end)))


def lerp_angle(a: np.ndarray | float, b: np.ndarray | float, t: np.ndarray | float):
    d = (np.asarray(b) - np.asarray(a) + 540.0) % 360.0 - 180.0
    return np.asarray(a) + d * t


@dataclass
class CameraTrack:
    """One value per frame for everything the map stage applies."""

    frames: int
    lon: np.ndarray = field(init=False)
    lat: np.ndarray = field(init=False)
    zoom: np.ndarray = field(init=False)
    pitch: np.ndarray = field(init=False)
    bearing: np.ndarray = field(init=False)
    elevation: np.ndarray = field(init=False)
    terrain: np.ndarray = field(init=False)
    globe: np.ndarray = field(init=False)
    map_opacity: np.ndarray = field(init=False)
    contours: np.ndarray = field(init=False)
    satellite: np.ndarray = field(init=False)
    #: Hillshade contrast multiplier (1 = the flat-map default).
    shade: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        for name in ("lon", "lat", "zoom", "pitch", "bearing", "elevation", "terrain", "globe", "contours", "satellite"):
            setattr(self, name, np.zeros(self.frames))
        self.map_opacity = np.ones(self.frames)
        self.shade = np.ones(self.frames)
