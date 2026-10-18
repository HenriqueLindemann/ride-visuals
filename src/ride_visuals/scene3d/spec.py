"""The JSON contract read by ``renderer/src/scene3d`` (schema.ts mirrors it)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from ride_visuals.credits import on_screen_line
from ride_visuals.scene3d.camera import CameraTrack
from ride_visuals.scene3d.tiles import TILE_SOURCES

SCENE_SPEC_VERSION = "1.0"
SceneKind = Literal["flyover", "stretch", "strata"]
Look = Literal["carbon", "satellite"]


def tile_paths(look: Look) -> dict[str, Any]:
    """Tile URL paths, relative to the server that serves the spec itself."""
    def path(key: str) -> str:
        return f"/tiles/{key}/{{z}}/{{x}}/{{y}}.{TILE_SOURCES[key].ext}"

    return {
        "dem": path("dem"),
        "vector": path("vector"),
        "satellite": path("satellite") if look == "satellite" else None,
        "demMaxZoom": TILE_SOURCES["dem"].max_zoom,
        "vectorMaxZoom": TILE_SOURCES["vector"].max_zoom,
        "satelliteMaxZoom": TILE_SOURCES["satellite"].max_zoom,
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
            "tiles": tile_paths(self.look),
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
