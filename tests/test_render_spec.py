import json
import subprocess
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ride_visuals.video.spec import (
    ActivityRenderSpec,
    BackgroundSpec,
    RenderProfile,
    probe_video,
)


def test_render_profile_rejects_odd_video_dimensions():
    with pytest.raises(ValueError, match="even"):
        RenderProfile(width=1919)


def test_render_spec_is_versioned_and_json_safe(tmp_path):
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-08-23T08:00:00Z", periods=4, freq="1s"),
            "lat": [10.0, 10.001, 10.002, 10.003],
            "lon": [20.0, 20.001, 20.002, 20.003],
            "altitude": [250.0, 251.0, 252.0, 253.0],
            "distance_m": [0.0, 100.0, 200.0, 300.0],
            "speed_mps": [5.0, 6.0, 7.0, 8.0],
            "heart_rate_bpm": [120.0, 125.0, 130.0, 135.0],
            "power_watts": [None, None, None, None],
        }
    )
    parquet = tmp_path / "activity.parquet"
    pq.write_table(pa.Table.from_pandas(frame), parquet)

    spec = ActivityRenderSpec.from_parquet(
        parquet,
        activity_id=42,
        title="Morning Ride",
        locale="pt-BR",
        max_points=3,
    )
    output = spec.write(tmp_path / "render.json")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schemaVersion"] == "1.0"
    assert payload["kind"] == "activity-telemetry"
    assert payload["locale"] == "pt-BR"
    assert payload["activity"]["id"] == "42"
    assert payload["background"] is None
    assert payload["summary"]["speedWindowSeconds"] >= 30
    assert payload["show_progress_bar"] is False
    assert payload["presentation"] == "standard"
    assert len(payload["points"]) == 3
    assert payload["points"][0]["powerWatts"] is None
    assert "cumulativeElevationGainM" in payload["points"][0]


def test_render_spec_can_enable_progress_bar(tmp_path):
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-08-23T08:00:00Z", periods=2, freq="1s"),
            "lat": [10.0, 10.001],
            "lon": [20.0, 20.001],
            "distance_m": [0.0, 100.0],
        }
    )
    parquet = tmp_path / "activity.parquet"
    pq.write_table(pa.Table.from_pandas(frame), parquet)

    spec = ActivityRenderSpec.from_parquet(
        parquet,
        activity_id=42,
        title="Morning Ride",
        show_progress_bar=True,
    )

    assert spec.show_progress_bar is True



def test_render_spec_embeds_portable_background(tmp_path):
    from PIL import Image

    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-08-23T08:00:00Z", periods=2, freq="1s"),
            "lat": [10.0, 10.001],
            "lon": [20.0, 20.001],
            "distance_m": [0.0, 100.0],
        }
    )
    parquet = tmp_path / "activity.parquet"
    pq.write_table(pa.Table.from_pandas(frame), parquet)
    background = tmp_path / "background.png"
    Image.new("RGB", (4, 4), "navy").save(background)

    spec = ActivityRenderSpec.from_parquet(
        parquet,
        activity_id=42,
        title="Morning Ride",
        background_image=background,
        background_blur_px=12,
        background_dim=0.45,
    )

    assert spec.background is not None
    assert spec.background.src.startswith("data:image/png;base64,")
    assert spec.background.blur_px == 12
    assert spec.background.dim == 0.45
    assert spec.background.attribution is None
    assert spec.background.attribution_bottom_px == 6.0
    assert spec.background.kind == "image"
    assert spec.background.audio is False


def _write_clip(path, *, with_audio: bool, seconds: float = 1.0):
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=320x180:rate=30:duration={seconds}",
    ]
    if with_audio:
        command.extend(["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            *([] if with_audio else ["-an"]),
            *(["-c:a", "aac", "-shortest"] if with_audio else []),
            str(path),
        ]
    )
    subprocess.run(command, check=True)


def _minimal_parquet(tmp_path):
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-08-23T08:00:00Z", periods=2, freq="1s"),
            "lat": [10.0, 10.001],
            "lon": [20.0, 20.001],
            "distance_m": [0.0, 100.0],
        }
    )
    parquet = tmp_path / "activity.parquet"
    pq.write_table(pa.Table.from_pandas(frame), parquet)
    return parquet


def test_render_spec_references_video_background(tmp_path):
    parquet = _minimal_parquet(tmp_path)
    clip = tmp_path / "background.mp4"
    _write_clip(clip, with_audio=True, seconds=6.0)

    spec = ActivityRenderSpec.from_parquet(
        parquet,
        activity_id=42,
        title="Morning Ride",
        background_video=clip,
        profile=RenderProfile(duration_seconds=4.0, hold_seconds=1.0),
    )

    assert spec.background is not None
    assert spec.background.kind == "video"
    assert spec.background.src == str(clip.resolve())
    # The clip covers the five-second composition and carries audio.
    assert spec.background.audio is True
    assert BackgroundSpec.from_video(clip, audio=False).audio is False


def test_render_spec_rejects_video_background_shorter_than_the_composition(tmp_path):
    parquet = _minimal_parquet(tmp_path)
    clip = tmp_path / "background.mp4"
    _write_clip(clip, with_audio=True, seconds=1.0)

    with pytest.raises(ValueError, match="covers the animation"):
        ActivityRenderSpec.from_parquet(
            parquet,
            activity_id=42,
            title="Morning Ride",
            background_video=clip,
            profile=RenderProfile(duration_seconds=4.0, hold_seconds=1.0),
        )


def test_render_spec_video_background_without_audio_delivers_silently(tmp_path):
    parquet = _minimal_parquet(tmp_path)
    clip = tmp_path / "background.mp4"
    _write_clip(clip, with_audio=False, seconds=6.0)

    spec = ActivityRenderSpec.from_parquet(
        parquet,
        activity_id=42,
        title="Morning Ride",
        background_video=clip,
        profile=RenderProfile(duration_seconds=4.0, hold_seconds=1.0),
    )

    assert spec.background is not None
    assert spec.background.kind == "video"
    # The clip covers the render duration and carries no audio track.
    assert spec.background.audio is False


def test_background_spec_rejects_audio_on_image_kind():
    with pytest.raises(ValueError, match="only applies to video backgrounds"):
        BackgroundSpec(src="data:image/png;base64,AAAA", audio=True)


def test_render_spec_rejects_multiple_background_sources(tmp_path):
    parquet = _minimal_parquet(tmp_path)
    image = tmp_path / "background.png"
    video = tmp_path / "background.mp4"

    with pytest.raises(ValueError, match="either a background image or a background video"):
        ActivityRenderSpec.from_parquet(
            parquet,
            activity_id=42,
            title="Morning Ride",
            background_image=image,
            background_video=video,
        )


def test_video_probe_prefers_visual_stream_duration(tmp_path, monkeypatch):
    clip = tmp_path / "background.mp4"
    clip.write_bytes(b"stub")
    metadata = {
        "streams": [
            {"codec_type": "video", "duration": "1.0"},
            {"codec_type": "audio", "duration": "6.0"},
        ],
        "format": {"duration": "6.0"},
    }
    monkeypatch.setattr(
        "ride_visuals.video.spec.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(metadata),
            stderr="",
        ),
    )

    result = probe_video(clip)

    assert result.duration_seconds == 1.0
    assert result.has_audio is True


def test_background_video_requires_an_existing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="Background video was not found"):
        BackgroundSpec.from_video(tmp_path / "missing.mp4")
