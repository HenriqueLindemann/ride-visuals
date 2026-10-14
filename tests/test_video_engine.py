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


def test_background_video_is_staged_content_addressed_and_idempotent(tmp_path):
    renderer = tmp_path / "renderer"
    renderer.mkdir()
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake video payload")

    staged = stage_background_video(_video_background_spec(source), renderer)
    staged_again = stage_background_video(staged, renderer)

    background = staged.background
    assert background is not None
    digest = hashlib.sha256(b"fake video payload").hexdigest()[:16]
    assert background.src == f"backgrounds/{digest}.mp4"
    staged_file = renderer / "public" / background.src
    assert staged_file.read_bytes() == b"fake video payload"
    assert staged_again.background == background
    assert background_video_source(staged.background, renderer) == staged_file
    assert background_video_source(None, renderer) is None


def test_staging_requires_a_real_background_video(tmp_path):
    with pytest.raises(FileNotFoundError, match="Background video was not found"):
        stage_background_video(_video_background_spec(tmp_path / "missing.mp4"), tmp_path)


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


def test_remotion_engine_rejects_mp4_for_transparent_video(tmp_path):
    engine = RemotionVideoEngine(Path("renderer"))
    with pytest.raises(ValueError, match=r"\.webm or \.mov"):
        engine.render_overlay_video(None, tmp_path / "overlay.mp4", spec_path=tmp_path / "spec.json")  # type: ignore[arg-type]


def test_overlay_png_requires_actual_transparent_pixels(tmp_path):
    opaque = tmp_path / "opaque.png"
    transparent = tmp_path / "transparent.png"
    Image.new("RGBA", (960, 320), (0, 0, 0, 255)).save(opaque)
    Image.new("RGBA", (960, 320), (0, 0, 0, 0)).save(transparent)

    assert not MediaValidator.validate_transparent_still(opaque)["valid"]
    assert MediaValidator.validate_transparent_still(transparent)["valid"]
