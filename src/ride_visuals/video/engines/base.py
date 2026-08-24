"""Interfaces shared by visual engine adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ride_visuals.video.spec import ActivityRenderSpec


@dataclass(frozen=True)
class EngineCapabilities:
    activity_telemetry: bool
    transparent_still: bool
    transparent_video: bool
    background_image: bool
    collection: bool
    clean_route: bool
    embedded_preview: bool
    locales: tuple[str, ...]
    themes: tuple[str, ...]


class VideoEngine(Protocol):
    name: str
    capabilities: EngineCapabilities

    def render_activity(
        self,
        spec: ActivityRenderSpec,
        output_path: Path,
        *,
        spec_path: Path,
        keyframes_dir: Path | None = None,
        composition: str = "ActivityTelemetry",
    ) -> tuple[Path, list[Path]]: ...

    def render_overlay_still(
        self,
        spec: ActivityRenderSpec,
        output_path: Path,
        *,
        spec_path: Path,
        frame: int | None = None,
    ) -> Path: ...

    def render_overlay_video(
        self,
        spec: ActivityRenderSpec,
        output_path: Path,
        *,
        spec_path: Path,
    ) -> Path: ...
