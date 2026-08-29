import json
from pathlib import Path
from types import SimpleNamespace

from ride_visuals.validate.media_validator import MediaValidator


def test_transparent_webm_accepts_ffmpeg_uppercase_alpha_tag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "overlay_preview.webm"
    output.touch()
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "vp9",
                "pix_fmt": "yuv420p",
                "width": 1080,
                "height": 1920,
                "tags": {"ALPHA_MODE": "1"},
            }
        ],
        "format": {"duration": "5.0"},
    }
    monkeypatch.setattr("shutil.which", lambda _name: "ffprobe")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(probe)),
    )

    result = MediaValidator.validate_transparent_video(output)

    assert result["valid"] is True
    assert result["has_alpha"] is True


def _mp4_probe(audio_codec: str | None) -> dict:
    streams = [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "width": 1920,
            "height": 1080,
        }
    ]
    if audio_codec is not None:
        streams.append({"codec_type": "audio", "codec_name": audio_codec})
    return {
        "streams": streams,
        "format": {"duration": "15.0"},
    }


def test_video_accepts_audioless_mp4(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "collection_all_chronological_heart_rate_16_9.mp4"
    output.write_bytes(b"moov" + b"\x00" * 64)
    probe = _mp4_probe(audio_codec=None)
    monkeypatch.setattr("shutil.which", lambda _name: "ffprobe")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(probe)),
    )

    result = MediaValidator.validate_video(output)

    assert result["valid"] is True
    assert result["audio_codec"] is None
    assert result["violations"] == []


def test_video_still_rejects_non_aac_audio(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "collection_all_chronological_heart_rate_16_9.mp4"
    output.write_bytes(b"moov" + b"\x00" * 64)
    probe = _mp4_probe(audio_codec="mp3")
    monkeypatch.setattr("shutil.which", lambda _name: "ffprobe")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(probe)),
    )

    result = MediaValidator.validate_video(output)

    assert result["valid"] is False
    assert "audio track must be AAC when present" in result["violations"]
