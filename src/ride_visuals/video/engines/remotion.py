"""Adapter for the React/Remotion visual framework."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from PIL import Image

from ride_visuals.validate.media_validator import MediaValidator
from ride_visuals.video.engines.base import EngineCapabilities
from ride_visuals.video.instagram import (
    INSTAGRAM_STORY_LANDSCAPE,
    ffmpeg_filter,
    present_frame,
)
from ride_visuals.video.spec import ActivityRenderSpec


def _resolve_renderer_dir(renderer_dir: Path | None = None) -> Path:
    if renderer_dir is not None:
        return Path(renderer_dir)
    env_dir = os.environ.get("RIDE_VISUALS_RENDERER_DIR")
    if env_dir:
        return Path(env_dir)
    cwd_candidate = Path.cwd() / "renderer"
    if (cwd_candidate / "src" / "index.ts").exists():
        return cwd_candidate
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "renderer"
        if (candidate / "src" / "index.ts").exists():
            return candidate
    return Path(__file__).resolve().parents[4] / "renderer"


class RemotionVideoEngine:
    name = "remotion"
    capabilities = EngineCapabilities(
        activity_telemetry=True,
        transparent_still=True,
        transparent_video=True,
        background_image=True,
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
        if composition not in {"ActivityTelemetry", "ActivityClean"}:
            raise ValueError(f"Unsupported activity composition: {composition}")
        serialized_spec = spec.write(spec_path).resolve()
        video_only = output.with_name(f".{output.stem}.remotion.mp4")
        assert self.node is not None

        render_command = [
            self.node,
            str(self.cli),
            "render",
            str(self.entrypoint),
            composition,
            str(video_only.resolve()),
            "--props",
            str(serialized_spec),
            "--codec",
            "h264",
            "--pixel-format",
            "yuv420p",
            "--color-space",
            "bt709",
            "--concurrency",
            "2",
            "--timeout",
            "120000",
            "--overwrite",
            "--log",
            "error",
        ]
        if self.browser_executable:
            render_command.extend(["--browser-executable", str(self.browser_executable)])
        self._run(render_command, "Remotion render", retries=1)

        mux_command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_only),
            "-map",
            "0:v:0",
            "-an",
        ]
        if spec.presentation == INSTAGRAM_STORY_LANDSCAPE:
            mux_command.extend(
                [
                    "-vf",
                    ffmpeg_filter(),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                ]
            )
        else:
            mux_command.extend(["-c:v", "copy"])
        mux_command.extend(
            [
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        self._run(mux_command, "media normalization")
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
    ) -> Path:
        """Render a reusable RGBA PNG overlay at a chosen animation frame."""
        errors = self.doctor()
        if errors:
            raise RuntimeError("; ".join(errors))
        output = Path(output_path).resolve()
        if output.suffix.lower() != ".png":
            raise ValueError("Transparent still output must use the .png extension")
        output.parent.mkdir(parents=True, exist_ok=True)
        render_spec = replace(spec, output_mode="static-summary") if frame is None else spec
        serialized_spec = render_spec.write(spec_path).resolve()
        total_frames = round(
            (spec.profile.duration_seconds + spec.profile.hold_seconds) * spec.profile.fps
        )
        # A reusable static overlay represents the completed activity. Callers
        # may still request an explicit frame for video/keyframe inspection.
        selected_frame = frame if frame is not None else max(0, total_frames - 1)
        command = [
            self.node or "node",
            str(self.cli),
            "still",
            str(self.entrypoint),
            "ActivityOverlay",
            str(output.resolve()),
            "--props",
            str(serialized_spec),
            "--frame",
            str(selected_frame),
            "--image-format",
            "png",
            "--timeout",
            "120000",
            "--overwrite",
            "--log",
            "error",
            *self._browser_args(),
        ]
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
    ) -> Path:
        """Render an animated alpha overlay as WebM or ProRes 4444 MOV.

        MP4/H.264 is intentionally excluded because it cannot carry the alpha
        channel required by reusable overlays.
        """
        errors = self.doctor()
        if errors:
            raise RuntimeError("; ".join(errors))
        output = Path(output_path).resolve()
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
        output.parent.mkdir(parents=True, exist_ok=True)
        serialized_spec = spec.write(spec_path).resolve()
        remotion_output = (
            output.with_name(f".{output.stem}.remotion{output.suffix}")
            if spec.presentation == INSTAGRAM_STORY_LANDSCAPE
            else output
        )
        command = [
            self.node or "node",
            str(self.cli),
            "render",
            str(self.entrypoint),
            "ActivityOverlay",
            str(remotion_output.resolve()),
            "--props",
            str(serialized_spec),
            "--image-format",
            "png",
            "--muted",
            "--concurrency",
            "1",
            "--timeout",
            "120000",
            "--overwrite",
            "--log",
            "error",
            *codec_args,
            *self._browser_args(),
        ]
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
        if destination is None:
            return []
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        total = spec.profile.duration_seconds + spec.profile.hold_seconds
        times = (0.0, total * 0.5, max(0.0, total - 1.0 / spec.profile.fps))
        paths: list[Path] = []
        for label, timestamp in zip(("00", "50", "100"), times):
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
                print(f"[Remotion] {operation} falhou; repetindo uma vez com o mesmo perfil estável...")
        raise RuntimeError(f"{operation} failed with exit code {result.returncode}")
