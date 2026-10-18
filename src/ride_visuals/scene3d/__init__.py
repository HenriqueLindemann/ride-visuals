"""3D cartographic and terrain scenes (flyover, stretch, strata)."""

from __future__ import annotations

from ride_visuals.scene3d.flyover import FlyoverMetadata, build_flyover_spec
from ride_visuals.scene3d.spec import Look, SceneKind, SceneSpec
from ride_visuals.scene3d.strata import PeriodMode, StrataBuildResult, build_strata_spec
from ride_visuals.scene3d.stretch import SceneRide, build_stretch_spec
from ride_visuals.scene3d.terrain import DemSampler, decode_terrarium
from ride_visuals.scene3d.tiles import (
    TILE_SOURCES,
    TileCache,
    TileServer,
    TileSource,
    stage_scene3d_assets,
)
from ride_visuals.scene3d.track import RideTrack

__all__ = [
    "DemSampler",
    "FlyoverMetadata",
    "Look",
    "PeriodMode",
    "RideTrack",
    "SceneKind",
    "SceneRide",
    "SceneSpec",
    "StrataBuildResult",
    "TILE_SOURCES",
    "TileCache",
    "TileServer",
    "TileSource",
    "build_flyover_spec",
    "build_strata_spec",
    "build_stretch_spec",
    "decode_terrarium",
    "stage_scene3d_assets",
]
