from pathlib import Path

from PIL import Image

from ride_visuals.validate.media_validator import MediaValidator
from ride_visuals.video.engines.remotion import RemotionVideoEngine


def test_remotion_engine_capabilities_are_explicit():
    engine = RemotionVideoEngine(Path("renderer"))
    assert engine.capabilities.activity_telemetry
    assert engine.capabilities.transparent_still
    assert engine.capabilities.transparent_video
    assert engine.capabilities.background_image
    assert engine.capabilities.clean_route
    assert engine.capabilities.embedded_preview
    assert not engine.capabilities.collection
    assert engine.capabilities.locales == ("en", "pt-BR")


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
