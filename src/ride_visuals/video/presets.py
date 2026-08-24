"""Canonical render dimensions and durations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanvasPreset:
    aspect: str
    width: int
    height: int
    layout: str


@dataclass(frozen=True)
class VideoPreset:
    canvas: CanvasPreset
    fps: int
    duration_seconds: float
    hold_seconds: float


CANVASES = {
    "16:9": CanvasPreset("16:9", 1920, 1080, "16:9"),
    "9:16": CanvasPreset("9:16", 1080, 1920, "9:16"),
    "4k": CanvasPreset("4k", 3840, 2160, "16:9"),
}

_DURATIONS = {
    "activity": {"preview": (4.0, 1.0), "final": (13.0, 2.0)},
    "collection": {"preview": (4.0, 1.0), "final": (12.0, 3.0)},
    "timeline": {"preview": (5.0, 1.0), "final": (13.0, 2.0)},
    # Eight chapters stay below the ten-second preview limit.
    "progress": {"preview": (0.8, 0.0), "final": (1.875, 0.0)},
}


def get_video_preset(kind: str, aspect: str, *, preview: bool = False, clean: bool = False) -> VideoPreset:
    """Resolve a named output to deterministic dimensions and timing."""
    try:
        canvas = CANVASES[aspect]
    except KeyError as exc:
        raise ValueError(f"Unsupported aspect {aspect!r}. Choose one of: {', '.join(CANVASES)}") from exc
    try:
        duration, hold = _DURATIONS[kind]["preview" if preview else "final"]
    except KeyError as exc:
        raise ValueError(f"Unsupported video preset {kind!r}") from exc
    if clean:
        canvas = CanvasPreset(canvas.aspect, canvas.width, canvas.height, "clean")
    return VideoPreset(canvas=canvas, fps=30, duration_seconds=duration, hold_seconds=hold)
