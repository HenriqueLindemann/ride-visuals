import pytest

from ride_visuals.video.presets import get_video_preset


def test_activity_portrait_preset_is_partitioned_and_deterministic():
    preset = get_video_preset("activity", "9:16", preview=True)
    # Previews keep the design canvas so typography and layout stay faithful.
    assert (preset.canvas.width, preset.canvas.height) == (1080, 1920)
    assert preset.canvas.layout == "9:16"
    assert preset.duration_seconds == 4.0
    assert preset.fps == 30


def test_clean_collection_uses_full_map_layout():
    preset = get_video_preset("collection", "16:9", clean=True)
    assert preset.canvas.layout == "clean"
    assert preset.hold_seconds == 3.0


def test_4k_preview_uses_landscape_partition_at_half_resolution():
    preset = get_video_preset("collection", "4k", preview=True)
    assert (preset.canvas.width, preset.canvas.height) == (1920, 1080)
    assert preset.canvas.layout == "16:9"
    assert preset.duration_seconds + preset.hold_seconds <= 10.0


def test_final_presets_keep_native_resolution():
    landscape = get_video_preset("activity", "16:9")
    portrait = get_video_preset("activity", "9:16")
    uhd = get_video_preset("collection", "4k")

    assert (landscape.canvas.width, landscape.canvas.height) == (1920, 1080)
    assert (portrait.canvas.width, portrait.canvas.height) == (1080, 1920)
    assert (uhd.canvas.width, uhd.canvas.height) == (3840, 2160)


def test_instagram_preset_delivers_portrait_but_renders_landscape():
    preset = get_video_preset("activity", "instagram")

    assert (preset.canvas.width, preset.canvas.height) == (1080, 1920)
    assert (preset.canvas.render_width, preset.canvas.render_height) == (1920, 1080)
    assert preset.canvas.layout == "16:9"
    assert preset.canvas.presentation == "instagram-story-landscape"


def test_clean_instagram_preset_preserves_story_presentation():
    preset = get_video_preset("collection", "instagram", clean=True)

    assert preset.canvas.layout == "clean"
    assert preset.canvas.presentation == "instagram-story-landscape"


def test_progress_preview_stays_below_ten_seconds():
    preset = get_video_preset("progress", "16:9", preview=True)
    assert preset.duration_seconds * 8 <= 10.0


def test_timeline_preview_stays_short_and_has_hold():
    preset = get_video_preset("timeline", "16:9", preview=True)
    assert preset.duration_seconds + preset.hold_seconds <= 10.0
    assert preset.hold_seconds == 1.0


@pytest.mark.parametrize("kind", ["activity", "collection", "timeline"])
def test_final_video_presets_total_fifteen_seconds(kind):
    preset = get_video_preset(kind, "16:9")
    assert preset.duration_seconds + preset.hold_seconds == 15.0


def test_final_progress_film_totals_fifteen_seconds():
    preset = get_video_preset("progress", "16:9")
    assert preset.duration_seconds * 8 == 15.0


def test_unknown_preset_is_explicit():
    with pytest.raises(ValueError, match="Unsupported video preset"):
        get_video_preset("unknown", "16:9")
