"""Tiles a 3D scene will ask for, fetched into the cache before the render starts.

The director knows every frame's camera, so the tiles follow from the spec alone:
a port of MapLibre's ``coveringTiles`` (6.11), mercator or globe, run per source
with the tile size, rounding, zoom range and LOD that style.ts and MapStage.tsx
declare. Fetching them up front keeps the network out of the render; whatever
is still missed is fetched on demand, and the tile server counts it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ride_visuals.scene3d.camera import span, travel
from ride_visuals.scene3d.tiles import TILE_SOURCES, TileCache

Tile = tuple[int, int, int]
#: The tiles of one zoom level: (zoom, x, y arrays).
_Level = tuple[int, np.ndarray, np.ndarray]
#: Height range (low, high) in metres of the tiles at a zoom, x and y.
_Boxes = Callable[[int, np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]

#: MapLibre's map tiles are 512 px (transform.tileSize).
MAP_TILE_SIZE = 512
#: Zoom levels on screen and tile count ratio (TILE_LOD in MapStage.tsx): rasters
#: and the terrain, vector tiles, and buildings while a city stands in 3D.
RASTER_LOD = (3.0, 10.0)
VECTOR_LOD = (1.0, 12.0)
CITY_LOD = (1.0, 30.0)
#: Steep views open the raster levels up to this many over this pitch range (rasterLevels).
RASTER_OPEN_LEVELS = 6.0
RASTER_OPEN_PITCH = (55.0, 75.0)
#: Buildings are drawn from this map zoom (style.ts), or while they stand.
BUILDINGS_MIN_ZOOM = 13.0
#: Contours exist from this tile level (style.ts CONTOUR_MIN_ZOOM).
CONTOUR_MIN_ZOOM = 8
#: One camera sample per this many seconds: a steep view sweeps new horizon tiles every frame.
SAMPLE_EVERY_S = 1 / 30

#: MapLibre's earth radius (m) and default vertical field of view.
EARTH_RADIUS_M = 6371008.8
FOV_RAD = 0.6435011087932844
#: The style's globe projection hands over to mercator at this zoom (style.ts, 'globe').
GLOBE_MAX_ZOOM = 12.0
#: mercator_utils.ts: the horizon is never followed past this angle from nadir.
MAX_HORIZON_ANGLE_DEG = 89.25
#: covering_tiles.ts: tile boxes grow up to this tall near the horizon, over this many degrees.
ASSUMED_MAX_FEATURE_HEIGHT_M = 500.0
CULLING_ONSET_DEG = 15.0
#: Tile coordinates run 0..EXTENT within a tile.
EXTENT = 8192
#: TerrainTileManager: the DEM sits this many levels above a terrain tile; the tile
#: manager also loads the parent and this ancestor level of every terrain tile.
TERRAIN_DELTA_ZOOM = 1
TERRAIN_ROOT_ZOOM = 5


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
    #: How fast pitched tiles drop levels (setSourceTileLodParams); None for rasters, by pitch.
    lod: tuple[float, float] | None = None
    #: The 3D terrain's own tiles: their parents and root ancestors load too.
    terrain: bool = False
    #: Contour tiles read the DEM tile of their own level (up to this one) and its 8 neighbours (maplibre-contour).
    dem_cap: int | None = None


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


def raster_lod(pitch: float) -> tuple[float, float]:
    """The rasters' LOD at a pitch, as MapStage.tsx sets it (rounded to 0.05 levels)."""
    levels = RASTER_LOD[0] + (RASTER_OPEN_LEVELS - RASTER_LOD[0]) * float(
        travel(span(pitch, *RASTER_OPEN_PITCH))
    )
    return round(levels * 20.0) / 20.0, RASTER_LOD[1]


def _layers(spec: dict[str, Any], frames: int) -> list[_Layer]:
    tiles, cam = spec["tiles"], spec["camera"]
    every = np.ones(frames, dtype=bool)
    dem_max, land_max = int(tiles["demMaxZoom"]), int(tiles["landMaxZoom"])
    vector_max = int(tiles["vectorMaxZoom"])
    contours = np.asarray(cam["contours"], dtype=float) > 0
    terrain = np.asarray(cam["terrain"], dtype=float) > 0
    city = np.asarray(cam.get("buildings", np.zeros(frames)), dtype=float) > 0
    streets = ~city & (np.asarray(cam["zoom"], dtype=float) >= BUILDINGS_MIN_ZOOM)
    layers = [
        # Hillshade rounds like every raster source. The terrain mesh (style.ts
        # declares 128 px) is covered with 256 px tiles one level coarser, floored.
        _Layer("dem", 128, True, 0, dem_max, every),
        _Layer("dem", 256, False, 0, dem_max - 1, terrain, terrain=True),
        _Layer("vector", MAP_TILE_SIZE, False, 0, land_max, every, VECTOR_LOD),
        _Layer("vector", MAP_TILE_SIZE, False, 0, vector_max, streets, VECTOR_LOD),
        _Layer("vector", MAP_TILE_SIZE, False, 0, vector_max, city, CITY_LOD),
        # Contour tiles cover the land like its vector tiles, from the DEM of their own level.
        _Layer(
            "dem",
            MAP_TILE_SIZE,
            False,
            CONTOUR_MIN_ZOOM,
            land_max,
            contours,
            VECTOR_LOD,
            dem_cap=min(dem_max, 14),
        ),
    ]
    if spec.get("look") == "satellite" and tiles.get("satellite"):
        satellite = np.asarray(cam["satellite"], dtype=float) > 0
        layers.append(
            _Layer("satellite", 256, True, 0, int(tiles["satelliteMaxZoom"]), satellite)
        )
    return layers


# Matrices, as gl-matrix composes them (column vectors, each step on the right) ---------------


def _rotate(axis: int, angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    out = np.eye(4)
    i, j = [(1, 2), (2, 0), (0, 1)][axis]
    out[i, i], out[i, j], out[j, i], out[j, j] = c, -s, s, c
    return out


def _translate(x: float, y: float, z: float) -> np.ndarray:
    out = np.eye(4)
    out[:3, 3] = (x, y, z)
    return out


def _perspective(near: float, far: float, aspect: float) -> np.ndarray:
    f, nf = 1.0 / math.tan(FOV_RAD / 2.0), 1.0 / (near - far)
    out = np.zeros((4, 4))
    out[0, 0], out[1, 1], out[2, 2], out[2, 3], out[3, 2] = (
        f / aspect,
        f,
        (far + near) * nf,
        2.0 * far * near * nf,
        -1.0,
    )
    return out


#: Clip space corners of the view volume, and the corner triples each plane is made from (frustum.ts).
_CORNERS = np.array(
    [
        [-1, 1, -1],
        [1, 1, -1],
        [1, -1, -1],
        [-1, -1, -1],
        [-1, 1, 1],
        [1, 1, 1],
        [1, -1, 1],
        [-1, -1, 1],
    ],
    dtype=float,
)
_PLANES = [(0, 1, 2), (6, 5, 4), (0, 3, 7), (2, 1, 5), (3, 2, 6), (0, 4, 5)]
#: The globe's matrix looks down -z, so its near and far planes swap.
_PLANES_FLIPPED = [(6, 5, 4), (0, 1, 2), (0, 3, 7), (2, 1, 5), (3, 2, 6), (0, 4, 5)]


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


@dataclass
class _Frustum:
    """Frustum.fromInvProjectionMatrix: corner points (8, 3), planes (6, 4) and their box."""

    points: np.ndarray
    planes: np.ndarray

    @classmethod
    def of(cls, points: np.ndarray, flipped: bool = False) -> _Frustum:
        planes = np.empty((6, 4))
        for k, (i, j, m) in enumerate(_PLANES_FLIPPED if flipped else _PLANES):
            normal = _unit(np.cross(points[i] - points[j], points[m] - points[j]))
            planes[k] = (*normal, -normal @ points[j])
        return cls(points, planes)


def _fit_far_plane(points: np.ndarray, horizon: np.ndarray) -> None:
    """Pull the far corners in to the horizon plane (adjustFarPlaneByHorizonPlane, flipped)."""
    near, far = points[4:], points[:4]
    rays = far - near
    lengths = np.linalg.norm(rays, axis=1)
    rays /= lengths[:, None]
    along = rays @ horizon[:3]
    reach = np.where(
        along != 0.0,
        (-(near @ horizon[:3]) - horizon[3]) / np.where(along != 0.0, along, 1.0),
        -1.0,
    )
    longest = float(np.max(np.where(reach >= 0.0, reach, lengths)))
    normal = _unit(np.cross(points[6] - points[5], points[4] - points[5]))
    plane = np.array([*normal, -normal @ points[6]])
    unit = horizon / np.linalg.norm(horizon[:3])
    view = normal - unit[:3] * (normal @ unit[:3])
    if (length := np.linalg.norm(view)) > 0:
        furthest = unit[:3] * -unit[3] + view * (math.sqrt(1.0 - unit[3] ** 2) / length)
        longest = min(longest, float(plane[:3] @ furthest + plane[3]) / float(rays[0] @ normal))
    points[:4] = near + rays * np.minimum(longest, lengths)[:, None]


# The camera as coveringTiles sees it ---------------------------------------------------------


def _cos_integral(p: float, x1: float, x2: float) -> float:
    """Midpoint rule over 10 points, as MapLibre's integralOfCosXByP."""
    return sum(
        (x2 - x1) / 10.0 * math.cos(x1 + (i + 0.5) / 10.0 * (x2 - x1)) ** p for i in range(10)
    )


@dataclass
class _View:
    """One frame's camera: mercator coordinates for distances, and the frustum tiles are culled with."""

    zoom: float
    pitch: float
    terrain: float
    #: Camera and centre in mercator coordinates (z too), and the box height used without relief.
    camera: np.ndarray
    centre: np.ndarray
    culling_elevation: float
    frustum: _Frustum
    #: The globe's horizon plane (4,); None in mercator.
    horizon: np.ndarray | None = None

    @classmethod
    def at(
        cls,
        camera: tuple[float, float, float, float, float],
        elevation: float,
        terrain: float,
        size: tuple[int, int],
        *,
        globe: bool = False,
    ) -> _View:
        """A frame's camera (lon, lat, zoom, pitch, bearing), centre elevation and terrain exaggeration."""
        (lon, lat, zoom, pitch, bearing), (width, height) = camera, size
        lat = max(-85.051129, min(85.051129, lat))
        circumference = 2.0 * math.pi * EARTH_RADIUS_M * math.cos(math.radians(lat))
        world = MAP_TILE_SIZE * 2.0**zoom
        to_camera = 0.5 / math.tan(FOV_RAD / 2.0) * height
        p, b = math.radians(pitch), math.radians(bearing)
        mx = ((lon + 180.0) / 360.0) % 1.0
        my = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0
        centre = np.array([mx, my, elevation / circumference])
        eye = centre + to_camera / world * np.array(
            [-math.sin(p) * math.sin(b), math.sin(p) * math.cos(b), math.cos(p)]
        )
        # getElevationForTileCulling: boxes grow tall as the frustum's bottom edge nears the horizon.
        bottom = MAX_HORIZON_ANGLE_DEG - pitch - math.degrees(FOV_RAD) / 2.0
        culling = (
            elevation
            + min(max((CULLING_ONSET_DEG - bottom) / CULLING_ONSET_DEG, 0.0), 1.0)
            * ASSUMED_MAX_FEATURE_HEIGHT_M
        )
        if globe:
            frustum, horizon = _globe_frustum(
                math.radians(lon), math.radians(lat), p, b, to_camera, world, width / height
            )
            return cls(zoom, pitch, terrain, eye, centre, culling, frustum, horizon)
        frustum = _mercator_frustum(
            mx, my, p, b, elevation, to_camera, world, world / circumference, width, height
        )
        return cls(zoom, pitch, terrain, eye, centre, culling, frustum)

    def variable(self, centre_zoom: float) -> bool:
        """allowVariableZoom: the globe from level 5 on; mercator with terrain or a pitch past the horizon's one-level reach."""
        if self.horizon is not None:
            return centre_zoom > 4
        return self.terrain > 0 or self.pitch > min(
            max(78.5 - math.degrees(FOV_RAD) / 2.0, 0.0), 60.0
        )

    def distance(self, zoom: int, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """distanceToTile2d: from the camera to the tile square, in mercator units."""
        size = 1.0 / (1 << zoom)
        cx, cy = x * size, y * size
        px, py = self.camera[:2]
        if self.horizon is None:
            return np.hypot(np.clip(px, cx, cx + size) - px, np.clip(py, cy, cy + size) - py)

        def edge(point, corner):
            delta = point - corner
            return np.where(delta < 0, -delta, np.maximum(0.0, delta - size))

        def wrapped(corner_x, corner_y):
            dx = px - corner_x
            across = np.where(
                dx < 0,
                np.minimum(-dx, 1.0 + dx - size),
                np.where(dx > size, np.minimum(np.maximum(dx - size, 0.0), 1.0 - dx), 0.0),
            )
            return np.maximum(across, edge(py, corner_y))

        # The tile itself, and across either pole (mirrored in y, half a world over in x).
        return np.minimum(
            np.minimum(wrapped(cx, cy), wrapped(cx + 0.5, -cy - size)),
            wrapped(cx + 0.5, 2.0 - cy - size),
        )

    def visibility(
        self, zoom: int, x: np.ndarray, y: np.ndarray, low: np.ndarray, high: np.ndarray
    ) -> np.ndarray:
        """isTileVisible for the tiles' volumes: 0 outside, 1 partly inside, 2 inside."""
        if self.horizon is not None:
            return _globe_visibility(
                self.frustum,
                self.horizon,
                *_tile_volumes(zoom, x, y, low, np.maximum(high, max(0.0, self.culling_elevation))),
            )
        size = float(1 << zoom)
        box_low = np.column_stack([x / size, y / size, low])
        box_high = np.column_stack([(x + 1) / size, (y + 1) / size, high])
        planes = self.frustum.planes
        positive, negative = np.maximum(planes[:, :3], 0.0).T, np.minimum(planes[:, :3], 0.0).T
        nearest = planes[:, 3] + box_low @ positive + box_high @ negative
        farthest = planes[:, 3] + box_high @ positive + box_low @ negative
        points = self.frustum.points
        apart = (box_low > points.max(axis=0)).any(axis=1) | (box_high < points.min(axis=0)).any(
            axis=1
        )
        return np.where(
            (farthest < 0).any(axis=1),
            0,
            np.where((nearest >= 0).all(axis=1), 2, np.where(apart, 0, 1)),
        )

    def tile_zoom(
        self, lod: tuple[float, float], centre_zoom: float
    ) -> Callable[[np.ndarray], np.ndarray]:
        """createCalculateTileZoomFunction: the zoom a tile asks for from its 2D distance to the camera."""
        levels, ratio = lod
        fov = math.degrees(FOV_RAD)
        behaviour = 2.0 * (
            (levels - 1.0)
            / math.log2(
                math.cos(math.radians(MAX_HORIZON_ANGLE_DEG - fov))
                / math.cos(math.radians(MAX_HORIZON_ANGLE_DEG))
            )
            - 1.0
        )
        dist_z = abs(self.centre[2] - self.camera[2])
        dist_centre = math.hypot(*(self.centre[:2] - self.camera[:2]), dist_z)
        centre_pitch = math.acos(dist_z / dist_centre)
        half_fov = FOV_RAD / 2.0
        highest = min(math.radians(MAX_HORIZON_ANGLE_DEG), centre_pitch + half_fov)
        lowest = min(highest, centre_pitch - half_fov)
        count_flat = 2.0 * _cos_integral(behaviour - 1.0, 0.0, half_fov)
        count = _cos_integral(behaviour - 1.0, lowest, highest)
        bias = centre_zoom - math.log2(max(1.0, count / count_flat / ratio)) / 2.0
        scale = dist_centre / max(0.5, math.cos(half_fov))

        def zoom_at(dist_2d: np.ndarray) -> np.ndarray:
            cos_pitch = np.maximum(np.cos(np.arctan(dist_2d / dist_z)), 1e-12)
            return (
                bias
                + np.log2(scale / np.hypot(dist_2d, dist_z))
                + behaviour * np.log2(cos_pitch) / 2.0
            )

        return zoom_at


def _mercator_frustum(
    mx, my, p, b, elevation, to_camera, world, metre_px, width, height
) -> _Frustum:
    """MercatorTransform._calcMatrices and _calculateNearFarZ: x and y in mercator units, z in metres."""
    pitch = math.degrees(p)
    limited = math.radians(min(pitch, MAX_HORIZON_ANGLE_DEG))
    sea = max(to_camera / 2.0, to_camera + elevation * metre_px / math.cos(limited))
    lowest_elevation = min(elevation, 0.0, math.cos(p) * to_camera / metre_px + elevation - 100.0)
    lowest = sea - lowest_elevation * metre_px / math.cos(limited) if lowest_elevation < 0 else sea
    ground, half = math.pi / 2.0 + p, FOV_RAD / 2.0

    def to_surface(angle: float) -> float:
        return (
            math.sin(angle)
            * lowest
            / math.sin(min(max(math.pi - ground - angle, 0.01), math.pi - 0.01))
        )

    horizon = to_camera * min(
        math.tan(math.radians(90.0 - pitch)) * 0.85,
        math.tan(math.radians(MAX_HORIZON_ANGLE_DEG - pitch)),
    )
    horizon_angle = math.atan(horizon / to_camera)
    to_horizon = max(horizon_angle, math.radians(90.0 - MAX_HORIZON_ANGLE_DEG))
    far = (
        math.cos(math.pi / 2.0 - limited) * min(to_surface(half), to_surface(to_horizon)) + lowest
    ) * 1.01
    view = (
        _perspective(height / 50.0, far, width / height)
        @ np.diag([1.0, -1.0, 1.0, 1.0])
        @ _translate(0, 0, -to_camera)
        @ _rotate(0, p)
        @ _rotate(2, -b)
        @ _translate(-mx * world, -my * world, 0)
        @ np.diag([1.0, 1.0, metre_px, 1.0])
        @ _translate(0, 0, -elevation)
    )
    corners = (np.linalg.inv(view) @ np.column_stack([_CORNERS, np.ones(8)]).T).T
    return _Frustum.of(
        np.column_stack(
            [
                corners[:, 0] / corners[:, 3] / world,
                corners[:, 1] / corners[:, 3] / world,
                corners[:, 2] / corners[:, 3],
            ]
        )
    )


def _globe_frustum(lon, lat, p, b, to_camera, world, aspect) -> tuple[_Frustum, np.ndarray]:
    """VerticalPerspectiveTransform: the unit globe seen from the camera, and its horizon plane."""
    radius = world / (2.0 * math.pi) / math.cos(lat)
    view = (
        _perspective(0.5, to_camera + radius * 2.0, aspect)
        @ _translate(0, 0, -to_camera)
        @ _rotate(0, -p)
        @ _rotate(2, b)
        @ _translate(0, 0, -radius)
        @ _rotate(0, lat)
        @ _rotate(1, -lon)
        @ np.diag([radius, radius, radius, 1.0])
    )
    corners = (
        np.linalg.inv(view)
        @ np.diag([1.0, 1.0, -1.0, 1.0])
        @ np.column_stack([_CORNERS, np.ones(8)]).T
    ).T
    points = corners[:, :3] / corners[:, 3:]
    # _computeClippingPlane: the tangent plane through everything the camera can see of the globe.
    to_centre = to_camera / radius
    along, up = math.sin(p) * to_centre, math.cos(p) * to_centre + 1.0
    to_camera_unit = np.array([0.0, -along, up]) / math.hypot(along, up)
    vector = (_rotate(1, lon) @ _rotate(0, -lat) @ _rotate(2, -b))[:3, :3] @ to_camera_unit
    horizon = np.array(
        [*(vector / np.linalg.norm(vector)), -1.0 / math.hypot(along, up) / np.linalg.norm(vector)]
    )
    _fit_far_plane(points, horizon)
    return _Frustum.of(points, flipped=True), horizon


def _plane_triples(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """threePlaneIntersection for planes (n, 4)."""
    cross_bc, cross_ca, cross_ab = (
        np.cross(b[:, :3], c[:, :3]),
        np.cross(c[:, :3], a[:, :3]),
        np.cross(a[:, :3], b[:, :3]),
    )
    det = np.einsum("ni,ni->n", a[:, :3], cross_bc)
    return (-a[:, 3:] * cross_bc - b[:, 3:] * cross_ca - c[:, 3:] * cross_ab) / det[:, None]


def _aabb_volume(low: np.ndarray, high: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """ConvexVolume.fromAabb for boxes (n, 3): corner points (n, 8, 3) and planes (n, 6, 4)."""
    corner = np.array([[(i >> axis) & 1 for axis in range(3)] for i in range(8)], dtype=bool)
    points = np.stack(
        [
            np.where(corner[None, :, axis], high[:, None, axis], low[:, None, axis])
            for axis in range(3)
        ],
        axis=-1,
    )
    planes = np.zeros((len(low), 6, 4))
    for axis in range(3):
        planes[:, 2 * axis, axis], planes[:, 2 * axis, 3] = -1.0, high[:, axis]
        planes[:, 2 * axis + 1, axis], planes[:, 2 * axis + 1, 3] = 1.0, -low[:, axis]
    return points, planes


def _tile_volumes(
    zoom: int, x: np.ndarray, y: np.ndarray, low: np.ndarray, high: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """GlobeCoveringTilesDetailsProvider's volumes for tiles of one level: points (n, 8, 3) and planes (n, 6, 4)."""
    n = len(x)
    top, bottom = 1.0 + high / EARTH_RADIUS_M, 1.0 + low / EARTH_RADIUS_M
    if zoom <= 1:
        # The whole globe, or a quarter of it (x is 1 at lng E90, y at the north pole, z at null island).
        if zoom == 0:
            return _aabb_volume(
                -np.repeat(top[:, None], 3, axis=1), np.repeat(top[:, None], 3, axis=1)
            )
        zeros = np.zeros(n)
        return _aabb_volume(
            np.column_stack([np.where(x == 0, -top, zeros), np.where(y == 0, zeros, -top), -top]),
            np.column_stack([np.where(x == 0, zeros, top), np.where(y == 0, top, zeros), top]),
        )

    scale = 1.0 / (1 << zoom)

    def sphere(ix: float, iy: float) -> np.ndarray:
        mx, my = ix / EXTENT * scale + x * scale, iy / EXTENT * scale + y * scale
        lon, lat = (
            (mx * 2.0 * math.pi + math.pi) % (2.0 * math.pi),
            2.0 * np.arctan(np.exp(math.pi - my * 2.0 * math.pi)) - math.pi / 2.0,
        )
        return np.column_stack([np.sin(lon) * np.cos(lat), np.sin(lat), np.cos(lon) * np.cos(lat)])

    c = [sphere(0, 0), sphere(EXTENT, 0), sphere(EXTENT, EXTENT), sphere(0, EXTENT)]
    centre = sphere(EXTENT / 2, EXTENT / 2)
    south = (y >= (1 << zoom) / 2)[:, None]
    middle = np.where(south, sphere(EXTENT / 2, 0), sphere(EXTENT / 2, EXTENT))
    north_pole = np.where((y == 0)[:, None], np.array([0.0, 1.0, 0.0]), c[0] * top[:, None])
    south_pole = np.where(
        (y == (1 << zoom) - 1)[:, None], np.array([0.0, -1.0, 0.0]), c[0] * top[:, None]
    )
    extremes = np.stack(
        [k * top[:, None] for k in c]
        + [k * bottom[:, None] for k in c]
        + [north_pole, south_pole, centre * top[:, None], middle * top[:, None]],
        axis=1,
    )
    east = _unit(np.cross([0.0, 1.0, 0.0], centre))
    north = _unit(np.cross(centre, east))
    axis_east, axis_west = _unit(np.cross(c[2], c[1])), _unit(np.cross(c[0], c[3]))
    up_down = np.einsum("nc,npc->np", centre, extremes)
    north_south = np.einsum("nc,npc->np", north, extremes)
    zero = np.zeros((n, 1))
    up = np.concatenate([-centre, up_down.max(axis=1, keepdims=True)], axis=1)
    down = np.concatenate([centre, -up_down.min(axis=1, keepdims=True)], axis=1)
    to_north = np.concatenate([-north, north_south.max(axis=1, keepdims=True)], axis=1)
    to_south = np.concatenate([north, -north_south.min(axis=1, keepdims=True)], axis=1)
    to_east, to_west = (
        np.concatenate([axis_east, zero], axis=1),
        np.concatenate([axis_west, zero], axis=1),
    )
    # A tile on the edge of the map closes at the pole with just its two side planes.
    pole = [_plane_triples(to_west, to_east, up), _plane_triples(to_west, to_east, down)]
    corners = [
        [_plane_triples(edge, side, level) for side in (to_east, to_west) for level in (up, down)]
        for edge in (to_north, to_south)
    ]
    first = np.where(
        (y == 0)[:, None, None],
        np.stack([pole[0], pole[1], pole[0], pole[1]], axis=1),
        np.stack(corners[0], axis=1),
    )
    last = np.where(
        (y == (1 << zoom) - 1)[:, None, None],
        np.stack([pole[0], pole[1], pole[0], pole[1]], axis=1),
        np.stack(corners[1], axis=1),
    )
    return np.concatenate([first, last], axis=1), np.stack(
        [up, down, to_north, to_south, to_east, to_west], axis=1
    )


def _globe_visibility(
    frustum: _Frustum, horizon: np.ndarray, points: np.ndarray, planes: np.ndarray
) -> np.ndarray:
    """isTileVisible for convex volumes against the globe frustum and its horizon: 0 outside, 1 partly, 2 inside."""
    inside = (points @ frustum.planes[:, :3].T + frustum.planes[:, 3]) >= 0
    seen = inside.sum(axis=1)
    reaches = (
        (np.einsum("nkc,pc->nkp", planes[..., :3], frustum.points) + planes[..., 3:4]) >= 0
    ).sum(axis=2)
    none = (seen == 0).any(axis=1)
    full = (seen == points.shape[1]).all(axis=1)
    in_frustum = np.where(none, 0, np.where(full, 2, np.where((reaches == 0).any(axis=1), 0, 1)))
    above = ((points @ horizon[:3] + horizon[3]) >= 0).sum(axis=1)
    on_surface = np.where(above == 0, 0, np.where(above == points.shape[1], 2, 1))
    return np.where(
        (in_frustum == 0) | (on_surface == 0),
        0,
        np.where((in_frustum == 2) & (on_surface == 2), 2, 1),
    )


def _covering(view: _View, boxes: _Boxes, layer: _Layer, lod: tuple[float, float]) -> list[_Level]:
    """coveringTiles for one source (from its min zoom up): the tiles per level, found down the quadtree."""
    centre_zoom = view.zoom + math.log2(MAP_TILE_SIZE / layer.tile_size)
    rounding = (lambda v: np.floor(v + 0.5)) if layer.round_zoom else np.floor
    zoom_at = (
        view.tile_zoom(lod, centre_zoom)
        if view.variable(max(0.0, float(rounding(centre_zoom))))
        else None
    )
    fixed = min(max(0.0, float(rounding(centre_zoom))), layer.max_zoom)
    x = y = np.zeros(1, dtype=np.int64)
    inside = np.zeros(1, dtype=bool)
    found: list[_Level] = []
    for zoom in range(layer.max_zoom + 1):
        if len(x) == 0:
            break
        low, high = boxes(zoom, x, y)
        seen = np.where(inside, 2, view.visibility(zoom, x, y, low, high))
        keep = seen > 0
        x, y, inside = x[keep], y[keep], seen[keep] == 2
        if zoom_at is None:
            wanted = np.full(len(x), fixed)
        else:
            wanted = np.minimum(
                np.maximum(rounding(zoom_at(view.distance(zoom, x, y))), 0.0), layer.max_zoom
            )
        leaf = zoom >= wanted
        if leaf.any():
            found.append((zoom, x[leaf], y[leaf]))
        x, y, inside = x[~leaf], y[~leaf], inside[~leaf]
        x, y = (
            np.repeat(2 * x, 4) + np.tile([0, 1, 0, 1], len(y)),
            np.repeat(2 * y, 4) + np.tile([0, 0, 1, 1], len(x)),
        )
        inside = np.repeat(inside, 4)
    return found


# The relief under the tiles (render/terrain.ts getMinMaxElevation) --------------------------


def _flat(view: _View, low: float = 0.0) -> _Boxes:
    """Boxes without relief: from sea level up to the culling height, as when no DEM is loaded."""
    bounds = (min(low, view.culling_elevation), max(low, view.culling_elevation))

    def boxes(_zoom: int, x: np.ndarray, _y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return np.full(len(x), bounds[0]), np.full(len(x), bounds[1])

    return boxes


# The tiles of a scene ----------------------------------------------------------------------


def _add(found: set[Tile], zoom: int, x: np.ndarray, y: np.ndarray) -> None:
    found.update(zip([zoom] * len(x), x.tolist(), y.tolist(), strict=True))


def _contour_dem(zoom: int, x: np.ndarray, y: np.ndarray, cap: int) -> _Level:
    """The DEM tiles a contour level asks for: its own (capped) and the 8 around it."""
    shift = zoom - min(zoom, cap)
    zoom, x, y = zoom - shift, x >> shift, y >> shift
    n = 1 << zoom
    around = [((x + dx) % n, y + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    nx, ny = np.concatenate([a for a, _ in around]), np.concatenate([b for _, b in around])
    inside = (ny >= 0) & (ny < n)
    return zoom, nx[inside], ny[inside]


def _request(view: _View, layers: Iterable[_Layer], frame: int, found: dict[str, set[Tile]]) -> None:
    """Add what each layer active at ``frame`` asks for at one camera."""
    boxes = _flat(view)
    covered: dict[tuple, list[_Level]] = {}
    for layer in layers:
        if not layer.active[frame]:
            continue
        lod = layer.lod or raster_lod(view.pitch)
        key = (layer.tile_size, layer.round_zoom, layer.max_zoom, lod)
        if key not in covered:
            covered[key] = _covering(view, boxes, layer, lod)
        for level, x, y in covered[key]:
            if level < layer.min_zoom:
                continue
            if layer.dem_cap is not None:
                level, x, y = _contour_dem(level, x, y, layer.dem_cap)
            _add(found[layer.source], level, x, y)
            if layer.terrain and level > 0:
                # _addTerrainIdealTiles: the parent, and the root level the visibility starts from.
                _add(found[layer.source], level - 1, x >> 1, y >> 1)
                root = min(level, TERRAIN_ROOT_ZOOM)
                _add(found[layer.source], root, x >> (level - root), y >> (level - root))


def scene_tiles(spec: dict[str, Any], *, sample_every_s: float = SAMPLE_EVERY_S) -> dict[str, set[Tile]]:
    """Tiles per source (keys of TILE_SOURCES) a serialized scene spec is expected to request."""
    cam = spec["camera"]
    profile = spec["profile"]
    size = (int(profile["width"]), int(profile["height"]))
    frames = len(cam["zoom"])
    step = max(1, round(sample_every_s * int(profile["fps"])))
    layers = _layers(spec, frames)
    found: dict[str, set[Tile]] = {layer.source: set() for layer in layers}
    globe = np.asarray(cam.get("globe", np.zeros(frames)), dtype=float) > 0

    for i in sorted({*range(0, frames, step), frames - 1}):
        camera = tuple(float(cam[key][i]) for key in ("lon", "lat", "zoom", "pitch", "bearing"))
        elevation, exaggeration = float(cam["elevation"][i]), round(float(cam["terrain"][i]), 3)
        low_zoom = camera[2] < GLOBE_MAX_ZOOM
        view = _View.at(camera, elevation, exaggeration, size, globe=low_zoom and bool(globe[i]))
        _request(view, layers, i, found)
    return found


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
