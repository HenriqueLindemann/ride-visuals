"""Chase-camera framing that generalises to any ride.

The director knows the whole future, so the camera is solved offline:

* **Look-ahead in time, not metres.** Each frame frames the stretch the head
  will cover over the next few seconds (plus a little behind it), so a slow
  hairpin climb and a fast valley road get the same amount of "story" on screen.
* **Bearing from the principal axis** of that window (PCA), oriented with the
  direction of travel. Zig-zags and switchbacks average out instead of
  shaking the camera; near-isotropic windows (tight loops) fall back to the chord.
* **Zoom fits the window inside a safe frame** (clear of the corner text),
  never faster than a background speed limit, smoothed in log space.
* **Composition:** the head sits in the lower third with lead room ahead.
* **Rate limits:** bearing is smoothed non-causally and its angular speed capped;
  zoom is the rate-limited lower envelope of the fit (it pulls back early and
  never dives in faster than it can come back out).
* **Pitch follows the local relief:** flat land is looked at more from above,
  where an oblique view would be empty; hills get a lower, more dramatic angle.
* **Visibility:** when a ridge would hide the head or the road ahead, the
  bearing swings to the side with a clear line of sight.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ride_visuals.scene3d.camera import (
    FOV_DEG,
    eye_offset,
    limit_rate,
    meters_per_pixel,
    smooth_angles,
    zoom_for_mpp,
)
from ride_visuals.scene3d.track import gaussian_smooth

#: Screen composition (fractions of the frame height, from the top).
HEAD_Y = 0.66
TOP_SAFE_Y = 0.20
BOTTOM_SAFE_Y = 0.80
#: Half-width of the safe frame (fraction of the frame width).
SIDE_SAFE_X = 0.38
LOOK_AHEAD_S = 2.0
#: Never frame less road than this: a crawling head would otherwise dive the
#: camera in, and then pull it out again (an accordion). A short ride frames
#: a share of its own length instead, down to the floor.
MIN_WINDOW_M = 1100.0
MIN_WINDOW_SHARE = 0.3
MIN_WINDOW_FLOOR_M = 400.0
MAX_BACKGROUND_PX_S = 300.0
MAX_BEARING_RATE_DEG_S = 22.0
#: Zoom levels per second the chase may dolly in or out.
MAX_ZOOM_RATE = 0.45
VISIBILITY_OFFSETS_DEG = (0.0, -22.0, 22.0, -45.0, 45.0)

#: Ground height sampler: (lon, lat) arrays in, metres out (NaN when unknown).
GroundFn = Callable[[np.ndarray, np.ndarray], np.ndarray]
#: Local metres -> (lon, lat).
ToLonLat = Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]


@dataclass
class ChaseCamera:
    cx: np.ndarray
    cy: np.ndarray
    zoom: np.ndarray
    pitch: np.ndarray
    bearing: np.ndarray
    #: Route relief (m) inside each frame's look-ahead window.
    local_relief: np.ndarray


def _head_at(t: np.ndarray, head: np.ndarray, offset_s: float) -> np.ndarray:
    return np.interp(t + offset_s, t, head)


def window_bearing(
    head: np.ndarray,
    ahead: np.ndarray,
    behind: np.ndarray,
    prof_d: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    samples: int = 24,
) -> np.ndarray:
    """Travel-oriented principal axis of each frame's window (compass degrees)."""
    frac = np.linspace(0.0, 1.0, samples)
    d = behind[:, None] + (ahead - behind)[:, None] * frac[None, :]
    wx = np.interp(d, prof_d, grid_x)
    wy = np.interp(d, prof_d, grid_y)
    # Weight the road ahead more than the road behind.
    w = np.where(d >= head[:, None], 1.0, 0.45)
    w = w / w.sum(axis=1, keepdims=True)
    mx = (w * wx).sum(axis=1, keepdims=True)
    my = (w * wy).sum(axis=1, keepdims=True)
    ex = wx - mx
    ey = wy - my
    sxx = (w * ex * ex).sum(axis=1)
    syy = (w * ey * ey).sum(axis=1)
    sxy = (w * ex * ey).sum(axis=1)
    # Principal eigenvector of the 2x2 covariance.
    theta = 0.5 * np.arctan2(2.0 * sxy, sxx - syy)
    ux, uy = np.cos(theta), np.sin(theta)
    tr = sxx + syy
    det = sxx * syy - sxy * sxy
    disc = np.sqrt(np.maximum(tr * tr / 4.0 - det, 0.0))
    l1 = tr / 2.0 + disc
    l2 = np.maximum(tr / 2.0 - disc, 0.0)
    anisotropy = np.clip((l1 - l2) / np.maximum(l1, 1e-9), 0.0, 1.0)
    chord_x = wx[:, -1] - wx[:, 0]
    chord_y = wy[:, -1] - wy[:, 0]
    sign = np.where(ux * chord_x + uy * chord_y < 0.0, -1.0, 1.0)
    ux, uy = ux * sign, uy * sign
    chord_n = np.maximum(np.hypot(chord_x, chord_y), 1e-9)
    # Tight loops have no dominant axis: lean on the chord instead.
    k = np.clip((anisotropy - 0.35) / 0.4, 0.0, 1.0)
    vx = k * ux + (1.0 - k) * chord_x / chord_n
    vy = k * uy + (1.0 - k) * chord_y / chord_n
    return np.degrees(np.arctan2(vx, vy)) % 360.0


def fit_window_mpp(
    bearing: np.ndarray,
    pitch: np.ndarray,
    head: np.ndarray,
    ahead: np.ndarray,
    behind: np.ndarray,
    prof_d: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    width: int,
    height: int,
    samples: int = 24,
) -> np.ndarray:
    """Metres per pixel that keep each window inside the safe frame."""
    frac = np.linspace(0.0, 1.0, samples)
    d = behind[:, None] + (ahead - behind)[:, None] * frac[None, :]
    hx = np.interp(head, prof_d, grid_x)[:, None]
    hy = np.interp(head, prof_d, grid_y)[:, None]
    dx = np.interp(d, prof_d, grid_x) - hx
    dy = np.interp(d, prof_d, grid_y) - hy
    b = np.radians(bearing)[:, None]
    forward = dx * np.sin(b) + dy * np.cos(b)
    lateral = dx * np.cos(b) - dy * np.sin(b)
    foreshorten = np.maximum(np.cos(np.radians(pitch)), 0.35)
    need_fwd = np.maximum(forward.max(axis=1), 0.0) * foreshorten / ((HEAD_Y - TOP_SAFE_Y) * height)
    need_back = np.maximum(-forward.min(axis=1), 0.0) * foreshorten / ((BOTTOM_SAFE_Y - HEAD_Y) * height)
    need_side = np.abs(lateral).max(axis=1) / (SIDE_SAFE_X * width)
    return np.maximum.reduce([need_fwd, need_back, need_side])


def occlusion(
    eye_x: np.ndarray,
    eye_y: np.ndarray,
    eye_z: np.ndarray,
    tx: np.ndarray,
    ty: np.ndarray,
    tz: np.ndarray,
    ground: Callable[[np.ndarray, np.ndarray], np.ndarray],
    steps: int = 24,
    ceiling: float | None = None,
    near_m: float = 90.0,
) -> np.ndarray:
    """Fraction of targets whose line of sight dips under the ground.

    The same test the player applies (``inAir`` in projector.ts): samples
    crowd towards the target, where the ridges that matter usually are, and
    the last ``near_m`` of each ray are skipped so a road lying on a slope
    does not hide itself.
    """
    reach = np.hypot(tx - eye_x[:, None], ty - eye_y[:, None])
    s_max = 1.0 - np.minimum(0.9, near_m / np.maximum(reach, 1.0))
    s = np.sqrt(np.arange(1, steps + 1) / steps)[None, None, :] * s_max[:, :, None]
    px = eye_x[:, None, None] + (tx[:, :, None] - eye_x[:, None, None]) * s
    py = eye_y[:, None, None] + (ty[:, :, None] - eye_y[:, None, None]) * s
    pz = eye_z[:, None, None] + (tz[:, :, None] - eye_z[:, None, None]) * s
    # Only the low end of a ray can meet the land; MapLibre's eye is often tens
    # of km away and sampling (and downloading) DEM along all of it is waste.
    low = pz < ceiling if ceiling is not None else np.ones(pz.shape, dtype=bool)
    g = np.full(pz.shape, -1e9)
    if low.any():
        g[low] = np.nan_to_num(ground(px[low], py[low]), nan=-1e9)
    hidden = (g > pz + 2.0).any(axis=2)
    return hidden.mean(axis=1)


def visible_bearing_offset(
    bearing: np.ndarray,
    pitch: np.ndarray,
    zoom: np.ndarray,
    cx: np.ndarray,
    cy: np.ndarray,
    lat: float,
    height: int,
    targets_x: np.ndarray,
    targets_y: np.ndarray,
    targets_z: np.ndarray,
    exaggeration: float,
    ground_xy: Callable[[np.ndarray, np.ndarray], np.ndarray],
    centre_z: np.ndarray,
    ceiling_m: float | None = None,
) -> np.ndarray:
    """Per-frame bearing offset (deg) that best keeps the targets in sight."""
    n = len(bearing)
    best = np.zeros(n)
    best_cost = np.full(n, np.inf)
    for off in VISIBILITY_OFFSETS_DEG:
        b = (bearing + off) % 360.0
        dx, dy, dz = eye_offset(zoom, pitch, b, np.full(n, lat), float(height))
        occ = occlusion(
            cx + dx,
            cy + dy,
            centre_z + dz,
            targets_x,
            targets_y,
            targets_z * exaggeration,
            lambda x, y: ground_xy(x, y) * exaggeration,
            ceiling=None if ceiling_m is None else ceiling_m * exaggeration,
        )
        cost = occ + 0.004 * abs(off)
        better = cost < best_cost - 1e-6
        best[better] = off
        best_cost[better] = cost[better]
    return best


def solve_chase(
    t: np.ndarray,
    head: np.ndarray,
    prof_d: np.ndarray,
    prof_alt: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    *,
    lat: float,
    width: int,
    height: int,
    fps: int,
    zoom_range: tuple[float, float] = (10.5, 16.0),
) -> ChaseCamera:
    """Solve centre, zoom, pitch and bearing for a head moving along a route."""
    total = float(prof_d[-1])
    window = float(np.clip(MIN_WINDOW_SHARE * total, MIN_WINDOW_FLOOR_M, MIN_WINDOW_M))
    ahead = np.minimum(total, np.maximum(_head_at(t, head, LOOK_AHEAD_S), head + window))
    behind = np.maximum(0.0, head - 0.35 * (ahead - head))

    # Route relief in each window drives pitch (and, upstream, exaggeration).
    frac = np.linspace(0.0, 1.0, 16)
    d = behind[:, None] + (ahead - behind)[:, None] * frac[None, :]
    alt = np.interp(d, prof_d, prof_alt)
    local_relief = gaussian_smooth(alt.max(axis=1) - alt.min(axis=1), 0.8 * fps)
    pitch = 50.0 + 16.0 * np.clip(local_relief / 260.0, 0.0, 1.0)
    pitch = gaussian_smooth(pitch, 0.9 * fps)

    bearing = window_bearing(head, ahead, behind, prof_d, grid_x, grid_y)
    # Smoothed as one unwrapped series, so the rate limit never sees a 359 -> 0 jump.
    bearing = smooth_angles(bearing, sigma=max(2.0, 1.0 * fps))
    bearing = limit_rate(bearing, MAX_BEARING_RATE_DEG_S / fps)
    bearing = gaussian_smooth(bearing, max(1.5, 0.25 * fps)) % 360.0

    speed_mpp = np.abs(np.gradient(head, 1.0 / fps)) / MAX_BACKGROUND_PX_S
    relief_pitch = pitch
    for _ in range(2):
        fit_mpp = fit_window_mpp(bearing, pitch, head, ahead, behind, prof_d, grid_x, grid_y, width, height)
        mpp = np.maximum.reduce([fit_mpp, speed_mpp, np.full_like(head, 1.4)])
        zoom = np.clip(zoom_for_mpp(mpp, lat), *zoom_range)
        # Smooth in log space (= zoom levels); zooming out early beats zooming out late.
        zoom = np.minimum(zoom, gaussian_smooth(zoom, 0.6 * fps))
        zoom = gaussian_smooth(rate_limited_floor(zoom, MAX_ZOOM_RATE / fps), 0.6 * fps)
        # The farther out, the more from above: a wide oblique view is mostly empty horizon.
        pitch = gaussian_smooth(np.minimum(relief_pitch, pitch_for_zoom(zoom)), 0.6 * fps)

    # Composition: put the head at HEAD_Y, leaving lead room ahead.
    hx = gaussian_smooth(np.interp(head, prof_d, grid_x), 0.35 * fps)
    hy = gaussian_smooth(np.interp(head, prof_d, grid_y), 0.35 * fps)
    lead = lead_for_composition(zoom, pitch, lat, height, HEAD_Y)
    b = np.radians(bearing)
    cx = hx + np.sin(b) * lead
    cy = hy + np.cos(b) * lead
    return ChaseCamera(cx=cx, cy=cy, zoom=zoom, pitch=pitch, bearing=bearing, local_relief=local_relief)


def rate_limited_floor(values: np.ndarray, max_step: float) -> np.ndarray:
    """Largest series under ``values`` whose per-frame change never exceeds ``max_step``.

    A forward pass caps rises, a backward pass caps falls (so a fall starts
    early instead of arriving late): for zoom, the camera is never closer than
    the fit allows and never dollies faster than the limit.
    """
    out = np.asarray(values, dtype=float).copy()
    for i in range(1, len(out)):
        out[i] = min(out[i], out[i - 1] + max_step)
    for i in range(len(out) - 2, -1, -1):
        out[i] = min(out[i], out[i + 1] + max_step)
    return out


def pitch_for_zoom(zoom: np.ndarray) -> np.ndarray:
    """Pitch ceiling (deg): ~42 at z11 (wide transit), ~66 at z13 and closer."""
    return np.clip(42.0 + 12.0 * (np.asarray(zoom) - 11.0), 36.0, 68.0)


def lead_for_composition(
    zoom: np.ndarray, pitch: np.ndarray, lat: float, height: int, head_y: float
) -> np.ndarray:
    """Ground distance (m) behind the look-at point that lands on screen row ``head_y``.

    Exact for a flat plane under MapLibre's pinhole camera: the eye sits ``D``
    from the centre (D = focal length in px times m/px); the head row is
    ``atan(dy / focal)`` further below the centre ray.
    """
    focal = 0.5 * height / np.tan(np.radians(FOV_DEG) / 2.0)
    dist = focal * meters_per_pixel(zoom, lat)
    p = np.radians(pitch)
    depression = (np.pi / 2.0 - p) + np.arctan((head_y - 0.5) * height / focal)
    return dist * np.sin(p) - dist * np.cos(p) / np.tan(depression)


def adaptive_exaggeration(view_width_m: float, route_relief_m: float) -> float:
    """Exaggeration that makes the visible relief read at a fixed fraction of the view.

    A 400 m hillside under a 35 km wide view is ~1% of the frame and reads flat;
    the Alps under the same view need almost none. Clamped so flat rides stay
    honest and mountains never look like a cartoon.
    """
    relief = max(route_relief_m, 25.0)
    return float(np.clip(0.022 * view_width_m / relief, 1.25, 2.6))


def principal_bearing(x: np.ndarray, y: np.ndarray) -> float:
    """Compass bearing (deg, 0..180) of the long axis of a point cloud."""
    _, vecs = np.linalg.eigh(np.cov(np.vstack([x - x.mean(), y - y.mean()])))
    ax, ay = vecs[:, -1]
    return float(np.degrees(np.arctan2(ax, ay)) % 180.0)


def fit_view(
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    pitch: float,
    bearing: float,
    lat: float,
    width: int,
    height: int,
    box: tuple[float, float, float, float],
    *,
    lift: bool = False,
    zoom_range: tuple[float, float] = (3.0, 16.0),
) -> tuple[float, float, float, float]:
    """Look-at point (x, y, height) and zoom that fill ``box`` with the points as seen in perspective.

    Each pass moves the projected extent onto the box centre. With ``lift``, a
    vertical correction raises the look-at point as much as the camera looks
    across (sin² of the pitch) and moves it forward as much as it looks down.
    """
    b = np.radians(bearing)
    p = np.radians(pitch)
    share = float(np.sin(p) ** 2) if lift else 0.0
    cx, cy, cz = float(px.mean()), float(py.mean()), 0.0
    box_x = 0.5 * (box[0] + box[2]) * width
    box_y = 0.5 * (box[1] + box[3]) * height
    for _ in range(6):
        zoom = zoom_to_fill(cx, cy, cz, pitch, bearing, lat, width, height, px, py, pz, box, zoom_range=zoom_range)
        sx, sy, _ = project_points(cx, cy, cz, zoom, pitch, bearing, lat, width, height, px, py, pz)
        mpp = float(meters_per_pixel(zoom, lat))
        dx = 0.5 * (np.nanmin(sx) + np.nanmax(sx)) - box_x
        dy = 0.5 * (np.nanmin(sy) + np.nanmax(sy)) - box_y
        fwd = -(1.0 - share) * dy * mpp / max(np.cos(p), 0.3)
        cx += 0.8 * (dx * mpp * np.cos(b) + fwd * np.sin(b))
        cy += 0.8 * (-dx * mpp * np.sin(b) + fwd * np.cos(b))
        cz = max(0.0, cz - 0.8 * share * dy * mpp / max(np.sin(p), 0.3))
    zoom = zoom_to_fill(cx, cy, cz, pitch, bearing, lat, width, height, px, py, pz, box, zoom_range=zoom_range)
    return cx, cy, cz, zoom


def project_points(
    cx: float,
    cy: float,
    cz: float,
    zoom: float,
    pitch: float,
    bearing: float,
    lat: float,
    width: int,
    height: int,
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pinhole projection matching MapLibre's camera: local metres -> screen px.

    Returns (x, y, in_front). Good to a few pixels, which is all layout needs.
    """
    dx, dy, dz = eye_offset(np.array([zoom]), np.array([pitch]), np.array([bearing]), np.array([lat]), float(height))
    eye = np.array([cx + dx[0], cy + dy[0], cz + dz[0]])
    f = np.array([cx, cy, cz]) - eye
    f /= max(float(np.linalg.norm(f)), 1e-9)
    b = np.radians(bearing)
    r = np.array([np.cos(b), -np.sin(b), 0.0])
    u = np.cross(r, f)
    focal = 0.5 * height / np.tan(np.radians(FOV_DEG) / 2.0)
    vx, vy, vz = px - eye[0], py - eye[1], pz - eye[2]
    zc = vx * f[0] + vy * f[1] + vz * f[2]
    safe = np.where(zc > 1e-6, zc, np.nan)
    sx = 0.5 * width + focal * (vx * r[0] + vy * r[1] + vz * r[2]) / safe
    sy = 0.5 * height - focal * (vx * u[0] + vy * u[1] + vz * u[2]) / safe
    return sx, sy, zc > 1e-6


def zoom_to_fill(
    cx: float,
    cy: float,
    cz: float,
    pitch: float,
    bearing: float,
    lat: float,
    width: int,
    height: int,
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    box: tuple[float, float, float, float],
    zoom_range: tuple[float, float] = (8.0, 16.0),
) -> float:
    """Closest zoom at which every point projects inside ``box`` (fractions x0, y0, x1, y1).

    Framing by the projected extent, not by the length of the road: a
    switchback climb 5 km long may only span 1 km on screen.
    """
    x0, y0, x1, y1 = box[0] * width, box[1] * height, box[2] * width, box[3] * height

    def fits(zoom: float) -> bool:
        sx, sy, ok = project_points(cx, cy, cz, zoom, pitch, bearing, lat, width, height, px, py, pz)
        return bool(ok.all()) and sx.min() >= x0 and sx.max() <= x1 and sy.min() >= y0 and sy.max() <= y1

    lo, hi = zoom_range
    if fits(hi):
        return hi
    if not fits(lo):
        return lo
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return lo


def frame_points(
    cx: np.ndarray,
    cy: np.ndarray,
    cz: np.ndarray,
    zoom: np.ndarray,
    pitch: np.ndarray,
    bearing: np.ndarray,
    lat: float,
    width: int,
    height: int,
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    safe: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    fps: int,
    fill: float = 0.94,
    iterations: int = 5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centre and zoom so the points fill the safe box, then smooth: (cx, cy, zoom).

    Per frame, the projected bounding box is moved onto the box centre (a pan
    along the camera's own right and forward axes) and scaled to ``fill`` of
    it. The result is smoothed as one calm move and finally guarded by
    :func:`keep_points_in_frame`, so the smoothing never pushes points out.
    ``pz`` and ``safe`` follow the conventions of that function.
    """
    bx0, by0, bx1, by1 = (np.asarray(v, dtype=float) * s for v, s in zip(safe, (width, height, width, height), strict=True))
    cx, cy, out = (np.asarray(v, dtype=float).copy() for v in (cx, cy, zoom))
    b = np.radians(bearing)
    for i in range(len(out)):
        z_i = pz[i] if pz.ndim == 2 else pz
        for _ in range(iterations):
            sx, sy, ok = project_points(
                float(cx[i]), float(cy[i]), float(cz[i]), float(out[i]), float(pitch[i]), float(bearing[i]),
                lat, width, height, px, py, z_i,
            )
            if not ok.all():
                out[i] -= 0.5
                continue
            mpp = float(meters_per_pixel(out[i], lat))
            dx = 0.5 * (sx.min() + sx.max()) - 0.5 * (bx0[i] + bx1[i])
            dy = 0.5 * (sy.min() + sy.max()) - 0.5 * (by0[i] + by1[i])
            fwd = -dy * mpp / max(np.cos(np.radians(pitch[i])), 0.3)
            cx[i] += dx * mpp * np.cos(b[i]) + fwd * np.sin(b[i])
            cy[i] += -dx * mpp * np.sin(b[i]) + fwd * np.cos(b[i])
            ratio = min(
                fill * (bx1[i] - bx0[i]) / max(sx.max() - sx.min(), 1.0),
                fill * (by1[i] - by0[i]) / max(sy.max() - sy.min(), 1.0),
            )
            out[i] += 0.8 * np.log2(ratio)
    sigma = 0.6 * fps
    cx, cy = gaussian_smooth(cx, sigma), gaussian_smooth(cy, sigma)
    out = gaussian_smooth(np.minimum(out, gaussian_smooth(out, sigma)), sigma)
    out = keep_points_in_frame(cx, cy, cz, out, pitch, bearing, lat, width, height, px, py, pz, safe, fps, step=0.03)
    return cx, cy, out


def keep_points_in_frame(
    cx: np.ndarray,
    cy: np.ndarray,
    cz: np.ndarray,
    zoom: np.ndarray,
    pitch: np.ndarray,
    bearing: np.ndarray,
    lat: float,
    width: int,
    height: int,
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    safe: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    fps: int,
    step: float = 0.04,
    max_iter: int = 40,
) -> np.ndarray:
    """Pull the zoom back wherever any of the points leaves its safe box.

    ``pz`` is one height per point, or one row per frame for things that grow.
    ``safe`` holds per-frame (x0, y0, x1, y1) fractions of the frame, so the
    box can widen or narrow as labels come and go. Zoom only ever decreases,
    and the correction is smoothed so it reads as one calm dolly.
    """
    x0, y0, x1, y1 = (np.asarray(v, dtype=float) * s for v, s in zip(safe, (width, height, width, height), strict=True))
    out = np.asarray(zoom, dtype=float).copy()
    for _ in range(max_iter):
        bad = np.zeros(len(out), dtype=bool)
        for i in range(len(out)):
            sx, sy, ok = project_points(
                float(cx[i]), float(cy[i]), float(cz[i]), float(out[i]), float(pitch[i]), float(bearing[i]),
                lat, width, height, px, py, pz[i] if pz.ndim == 2 else pz,
            )
            bad[i] = (
                not ok.all()
                or sx.min() < x0[i] or sx.max() > x1[i] or sy.min() < y0[i] or sy.max() > y1[i]
            )
        if not bad.any():
            break
        out[bad] -= step
        out = np.minimum(out, gaussian_smooth(out, 0.5 * fps))
    return gaussian_smooth(np.minimum(out, gaussian_smooth(out, 0.5 * fps)), 0.4 * fps)
