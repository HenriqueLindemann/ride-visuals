"""Tiles a 3D scene will ask for, fetched into the cache before the render starts.

Without this the tile server downloads on first request, in the middle of the
render: every frame waits on the network, and an upstream hiccup only shows up
as a warning (or a hole in the relief) hours later. The director already knows
the camera of every frame, so the tile set can be estimated up front from the
serialized spec alone (``camera`` and ``tiles``), fetched in parallel, and any
failure reported before a single frame is rendered.

The estimate follows MapLibre's ``coveringTiles``: a grid of screen rays is cast
onto the ground at the camera's centre elevation, and each ground point asks
for the tile zoom MapLibre's distance rule gives it (``calculateTileZoom``), per
source tile size, rounding and zoom range as declared in style.ts. Each tile's
neighbours are included too (sampling gaps, relief above the ground plane,
contour borders). Whatever it still misses is fetched on demand as before, and
the tile server counts it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ride_visuals.scene3d.camera import EARTH_CIRCUMFERENCE_M, FOV_DEG
from ride_visuals.scene3d.tiles import TILE_SOURCES, TileCache

Tile = tuple[int, int, int]

#: MapLibre's map tiles are 512 px (transform.tileSize).
MAP_TILE_SIZE = 512
#: covering_tiles.ts defaults (zoom levels on screen, tile count ratio).
DEFAULT_LOD = (9.314, 3.0)
#: The map's tiles while a city stands in 3D (TILE_LOD in MapStage.tsx).
CITY_LOD = (1.0, 30.0)
#: mercator_utils.ts: rays are never followed further out than this from nadir.
MAX_HORIZON_ANGLE_DEG = 89.25
#: One camera sample per this many seconds; neighbours cover the motion between.
SAMPLE_EVERY_S = 0.25
#: Screen rays per sample (columns, rows): about 120 px apart at 1080p.
GRID = (17, 11)
#: Zoom levels short of a split at which the finer level is fetched as well.
SPLIT_MARGIN = 0.3
#: MapLibre also loads ancestors this many levels up as placeholders (map
#: option prefetchZoomDelta, default 4).
PREFETCH_ZOOM_DELTA = 4
#: Contours exist from this map zoom (style.ts contours.minzoom).
CONTOUR_MIN_ZOOM = 10


@dataclass(frozen=True)
class _Layer:
    """One way a source's tiles are requested (style.ts)."""

    source: str
    tile_size: int
    round_zoom: bool
    min_zoom: int
    max_zoom: int
    #: Frames (boolean mask) on which the layer can request tiles.
    active: np.ndarray
    #: How fast pitched tiles drop levels (setSourceTileLodParams).
    lod: tuple[float, float] = DEFAULT_LOD


@dataclass
class PrefetchReport:
    tiles: dict[str, set[Tile]] = field(default_factory=dict)
    cached: int = 0
    downloaded: int = 0
    empty: int = 0
    failed: list[tuple[str, Tile]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(len(tiles) for tiles in self.tiles.values())


def _integral_cos_pow(p: float, x1: float, x2: float) -> float:
    """Midpoint rule over 10 points, as MapLibre's integralOfCosXByP."""
    dx = (x2 - x1) / 10.0
    return sum(dx * math.cos(x1 + (i + 0.5) * dx) ** p for i in range(10))


def _tile_zoom_offset(
    center_pitch_deg: float, dist2d: np.ndarray, height: float, center_dist: float, lod: tuple[float, float]
) -> np.ndarray:
    """calculateTileZoom minus the requested centre zoom, for ground points at ``dist2d``."""
    levels, ratio = lod
    behaviour = 2.0 * (
        (levels - 1.0)
        / math.log2(math.cos(math.radians(MAX_HORIZON_ANGLE_DEG - FOV_DEG)) / math.cos(math.radians(MAX_HORIZON_ANGLE_DEG)))
        - 1.0
    )
    half_fov = math.radians(FOV_DEG / 2.0)
    count_pitch0 = 2.0 * _integral_cos_pow(behaviour - 1.0, 0.0, half_fov)
    centre = math.radians(center_pitch_deg)
    highest = min(math.radians(MAX_HORIZON_ANGLE_DEG), centre + half_fov)
    lowest = min(highest, centre - half_fov)
    tile_count = _integral_cos_pow(behaviour - 1.0, lowest, highest)
    tile_pitch = np.arctan(dist2d / height)
    dist3d = np.hypot(dist2d, height)
    offset = np.log2(center_dist / dist3d / max(0.5, math.cos(half_fov)))
    offset = offset + behaviour * np.log2(np.maximum(np.cos(tile_pitch), 1e-9)) / 2.0
    return offset - math.log2(max(1.0, tile_count / count_pitch0 / ratio)) / 2.0


def _ground_points(zoom: float, pitch: float, bearing: float, lat: float, width: int, height: int):
    """Screen-grid rays on the ground plane: (east, north) metres from the centre, eye height and distance."""
    focal = 0.5 * height / math.tan(math.radians(FOV_DEG) / 2.0)
    mpp = EARTH_CIRCUMFERENCE_M * math.cos(math.radians(lat)) / (MAP_TILE_SIZE * 2.0**zoom)
    center_dist = focal * mpp
    p, b = math.radians(pitch), math.radians(bearing)
    eye_h = max(center_dist * math.cos(p), 1e-3)
    horizontal = center_dist * math.sin(p)
    eye = np.array([-horizontal * math.sin(b), -horizontal * math.cos(b), eye_h])
    forward = -eye / center_dist
    right = np.array([math.cos(b), -math.sin(b), 0.0])
    up = np.cross(right, forward)

    u, v = np.meshgrid(np.linspace(-0.5, 0.5, GRID[0]) * width, np.linspace(-0.5, 0.5, GRID[1]) * height)
    rays = forward[None, :] * focal + right[None, :] * u.reshape(-1, 1) + up[None, :] * v.reshape(-1, 1)
    reach = np.hypot(rays[:, 0], rays[:, 1])
    from_nadir = np.minimum(np.arctan2(reach, -rays[:, 2]), math.radians(MAX_HORIZON_ANGLE_DEG))
    dist2d = eye_h * np.tan(from_nadir)
    direction = rays[:, :2] / np.maximum(reach, 1e-9)[:, None]
    ground = eye[None, :2] + direction * dist2d[:, None]
    return ground, dist2d, eye_h, center_dist


def _layers(spec: dict[str, Any], frames: int) -> list[_Layer]:
    tiles, cam = spec["tiles"], spec["camera"]
    every = np.ones(frames, dtype=bool)
    dem_max = int(tiles["demMaxZoom"])
    contour_max = max(CONTOUR_MIN_ZOOM, min(dem_max - 2, 14))
    contours = np.asarray(cam["contours"], dtype=float) > 0
    city = np.asarray(cam.get("buildings", np.zeros(frames)), dtype=float) > 0
    layers = [
        # Hillshade rounds like every raster source; the terrain mesh floors.
        _Layer("dem", 128, True, 0, dem_max, every),
        _Layer("dem", 128, False, 0, dem_max, every),
        _Layer("vector", MAP_TILE_SIZE, False, 0, int(tiles["vectorMaxZoom"]), ~city),
        _Layer("vector", MAP_TILE_SIZE, False, 0, int(tiles["vectorMaxZoom"]), city, CITY_LOD),
        # maplibre-contour: one DEM tile of the contour tile's own level (overzoom 0).
        _Layer("dem", MAP_TILE_SIZE, False, CONTOUR_MIN_ZOOM, min(contour_max, dem_max, 14), contours),
    ]
    if spec.get("look") == "satellite" and tiles.get("satellite"):
        satellite = np.asarray(cam["satellite"], dtype=float) > 0
        layers.append(_Layer("satellite", 256, True, 0, int(tiles["satelliteMaxZoom"]), satellite))
    return layers


def _with_ancestors(tiles: Iterable[Tile], levels: int) -> set[Tile]:
    out = set(tiles)
    for z, x, y in list(out):
        for up in range(1, min(levels, z) + 1):
            out.add((z - up, x >> up, y >> up))
    return out


def _with_neighbours(tiles: Iterable[Tile]) -> set[Tile]:
    out: set[Tile] = set()
    for z, x, y in tiles:
        n = 2**z
        for dy in (-1, 0, 1):
            if 0 <= y + dy < n:
                out.update((z, (x + dx) % n, y + dy) for dx in (-1, 0, 1))
    return out


def scene_tiles(spec: dict[str, Any], *, sample_every_s: float = SAMPLE_EVERY_S) -> dict[str, set[Tile]]:
    """Tiles per source (keys of TILE_SOURCES) a serialized scene spec is expected to request."""
    cam = spec["camera"]
    profile = spec["profile"]
    width, height = int(profile["width"]), int(profile["height"])
    frames = len(cam["zoom"])
    step = max(1, round(sample_every_s * int(profile["fps"])))
    samples = sorted({*range(0, frames, step), frames - 1})
    layers = _layers(spec, frames)
    found: dict[str, set[Tile]] = {layer.source: set() for layer in layers}
    terrain = np.asarray(cam["terrain"], dtype=float)
    max_constant_pitch = min(max(78.5 - FOV_DEG / 2.0, 0.0), 60.0)

    for i in samples:
        zoom, pitch, lat = float(cam["zoom"][i]), float(cam["pitch"][i]), float(cam["lat"][i])
        ground, dist2d, eye_h, center_dist = _ground_points(zoom, pitch, float(cam["bearing"][i]), lat, width, height)
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        mx0 = (float(cam["lon"][i]) + 180.0) / 360.0
        my0 = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0
        # Local metres to Web Mercator units (0..1) at the centre's latitude.
        mx = np.clip(mx0 + ground[:, 0] / (EARTH_CIRCUMFERENCE_M * cos_lat), 0.0, 1.0 - 1e-12)
        my = np.clip(my0 - ground[:, 1] / (EARTH_CIRCUMFERENCE_M * cos_lat), 0.0, 1.0 - 1e-12)
        variable = terrain[i] > 0 or pitch > max_constant_pitch

        for layer in layers:
            if not layer.active[i]:
                continue

            def offset_at(dist: np.ndarray, *, variable=variable, pitch=pitch, eye_h=eye_h, center_dist=center_dist, lod=layer.lod):
                return _tile_zoom_offset(pitch, dist, eye_h, center_dist, lod) if variable else np.zeros(len(dist))

            point_offset = offset_at(dist2d)
            requested = zoom + math.log2(MAP_TILE_SIZE / layer.tile_size)
            if requested + 0.5 < layer.min_zoom:
                continue
            rounding = np.round if layer.round_zoom else np.floor
            z = np.clip(rounding(requested + point_offset), 0, layer.max_zoom)
            # MapLibre descends the tile tree and splits a tile while its
            # nearest point asks for a finer level: the tile around a ground
            # point can be finer than the point's own distance gives. Follow
            # that descent with the nearest point bounded by half a diagonal.
            for _ in range(layer.max_zoom):
                edge_m = EARTH_CIRCUMFERENCE_M * cos_lat / 2.0**z
                near = np.maximum(dist2d - 0.7071 * edge_m, 1.0)
                split = (rounding(requested + offset_at(near)) > z) & (z < layer.max_zoom)
                if not split.any():
                    break
                z = z + split
            # Close to a split the bound above is too coarse to call: take
            # the finer level too where the nearest point is within a margin.
            edge_m = EARTH_CIRCUMFERENCE_M * cos_lat / 2.0**z
            near = np.maximum(dist2d - 0.7071 * edge_m, 1.0)
            close = rounding(requested + offset_at(near) + SPLIT_MARGIN) > z
            for level in (z, np.where(close, np.minimum(z + 1, layer.max_zoom), z)):
                level = level.astype(int)
                n = 2.0**level
                xs = np.floor(mx * n).astype(int)
                ys = np.floor(my * n).astype(int)
                keep = level >= layer.min_zoom
                found[layer.source].update(
                    zip(level[keep].tolist(), xs[keep].tolist(), ys[keep].tolist(), strict=True)
                )
    return {source: _with_ancestors(_with_neighbours(tiles), PREFETCH_ZOOM_DELTA) for source, tiles in found.items()}


def prefetch_tiles(
    cache: TileCache,
    tiles: dict[str, set[Tile]],
    *,
    workers: int = 8,
    progress: Callable[[int, int], None] | None = None,
) -> PrefetchReport:
    """Fetch every listed tile into the cache (upstream politeness is TileCache's own limit)."""
    report = PrefetchReport(tiles=tiles)
    jobs = [(source, tile) for source, keys in tiles.items() for tile in sorted(keys)]

    def fetch(job: tuple[str, Tile]) -> tuple[str, Tile, str]:
        source, (z, x, y) = job
        definition = TILE_SOURCES[source]
        if cache.path(definition, z, x, y).exists():
            return source, (z, x, y), "cached"
        data = cache.get(definition, z, x, y)
        if data is None:
            return source, (z, x, y), "failed"
        return source, (z, x, y), "downloaded" if data else "empty"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, (source, tile, outcome) in enumerate(pool.map(fetch, jobs), start=1):
            if outcome == "failed":
                report.failed.append((source, tile))
            elif outcome == "cached":
                report.cached += 1
            elif outcome == "empty":
                report.empty += 1
            else:
                report.downloaded += 1
            if progress is not None:
                progress(done, len(jobs))
    return report
