"""Adapter for the React/Remotion visual framework."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from ride_visuals.validate.media_validator import MediaValidator
from ride_visuals.video.engines.base import EngineCapabilities
from ride_visuals.video.instagram import (
    INSTAGRAM_STORY_LANDSCAPE,
    ffmpeg_filter,
    present_frame,
)
from ride_visuals.video.spec import ActivityRenderSpec, BackgroundSpec

if TYPE_CHECKING:
    from ride_visuals.scene3d.spec import SceneSpec


def _resolve_renderer_dir(renderer_dir: Path | None = None) -> Path:
    if renderer_dir is not None:
        return Path(renderer_dir).resolve()
    env_dir = os.environ.get("RIDE_VISUALS_RENDERER_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    cwd_candidate = Path.cwd() / "renderer"
    if (cwd_candidate / "src" / "index.ts").exists():
        return cwd_candidate.resolve()
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "renderer"
        if (candidate / "src" / "index.ts").exists():
            return candidate.resolve()
    return (Path(__file__).resolve().parents[4] / "renderer").resolve()


def stage_background_video(
    spec: ActivityRenderSpec,
    renderer_dir: Path,
) -> ActivityRenderSpec:
    """Copy a video background into the renderer public dir for staticFile.

    The staged copy is content-addressed so repeated renders reuse the same
    file. The returned spec references the copy relative to the public dir,
    which is what the saved render spec records.
    """
    background = spec.background
    if background is None or background.kind != "video":
        return spec
    source = Path(background.src)
    if not source.is_absolute() and (renderer_dir / "public" / background.src).is_file():
        # Already staged by a previous pass; keep the public-relative reference.
        return spec
    if not source.is_file():
        raise FileNotFoundError(f"Background video was not found: {source}")
    suffix = source.suffix.lower() or ".mp4"
    staging_dir = renderer_dir / "public" / "backgrounds"
    staging_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=staging_dir,
        prefix=".background-",
        suffix=".part",
    )
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "wb") as staged_file, source.open("rb") as source_file:
            while chunk := source_file.read(1024 * 1024):
                digest.update(chunk)
                staged_file.write(chunk)
        staged_name = f"{digest.hexdigest()[:16]}{suffix}"
        staged = staging_dir / staged_name
        if staged.exists():
            temporary.unlink()
        else:
            os.replace(temporary, staged)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"[Background] Background video prepared: backgrounds/{staged_name}")
    return replace(spec, background=replace(background, src=f"backgrounds/{staged_name}"))


def background_video_source(
    background: BackgroundSpec | None,
    renderer_dir: Path,
) -> Path | None:
    """Resolve a staged video background back to an absolute filesystem path."""
    if background is None or background.kind != "video":
        return None
    candidate = Path(background.src)
    return candidate if candidate.is_absolute() else renderer_dir / "public" / candidate


def media_normalization_command(
    ffmpeg: str,
    video_only: Path,
    output: Path,
    spec: ActivityRenderSpec,
    background_video: Path | None,
) -> list[str]:
    """Build the final video/audio normalization command."""
    keep_background_audio = (
        background_video is not None
        and spec.background is not None
        and spec.background.kind == "video"
        and spec.background.audio
    )
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_only),
    ]
    if keep_background_audio:
        command.extend(["-i", str(background_video)])
    command.extend(["-map", "0:v:0"])
    if keep_background_audio:
        total_frames = round(
            (spec.profile.duration_seconds + spec.profile.hold_seconds) * spec.profile.fps
        )
        total_seconds = total_frames / spec.profile.fps
        command.extend(
            [
                "-map",
                "1:a:0",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-af",
                (
                    f"atrim=duration={total_seconds:.6f},"
                    f"asetpts=PTS-STARTPTS,apad=whole_dur={total_seconds:.6f}"
                ),
                "-shortest",
            ]
        )
    else:
        command.append("-an")
    if spec.presentation == INSTAGRAM_STORY_LANDSCAPE or (
        spec.profile.width == 1080 and spec.profile.height == 1920
    ):
        if spec.presentation == INSTAGRAM_STORY_LANDSCAPE:
            command.extend(["-vf", ffmpeg_filter()])
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-profile:v",
                "high",
                "-level:v",
                "4.2",
                "-g",
                str(max(2, 2 * spec.profile.fps)),
                "-keyint_min",
                str(spec.profile.fps),
                "-sc_threshold",
                "0",
                "-bf",
                "2",
                "-colorspace",
                "bt709",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
            ]
        )
    else:
        command.extend(["-c:v", "copy"])
    command.extend(["-movflags", "+faststart", str(output)])
    return command


#: 3D scenes open and close on a black curtain; sample the inspection keyframes
#: just inside it, so a frame is never a fully black fade.
KEYFRAME_START_INSET_S = 0.9
KEYFRAME_END_INSET_S = 1.2


def keyframe_timestamps(
    total_seconds: float,
    fps: int,
    *,
    start_inset_s: float = 0.0,
    end_inset_s: float = 0.0,
) -> tuple[float, float, float]:
    """0/50/100% sample times, optionally inset from the ends.

    Insets keep inspection frames off a fade. They are clamped so the three
    samples stay ordered and inside the video even for very short clips; with
    no inset this reproduces the historical 0 / mid / last-frame sampling.
    """
    frame_s = 1.0 / max(fps, 1)
    last = max(total_seconds - frame_s, 0.0)
    mid = total_seconds * 0.5
    start = min(max(start_inset_s, 0.0), max(mid - frame_s, 0.0))
    end = max(min(max(total_seconds - end_inset_s, mid + frame_s), last), mid + frame_s)
    return (start, mid, end)


#: 3D scenes are rendered in chunks of this many seconds of video: a failure
#: or a stop only loses the chunk in progress (see render_scene3d).
SCENE3D_CHUNK_S = 15.0


def scene3d_chunks(frames: int, chunk_frames: int) -> list[tuple[int, int]]:
    """Inclusive (first, last) frame ranges covering ``frames``; no tail shorter than half a chunk."""
    chunk_frames = max(1, chunk_frames)
    count = max(1, round(frames / chunk_frames))
    bounds = [round(i * frames / count) for i in range(count + 1)]
    return [(bounds[i], bounds[i + 1] - 1) for i in range(count) if bounds[i + 1] > bounds[i]]


class RemotionVideoEngine:
    name = "remotion"
    capabilities = EngineCapabilities(
        activity_telemetry=True,
        transparent_still=True,
        transparent_video=True,
        background_image=True,
        background_video=True,
        collection=False,
        clean_route=True,
        embedded_preview=True,
        locales=("en", "pt-BR"),
        themes=("midnight", "frost"),
    )

    def __init__(self, renderer_dir: Path | None = None) -> None:
        self.renderer_dir = _resolve_renderer_dir(renderer_dir)
        self.entrypoint = self.renderer_dir / "src" / "index.ts"
        self.cli = self.renderer_dir / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        self.node = shutil.which("node")
        self.ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
        self.browser_executable = self._find_browser_executable()

    @staticmethod
    def _find_browser_executable() -> Path | None:
        candidates = sorted(
            Path.home().glob(
                ".cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-*/chrome-headless-shell"
            ),
            reverse=True,
        )
        return candidates[0] if candidates else None

    def doctor(self) -> list[str]:
        errors: list[str] = []
        if not self.node:
            errors.append("Node.js was not found in PATH")
        if not self.entrypoint.exists():
            errors.append(
                f"Remotion entrypoint was not found: {self.entrypoint}. "
                "Ensure you run from the repository root or set RIDE_VISUALS_RENDERER_DIR."
            )
        if not self.cli.exists():
            errors.append(
                f"Remotion dependencies are missing. Run: npm --prefix '{self.renderer_dir}' ci --no-bin-links"
            )
        return errors

    def render_activity(
        self,
        spec: ActivityRenderSpec,
        output_path: Path,
        *,
        spec_path: Path,
        keyframes_dir: Path | None = None,
        composition: str = "ActivityTelemetry",
    ) -> tuple[Path, list[Path]]:
        errors = self.doctor()
        if errors:
            raise RuntimeError("; ".join(errors))

        output = Path(output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        if composition not in {"ActivityTelemetry", "ActivityClean", "ActivityMinimal"}:
            raise ValueError(f"Unsupported activity composition: {composition}")
        spec = stage_background_video(spec, self.renderer_dir)
        serialized_spec = spec.write(spec_path).resolve()
        video_only = output.with_name(f".{output.stem}.remotion.mp4")
        assert self.node is not None

        render_command = self._remotion_command(
            "render",
            composition,
            video_only,
            str(serialized_spec),
            "--codec",
            "h264",
            "--pixel-format",
            "yuv420p",
            "--color-space",
            "bt709",
            "--concurrency",
            "2",
        )
        try:
            self._run(render_command, "Remotion render", retries=1)

            background_video = background_video_source(spec.background, self.renderer_dir)
            mux_command = media_normalization_command(
                self.ffmpeg,
                video_only,
                output,
                spec,
                background_video,
            )
            self._run(mux_command, "media normalization")
        finally:
            video_only.unlink(missing_ok=True)

        validation = MediaValidator.validate_video(output)
        if not validation.get("valid") or validation.get("has_faststart") is not True:
            raise RuntimeError(f"Rendered video failed validation: {validation}")

        keyframes = self._extract_keyframes(output, spec, keyframes_dir)
        return output, keyframes

    def render_overlay_still(
        self,
        spec: ActivityRenderSpec,
        output_path: Path,
        *,
        spec_path: Path,
        frame: int | None = None,
        composition: str = "ActivityOverlay",
    ) -> Path:
        """Render a reusable RGBA PNG overlay at a chosen animation frame."""
        self._validate_overlay_composition(composition)
        output = Path(output_path).resolve()
        if output.suffix.lower() != ".png":
            raise ValueError("Transparent still output must use the .png extension")
        errors = self.doctor()
        if errors:
            raise RuntimeError("; ".join(errors))
        output.parent.mkdir(parents=True, exist_ok=True)
        render_spec = replace(spec, output_mode="static-summary") if frame is None else spec
        serialized_spec = render_spec.write(spec_path).resolve()
        total_frames = round(
            (spec.profile.duration_seconds + spec.profile.hold_seconds) * spec.profile.fps
        )
        # A reusable static overlay represents the completed activity. Callers
        # may still request an explicit frame for video/keyframe inspection.
        selected_frame = frame if frame is not None else max(0, total_frames - 1)
        command = self._remotion_command(
            "still",
            composition,
            output,
            str(serialized_spec),
            "--frame",
            str(selected_frame),
            "--image-format",
            "png",
        )
        self._run(command, "transparent overlay still", retries=1)
        if spec.presentation == INSTAGRAM_STORY_LANDSCAPE:
            with Image.open(output) as rendered:
                story_frame = present_frame(
                    rendered.convert("RGBA"),
                    presentation=spec.presentation,
                )
            story_frame.save(output)
        validation = MediaValidator.validate_transparent_still(output)
        if not validation.get("valid"):
            raise RuntimeError(f"Overlay PNG failed validation: {validation}")
        return output

    def render_overlay_video(
        self,
        spec: ActivityRenderSpec,
        output_path: Path,
        *,
        spec_path: Path,
        composition: str = "ActivityOverlay",
    ) -> Path:
        """Render an animated alpha overlay as WebM or ProRes 4444 MOV.

        MP4/H.264 is intentionally excluded because it cannot carry the alpha
        channel required by reusable overlays.
        """
        output = Path(output_path).resolve()
        self._validate_overlay_composition(composition)
        suffix = output.suffix.lower()
        if suffix == ".webm":
            codec_args = ["--codec", "vp9", "--pixel-format", "yuva420p"]
        elif suffix == ".mov":
            codec_args = [
                "--codec",
                "prores",
                "--prores-profile",
                "4444",
                "--pixel-format",
                "yuva444p10le",
            ]
        else:
            raise ValueError("Transparent video output must use .webm or .mov")
        errors = self.doctor()
        if errors:
            raise RuntimeError("; ".join(errors))
        output.parent.mkdir(parents=True, exist_ok=True)
        serialized_spec = spec.write(spec_path).resolve()
        remotion_output = (
            output.with_name(f".{output.stem}.remotion{output.suffix}")
            if spec.presentation == INSTAGRAM_STORY_LANDSCAPE
            else output
        )
        command = self._remotion_command(
            "render",
            composition,
            remotion_output,
            str(serialized_spec),
            "--image-format",
            "png",
            "--muted",
            "--concurrency",
            "1",
            *codec_args,
        )
        self._run(command, "transparent overlay video", retries=1)
        if spec.presentation == INSTAGRAM_STORY_LANDSCAPE:
            if suffix == ".webm":
                transform_codec_args = [
                    "-c:v",
                    "libvpx-vp9",
                    "-pix_fmt",
                    "yuva420p",
                    "-auto-alt-ref",
                    "0",
                ]
                input_codec_args = ["-c:v", "libvpx-vp9"]
            else:
                transform_codec_args = [
                    "-c:v",
                    "prores_ks",
                    "-profile:v",
                    "4",
                    "-pix_fmt",
                    "yuva444p10le",
                ]
                input_codec_args = []
            transform_command = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                *input_codec_args,
                "-i",
                str(remotion_output),
                "-vf",
                ffmpeg_filter(transparent=True),
                *transform_codec_args,
                "-an",
                str(output),
            ]
            self._run(transform_command, "Instagram transparent presentation")
            remotion_output.unlink(missing_ok=True)
        if not output.exists() or output.stat().st_size < 1024:
            raise RuntimeError(f"Transparent video render is invalid: {output}")
        validation = MediaValidator.validate_transparent_video(output)
        if not validation.get("valid"):
            raise RuntimeError(f"Transparent video failed validation: {validation}")
        return output

    def render_scene3d(
        self,
        spec: SceneSpec,
        output_path: Path,
        *,
        spec_url: str,
        scale: int = 1,
        keyframes_dir: Path | None = None,
        concurrency: int = 2,
        chunk_seconds: float = SCENE3D_CHUNK_S,
    ) -> tuple[Path, list[Path]]:
        """Render the ``Scene3D`` composition served by a local ``TileServer``.

        The video is rendered in chunks of ``chunk_seconds`` from one prebuilt
        bundle and joined without re-encoding. Finished chunks are kept next to
        the output until the whole video is valid, so a crash or a stop costs
        only the chunk in progress: running the same command again resumes.
        A chunk is reused only for the very same spec and render settings.
        """
        from ride_visuals.scene3d.tiles import stage_scene3d_assets

        errors = self.doctor()
        if errors:
            raise RuntimeError("; ".join(errors))
        stage_scene3d_assets(self.renderer_dir)

        output = Path(output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        props_json = json.dumps(
            {
                "specUrl": spec_url,
                "width": spec.width,
                "height": spec.height,
                "fps": spec.fps,
                "durationInFrames": spec.frames,
            },
            separators=(",", ":"),
        )
        render_options = [
            "--gl",
            "angle",
            # Lossless frame capture: JPEG lifts the near-black land and
            # makes the fine relief shading shimmer from frame to frame.
            "--image-format",
            "png",
            "--codec",
            "h264",
            # Fine contour and hillshade texture on near-black needs more bits
            # than flat graphics, or it pulses with the encoder's frame types.
            "--crf",
            "15",
            "--pixel-format",
            "yuv420p",
            "--color-space",
            "bt709",
            "--concurrency",
            str(concurrency),
            *(["--scale", str(scale)] if scale > 1 else []),
        ]
        # The spec URL changes with the server port on every run: key the
        # chunks by the spec's content and the settings that change pixels.
        digest = hashlib.sha256(
            json.dumps([spec.to_json(), render_options], separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        parts_dir = output.with_name(f".{output.stem}.parts")
        chunks_dir = parts_dir / digest
        for stale in parts_dir.glob("*"):
            if stale != chunks_dir:
                shutil.rmtree(stale, ignore_errors=True)
        chunks_dir.mkdir(parents=True, exist_ok=True)
        ranges = scene3d_chunks(spec.frames, max(1, round(chunk_seconds * spec.fps)))

        bundle = chunks_dir / "bundle"
        shutil.rmtree(bundle, ignore_errors=True)
        self._run(
            [self.node or "node", str(self.cli), "bundle", str(self.entrypoint), "--out-dir", str(bundle), "--log", "error"],
            "Remotion bundle",
        )
        chunk_files: list[Path] = []
        try:
            for index, (first, last) in enumerate(ranges):
                chunk = chunks_dir / f"chunk_{index:04d}.mp4"
                chunk_files.append(chunk)
                if chunk.exists():
                    print(f"[Scene3D] Chunk {index + 1}/{len(ranges)} already rendered, reusing it.")
                    continue
                print(f"[Scene3D] Rendering chunk {index + 1}/{len(ranges)} (frames {first}-{last})...")
                partial = chunk.with_name(f"{chunk.stem}.partial.mp4")
                command = self._remotion_command(
                    "render",
                    "Scene3D",
                    partial,
                    props_json,
                    *render_options,
                    f"--frames={first}-{last}",
                    source=bundle,
                )
                self._run(command, f"Remotion 3D scene chunk {index + 1}/{len(ranges)}", retries=1)
                partial.replace(chunk)
        finally:
            shutil.rmtree(bundle, ignore_errors=True)

        concat_list = chunks_dir / "chunks.txt"
        concat_list.write_text("".join(f"file '{path.name}'\n" for path in chunk_files), encoding="utf-8")
        self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ],
            "3D scene chunk join",
        )

        total_seconds = spec.frames / spec.fps
        validation = MediaValidator.validate_video(output, expected_duration_s=total_seconds)
        if not validation.get("valid") or validation.get("has_faststart") is not True:
            raise RuntimeError(
                f"Rendered 3D video failed validation: {validation} (chunks kept in {chunks_dir})"
            )
        shutil.rmtree(parts_dir, ignore_errors=True)

        keyframes = self._extract_keyframes_by_duration(
            output,
            total_seconds,
            spec.fps,
            keyframes_dir,
            start_inset_s=KEYFRAME_START_INSET_S,
            end_inset_s=KEYFRAME_END_INSET_S,
        )
        return output, keyframes

    @staticmethod
    def _validate_overlay_composition(composition: str) -> None:
        if composition not in {
            "ActivityOverlay",
            "RouteOverlay",
            "StatsOverlay",
            "ActivityMinimalOverlay",
        }:
            raise ValueError(f"Unsupported overlay composition: {composition}")

    def _remotion_command(
        self,
        action: str,
        composition: str,
        output: Path,
        props: str,
        *options: str,
        source: Path | None = None,
    ) -> list[str]:
        """``remotion <action>`` with the flags every render here shares.

        ``source`` is the entrypoint by default, or a prebuilt bundle directory.
        """
        return [
            self.node or "node",
            str(self.cli),
            action,
            str(source or self.entrypoint),
            composition,
            str(Path(output).resolve()),
            "--props",
            props,
            "--timeout",
            "120000",
            "--overwrite",
            "--log",
            "error",
            *options,
            *self._browser_args(),
        ]

    def _browser_args(self) -> list[str]:
        if self.browser_executable is None:
            return []
        return ["--browser-executable", str(self.browser_executable)]

    def _extract_keyframes(
        self,
        video: Path,
        spec: ActivityRenderSpec,
        destination: Path | None,
    ) -> list[Path]:
        total = spec.profile.duration_seconds + spec.profile.hold_seconds
        return self._extract_keyframes_by_duration(video, total, spec.profile.fps, destination)

    def _extract_keyframes_by_duration(
        self,
        video: Path,
        total_seconds: float,
        fps: int,
        destination: Path | None,
        *,
        start_inset_s: float = 0.0,
        end_inset_s: float = 0.0,
    ) -> list[Path]:
        if destination is None:
            return []
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        times = keyframe_timestamps(
            total_seconds, fps, start_inset_s=start_inset_s, end_inset_s=end_inset_s
        )
        paths: list[Path] = []
        for label, timestamp in zip(("00", "50", "100"), times, strict=True):
            frame = destination / f"keyframe_{label}pct.png"
            command = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{timestamp:.6f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                str(frame),
            ]
            self._run(command, f"keyframe {label}%")
            paths.append(frame)
        return paths

    def _run(self, command: list[str], operation: str, *, retries: int = 0) -> None:
        # Do not capture pipes here: Chrome spawns descendants that may keep a
        # pipe descriptor open after the CLI exits, causing an otherwise
        # completed render to wait forever in communicate().
        for attempt in range(retries + 1):
            result = subprocess.run(command, cwd=self.renderer_dir)
            if result.returncode == 0:
                return
            if attempt < retries:
                print(
                    f"[Remotion] {operation} failed; retrying once with the same stable profile..."
                )
        raise RuntimeError(f"{operation} failed with exit code {result.returncode}")
