"""Versioned contract between the Python data pipeline and visual engines.

Renderers consume this JSON-safe structure instead of opening DuckDB, Parquet,
FIT or TCX themselves.
"""

from __future__ import annotations

import json
import math
import mimetypes
import shutil
import subprocess
from base64 import b64encode
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ride_visuals.design import get_theme
from ride_visuals.i18n import normalize_locale
from ride_visuals.video.telemetry import TelemetryTimeline, adaptive_speed_window_seconds

RENDER_SPEC_VERSION = "1.0"
BACKGROUND_KINDS = ("image", "video")


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float
    has_audio: bool


def probe_video(path: Path) -> VideoMetadata:
    """Return the playback metadata needed for a video background."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise RuntimeError("ffprobe was not found in PATH")
    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or "ffprobe could not read the file"
        raise ValueError(f"Could not inspect background video {path}: {detail}")
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ffprobe returned invalid metadata for background video: {path}") from exc
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError(f"Background video has no video stream: {path}")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = 0.0
    # Prefer the video-stream duration: a longer audio stream must not make a
    # short visual track appear suitable. Some containers only expose format
    # duration, so retain that as a fallback.
    for raw_duration in (video.get("duration"), info.get("format", {}).get("duration")):
        try:
            candidate = float(raw_duration)
        except (TypeError, ValueError):
            continue
        if math.isfinite(candidate) and candidate > 0.0:
            duration = candidate
            break
    if duration == 0.0:
        raise ValueError(f"Background video duration could not be determined: {path}")
    return VideoMetadata(duration_seconds=duration, has_audio=audio is not None)


@dataclass(frozen=True)
class RenderProfile:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    duration_seconds: float = 5.0
    hold_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.width < 320 or self.height < 320 or self.width % 2 or self.height % 2:
            raise ValueError("Render dimensions must be even and at least 320 px")
        if not 1 <= self.fps <= 120:
            raise ValueError("FPS must be between 1 and 120")
        if not 1.0 <= self.duration_seconds <= 3600.0:
            raise ValueError("Animation duration must be between 1 and 3600 seconds")
        if not 0.0 <= self.hold_seconds <= 60.0:
            raise ValueError("Hold duration must be between 0 and 60 seconds")


@dataclass(frozen=True)
class ActivityIdentity:
    id: str
    title: str
    date: str | None = None


@dataclass(frozen=True)
class BackgroundSpec:
    """Portable background embedded in the render contract.

    Image backgrounds carry data URLs so visual engines stay independent from
    the local filesystem and saved render specs remain portable. Video
    backgrounds keep a filesystem reference: they are too large to inline, so
    the render engine stages the file into the renderer public dir and the
    component reads it through staticFile.
    """

    src: str
    blur_px: float = 0.0
    dim: float = 0.35
    attribution: str | None = None
    attribution_bottom_px: float = 6.0
    kind: Literal["image", "video"] = "image"
    audio: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.blur_px <= 100.0:
            raise ValueError("Background blur must be between 0 and 100 px")
        if not 0.0 <= self.dim <= 1.0:
            raise ValueError("Background dim must be between 0 and 1")
        if self.attribution_bottom_px < 0.0:
            raise ValueError("Attribution position cannot be negative")
        if self.kind not in BACKGROUND_KINDS:
            raise ValueError(f"Background kind must be one of: {', '.join(BACKGROUND_KINDS)}")
        if self.kind == "image" and self.audio:
            raise ValueError("Background audio flag only applies to video backgrounds")

    @classmethod
    def from_image(
        cls,
        path: Path,
        *,
        blur_px: float = 0.0,
        dim: float = 0.35,
        attribution: str | None = None,
        attribution_bottom_px: float = 6.0,
    ) -> "BackgroundSpec":
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(f"Background image was not found: {source}")
        mime, _ = mimetypes.guess_type(source.name)
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("Background image must be JPEG, PNG or WebP")
        payload = b64encode(source.read_bytes()).decode("ascii")
        return cls(
            src=f"data:{mime};base64,{payload}",
            blur_px=blur_px,
            dim=dim,
            attribution=attribution,
            attribution_bottom_px=attribution_bottom_px,
        )

    @classmethod
    def from_video(
        cls,
        path: Path,
        *,
        blur_px: float = 0.0,
        dim: float = 0.35,
        audio: bool = True,
        required_duration: float | None = None,
    ) -> "BackgroundSpec":
        """Reference a video file that plays underneath the composition.

        Unlike images, the source stays a filesystem path: it is too large to
        inline, so the render engine stages the file into the renderer public
        dir and the component reads it through staticFile. The clip must cover
        the composition duration; the composition length is canonical, not the
        clip length.
        """
        source = Path(path).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Background video was not found: {source}")
        media = probe_video(source)
        if required_duration is not None and media.duration_seconds < required_duration - 1e-3:
            raise ValueError(
                f"Background video is {media.duration_seconds:.2f}s long but the composition "
                f"runs for {required_duration:.2f}s; use a clip that covers the animation"
            )
        return cls(
            src=str(source),
            blur_px=blur_px,
            dim=dim,
            kind="video",
            audio=audio and media.has_audio,
        )


def _json_number(value: float) -> float | None:
    return None if not math.isfinite(float(value)) else round(float(value), 6)


def _records(
    timeline: TelemetryTimeline,
    indices: Iterable[int],
    cumulative_elevation_gain_m: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index in indices:
        record = {
            "elapsedSeconds": _json_number(timeline.elapsed_s[index]),
            "lat": _json_number(timeline.lat[index]),
            "lon": _json_number(timeline.lon[index]),
            "altitudeM": _json_number(timeline.altitude_m[index]),
            "distanceKm": _json_number(timeline.distance_km[index]),
            "speedKmh": _json_number(timeline.speed_kmh[index]),
            "speed3MinKmh": _json_number(timeline.speed_3min_kmh[index]),
            "heartRateBpm": _json_number(timeline.heart_rate_bpm[index]),
            "powerWatts": _json_number(timeline.power_watts[index]),
            "temperatureC": _json_number(timeline.temperature_c[index]),
            "gradePct": _json_number(timeline.grade_pct[index]),
            "bearingDeg": _json_number(timeline.bearing_deg[index]),
        }
        if cumulative_elevation_gain_m is not None:
            record["cumulativeElevationGainM"] = _json_number(cumulative_elevation_gain_m[index])
        result.append(record)
    return result


def _sample_indices(point_count: int, max_points: int | None) -> np.ndarray:
    if max_points is None or point_count <= max_points:
        return np.arange(point_count, dtype=int)
    if max_points < 2:
        raise ValueError("max_points must be at least 2")
    return np.unique(np.linspace(0, point_count - 1, num=max_points, dtype=int))


@dataclass(frozen=True)
class ActivityRenderSpec:
    schema_version: str
    kind: str
    locale: str
    theme: str
    profile: RenderProfile
    activity: ActivityIdentity
    background: BackgroundSpec | None
    summary: dict[str, float]
    points: list[dict[str, Any]]
    presentation: str = "standard"
    output_mode: str = "animated"
    show_progress_bar: bool = False
    show_background_route: bool = True

    @classmethod
    def from_parquet(
        cls,
        parquet_path: Path,
        *,
        activity_id: str | int,
        title: str,
        activity_date: str | None = None,
        locale: str = "en",
        theme: str = "midnight",
        profile: RenderProfile | None = None,
        max_points: int | None = None,
        background_image: Path | None = None,
        background_video: Path | None = None,
        background_video_audio: bool = True,
        background_blur_px: float = 0.0,
        background_dim: float = 0.35,
        show_progress_bar: bool = False,
        show_background_route: bool = True,
        presentation: str = "standard",
    ) -> "ActivityRenderSpec":
        if background_image is not None and background_video is not None:
            raise ValueError("Use either a background image or a background video, not both")
        effective_profile = profile or RenderProfile()
        source_frame = pq.read_table(parquet_path).to_pandas()
        raw_timestamps = pd.to_datetime(source_frame["timestamp"], utc=True, errors="coerce").dropna().sort_values()
        source_duration = (
            float((raw_timestamps.iloc[-1] - raw_timestamps.iloc[0]).total_seconds())
            if len(raw_timestamps) > 1
            else 0.0
        )
        speed_window_seconds = adaptive_speed_window_seconds(
            source_duration,
            effective_profile.duration_seconds,
            effective_profile.fps,
        )
        timeline = TelemetryTimeline.from_frame(
            source_frame,
            speed_window_seconds=speed_window_seconds,
        )
        selected = _sample_indices(len(timeline), max_points)
        cumulative_elevation_gain = timeline.elevation_gain_series_m()
        normalized_locale = normalize_locale(locale)
        normalized_theme = get_theme(theme).name
        return cls(
            schema_version=RENDER_SPEC_VERSION,
            kind="activity-telemetry",
            locale=normalized_locale,
            theme=normalized_theme,
            profile=effective_profile,
            activity=ActivityIdentity(
                id=str(activity_id),
                title=title,
                date=activity_date,
            ),
            background=(
                BackgroundSpec.from_video(
                    background_video,
                    blur_px=background_blur_px,
                    dim=background_dim,
                    audio=background_video_audio,
                    required_duration=(
                        effective_profile.duration_seconds + effective_profile.hold_seconds
                    ),
                )
                if background_video is not None
                else (
                    BackgroundSpec.from_image(
                        background_image,
                        blur_px=background_blur_px,
                        dim=background_dim,
                    )
                    if background_image is not None
                    else None
                )
            ),
            summary={
                "distanceKm": round(timeline.total_distance_km, 3),
                "elevationGainM": round(timeline.elevation_gain_m, 1),
                "sourceDurationSeconds": round(timeline.duration_s, 3),
                "sourcePointCount": float(len(timeline)),
                "renderPointCount": float(len(selected)),
                "speedWindowSeconds": float(speed_window_seconds),
                "maximumGradePct": round(timeline.maximum_grade_pct, 1),
            },
            points=_records(timeline, selected, cumulative_elevation_gain),
            presentation=presentation,
            show_progress_bar=show_progress_bar,
            show_background_route=show_background_route,
        )

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        return {
            "schemaVersion": raw.pop("schema_version"),
            "outputMode": raw.pop("output_mode"),
            **raw,
        }

    def write(self, path: Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return destination
