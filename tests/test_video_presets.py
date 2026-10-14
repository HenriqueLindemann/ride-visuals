import pytest

from ride_visuals.video.presets import get_video_preset


@pytest.mark.parametrize("kind", ["activity", "collection", "timeline"])
def test_final_video_presets_total_fifteen_seconds_and_previews_stay_short(kind):
    final = get_video_preset(kind, "16:9")
    preview = get_video_preset(kind, "16:9", preview=True)

    assert final.duration_seconds + final.hold_seconds == 15.0
    assert preview.duration_seconds + preview.hold_seconds <= 10.0


def test_instagram_and_clean_presets_preserve_layout_and_presentation():
    story = get_video_preset("activity", "instagram")
    clean_story = get_video_preset("collection", "instagram", clean=True)

    assert (story.canvas.width, story.canvas.height) == (1080, 1920)
    assert (story.canvas.render_width, story.canvas.render_height) == (1920, 1080)
    assert story.canvas.presentation == "instagram-story-landscape"
    assert clean_story.canvas.layout == "clean"
    assert clean_story.canvas.presentation == "instagram-story-landscape"


def test_unknown_preset_is_explicit():
    with pytest.raises(ValueError, match="Unsupported video preset"):
        get_video_preset("unknown", "16:9")
