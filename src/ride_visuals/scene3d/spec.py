"""The JSON contract read by ``renderer/src/scene3d`` (schema.ts mirrors it)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from ride_visuals.credits import on_screen_line
from ride_visuals.scene3d.camera import CameraTrack, meters_per_pixel
from ride_visuals.scene3d.tiles import TILE_SOURCES

SCENE_SPEC_VERSION = "1.0"
SceneKind = Literal["flyover", "stretch", "strata", "territory", "ascent"]
Look = Literal["carbon", "satellite"]


#: Share of the relief frames allowed below the level a scene's land is locked to.
RELIEF_ZOOM_PERCENTILE = 10.0
#: DEM tiles are declared 128 px in style.ts: MapLibre loads them two levels
#: above the map zoom (one for 256 px).
DEM_LEVELS_ABOVE_MAP_ZOOM = 2
#: Contour intervals (minor, major, m). A scene takes the widest whose minor
#: line is at most CONTOUR_PX ground pixels at its widest typical view.
CONTOUR_INTERVALS = ((10, 50), (20, 100), (25, 100), (50, 200), (100, 500), (200, 1000), (500, 2500))
CONTOUR_PX = 2.0


@dataclass(frozen=True)
class ReliefLock:
    """Tile levels a scene's land is drawn from, and its contour interval.

    MapLibre picks tile levels from the camera zoom, so every whole level the
    camera crosses would swap the detail of the land (relief, contours,
    fields). Capping the levels just above where the camera spends nearly all
    of its relief frames makes everything closer an overzoom of the same
    tiles: the land keeps one look while the camera moves in and out.
    """

    #: DEM tiles (relief mesh and shading), DEM_LEVELS_ABOVE_MAP_ZOOM above the land's.
    dem: int
    #: Land and contour tiles (512 px, at the map zoom).
    land: int
    contours: tuple[int, int]


def relief_lock(camera: CameraTrack) -> ReliefLock:
    """The levels and contour interval for the frames where the land reads as relief."""
    dem_max, land_max = TILE_SOURCES["dem"].max_zoom, TILE_SOURCES["vector"].max_zoom
    relief = (np.maximum(camera.terrain, camera.contours) > 0.01) & (camera.map_opacity > 0.5)
    if not relief.any():
        return ReliefLock(dem_max, land_max, CONTOUR_INTERVALS[2])
    low = float(np.percentile(camera.zoom[relief], RELIEF_ZOOM_PERCENTILE))
    base = int(max(0, np.floor(low)))
    ground_px = float(meters_per_pixel(low, float(np.median(camera.lat[relief]))))
    contours = max((pair for pair in CONTOUR_INTERVALS if pair[0] <= CONTOUR_PX * ground_px), default=CONTOUR_INTERVALS[0])
    return ReliefLock(min(dem_max, base + DEM_LEVELS_ABOVE_MAP_ZOOM), min(land_max, base), contours)


def tile_paths(look: Look, lock: ReliefLock | None = None) -> dict[str, Any]:
    """Tile URL paths, relative to the server that serves the spec itself."""
    def path(key: str) -> str:
        return f"/tiles/{key}/{{z}}/{{x}}/{{y}}.{TILE_SOURCES[key].ext}"

    lock = lock or ReliefLock(TILE_SOURCES["dem"].max_zoom, TILE_SOURCES["vector"].max_zoom, CONTOUR_INTERVALS[2])
    return {
        "dem": path("dem"),
        "vector": path("vector"),
        "satellite": path("satellite") if look == "satellite" else None,
        "demMaxZoom": lock.dem,
        "landMaxZoom": lock.land,
        "vectorMaxZoom": TILE_SOURCES["vector"].max_zoom,
        "satelliteMaxZoom": TILE_SOURCES["satellite"].max_zoom,
        "contours": list(lock.contours),
    }


def tile_credits(look: Look) -> tuple[str, ...]:
    """Credited sources (keys of ``ride_visuals.credits.SOURCES``) behind a look's tiles."""
    keys = [*TILE_SOURCES["dem"].credits, *TILE_SOURCES["vector"].credits]
    if look == "satellite":
        keys.extend(TILE_SOURCES["satellite"].credits)
    return tuple(keys)


def _series(values: np.ndarray, decimals: int) -> list[float]:
    array = np.asarray(values, dtype=float)
    if not np.isfinite(array).all():
        raise ValueError("Scene series contain non-finite values")
    return np.round(array, decimals).tolist()


@dataclass
class SceneSpec:
    """Everything the player needs: camera and channels per frame, geometry, story."""

    kind: SceneKind
    locale: str
    look: Look
    width: int
    height: int
    fps: int
    camera: CameraTrack
    channels: dict[str, np.ndarray] = field(default_factory=dict)
    tracks: list[dict[str, list[int]]] = field(default_factory=list)
    story: dict[str, Any] = field(default_factory=dict)
    #: Draw the short data credit on screen (the sidecar file is always written).
    credits_on_screen: bool = False
    #: Credited data sources beyond the map tiles (e.g. a gazetteer).
    extra_sources: tuple[str, ...] = ()

    @property
    def frames(self) -> int:
        return self.camera.frames

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys([*tile_credits(self.look), *self.extra_sources]))

    @property
    def credits(self) -> str | None:
        return on_screen_line(self.sources) if self.credits_on_screen else None

    def validate(self) -> None:
        for name, values in self.channels.items():
            if len(values) != self.frames:
                raise ValueError(f"Channel {name!r} has {len(values)} values for {self.frames} frames")

    def to_json(self) -> dict[str, Any]:
        self.validate()
        cam = self.camera
        return {
            "schemaVersion": SCENE_SPEC_VERSION,
            "kind": self.kind,
            "locale": self.locale,
            "look": self.look,
            "profile": {
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
                "durationInFrames": self.frames,
            },
            "tiles": tile_paths(self.look, relief_lock(cam)),
            "credits": self.credits,
            "camera": {
                "lon": _series(cam.lon, 7),
                "lat": _series(cam.lat, 7),
                "zoom": _series(cam.zoom, 4),
                "pitch": _series(cam.pitch, 3),
                "bearing": _series(cam.bearing, 3),
                "elevation": _series(cam.elevation, 1),
                "terrain": _series(cam.terrain, 4),
                "globe": _series(cam.globe, 0),
                "mapOpacity": _series(cam.map_opacity, 4),
                "contours": _series(cam.contours, 3),
                "satellite": _series(cam.satellite, 3),
                "shade": _series(cam.shade, 3),
                "buildings": _series(cam.buildings, 3),
            },
            "channels": {name: _series(values, 4) for name, values in self.channels.items()},
            "tracks": self.tracks,
            "story": self.story,
        }

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return path
