import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from ride_visuals.validate.media_validator import MediaValidator
from ride_visuals.video.engines.remotion import (
    RemotionVideoEngine,
    background_video_source,
    media_normalization_command,
    stage_background_video,
)
from ride_visuals.video.spec import (
    ActivityIdentity,
    ActivityRenderSpec,
    BackgroundSpec,
    RenderProfile,
)


def _video_background_spec(source: Path, *, audio: bool = False) -> ActivityRenderSpec:
    return ActivityRenderSpec(
        schema_version="1.0",
        kind="activity-telemetry",
        locale="en",
        theme="midnight",
        profile=RenderProfile(),
        activity=ActivityIdentity(id="42", title="Morning Ride"),
        background=BackgroundSpec(src=str(source), kind="video", audio=audio),
        summary={},
        points=[],
    )


def test_remotion_engine_capabilities_are_explicit():
    engine = RemotionVideoEngine(Path("renderer"))
    assert engine.renderer_dir.is_absolute()
    assert engine.cli.is_absolute()
    assert engine.capabilities.activity_telemetry
    assert engine.capabilities.transparent_still
    assert engine.capabilities.transparent_video
    assert engine.capabilities.background_image
    assert engine.capabilities.background_video
    assert engine.capabilities.clean_route
    assert engine.capabilities.embedded_preview
    assert not engine.capabilities.collection
    assert engine.capabilities.locales == ("en", "pt-BR")


def test_background_video_is_staged_content_addressed_and_idempotent(tmp_path):
    renderer = tmp_path / "renderer"
    renderer.mkdir()
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake video payload")

    staged = stage_background_video(_video_background_spec(source), renderer)
    staged_again = stage_background_video(staged, renderer)

    background = staged.background
    assert background is not None
    assert background.src.startswith("backgrounds/")
    staged_file = renderer / "public" / background.src
    assert staged_file.is_file()
    assert staged_file.read_bytes() == b"fake video payload"
    digest = hashlib.sha256(b"fake video payload").hexdigest()[:16]
    assert background.src == f"backgrounds/{digest}.mp4"
    assert not list(staged_file.parent.glob(".background-*.part"))
    # Re-staging an already staged spec is a no-op on the same path.
    assert staged_again.background is not None
    assert staged_again.background.src == background.src


def test_background_video_source_resolves_relative_to_public_dir(tmp_path):
    renderer = tmp_path / "renderer"
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"payload")
    spec = stage_background_video(_video_background_spec(source), renderer)

    resolved = background_video_source(spec.background, renderer)
    assert resolved is not None
    assert resolved.is_file()
    # Non-video backgrounds never resolve to a media path.
    assert background_video_source(None, renderer) is None


def test_staging_requires_a_real_background_video(tmp_path):
    with pytest.raises(FileNotFoundError, match="Background video was not found"):
        stage_background_video(_video_background_spec(tmp_path / "missing.mp4"), tmp_path)


def test_media_normalization_preserves_requested_background_audio(tmp_path):
    source = tmp_path / "background.mp4"
    spec = _video_background_spec(source, audio=True)

    command = media_normalization_command(
        "ffmpeg",
        tmp_path / "video-only.mp4",
        tmp_path / "output.mp4",
        spec,
        source,
    )

    assert command.count("-i") == 2
    assert "-an" not in command
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-ar") + 1] == "48000"
    assert command[command.index("-ac") + 1] == "2"
    assert command[command.index("-af") + 1] == (
        "atrim=duration=6.000000,asetpts=PTS-STARTPTS,apad=whole_dur=6.000000"
    )
    assert "-shortest" in command
    assert command[command.index("-c:v") + 1] == "copy"


def test_media_normalization_can_mute_background_video(tmp_path):
    source = tmp_path / "background.mp4"
    spec = _video_background_spec(source)

    command = media_normalization_command(
        "ffmpeg",
        tmp_path / "video-only.mp4",
        tmp_path / "output.mp4",
        spec,
        source,
    )

    assert command.count("-i") == 1
    assert "-an" in command
    assert "-c:a" not in command


def test_media_normalization_produces_aligned_padded_audio(tmp_path):
    video_only = tmp_path / "video-only.mp4"
    background_audio = tmp_path / "background.m4a"
    output = tmp_path / "output.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=size=320x320:rate=30:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(video_only),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.4",
            "-c:a",
            "aac",
            str(background_audio),
        ],
        check=True,
    )
    spec = replace(
        _video_background_spec(background_audio, audio=True),
        profile=RenderProfile(width=320, height=320, duration_seconds=1.0, hold_seconds=0.0),
    )

    subprocess.run(
        media_normalization_command("ffmpeg", video_only, output, spec, background_audio),
        check=True,
    )
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = json.loads(result.stdout)
    audio = next(stream for stream in metadata["streams"] if stream["codec_type"] == "audio")

    assert float(audio["start_time"]) == pytest.approx(0.0, abs=1e-3)
    assert float(metadata["format"]["duration"]) == pytest.approx(1.0, abs=0.05)


def test_instagram_normalization_uses_delivery_encoding_profile(tmp_path):
    spec = replace(
        _video_background_spec(tmp_path / "background.mp4"),
        presentation="instagram-story-landscape",
    )

    command = media_normalization_command(
        "ffmpeg",
        tmp_path / "video-only.mp4",
        tmp_path / "output.mp4",
        spec,
        None,
    )

    assert "-vf" in command
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-profile:v") + 1] == "high"
    assert command.count("-colorspace") == 1
    assert command[command.index("-colorspace") + 1] == "bt709"


def test_remotion_engine_rejects_mp4_for_transparent_video(tmp_path):
    engine = RemotionVideoEngine(Path("renderer"))
    # Extension validation happens before any renderer process is launched.
    try:
        engine.render_overlay_video(None, tmp_path / "overlay.mp4", spec_path=tmp_path / "spec.json")  # type: ignore[arg-type]
    except ValueError as exc:
        assert ".webm or .mov" in str(exc)
    else:
        raise AssertionError("MP4 cannot be accepted as a transparent video container")


def test_overlay_png_requires_actual_transparent_pixels(tmp_path):
    opaque = tmp_path / "opaque.png"
    transparent = tmp_path / "transparent.png"
    Image.new("RGBA", (1920, 1080), (0, 0, 0, 255)).save(opaque)
    Image.new("RGBA", (1920, 1080), (0, 0, 0, 0)).save(transparent)

    assert not MediaValidator.validate_transparent_still(opaque)["valid"]
    assert MediaValidator.validate_transparent_still(transparent)["valid"]


def test_frame_critical_svgs_do_not_depend_on_async_dom_measurement():
    """A measured-on-mount SVG can be captured empty by a Remotion worker."""
    renderer = Path("renderer/src/components")
    for filename in ("RouteMap.tsx", "ProgressAxisChart.tsx"):
        source = (renderer / filename).read_text(encoding="utf-8")
        assert "new ResizeObserver" not in source
        assert "useElementSize<" not in source
        assert "preserveAspectRatio" in source
