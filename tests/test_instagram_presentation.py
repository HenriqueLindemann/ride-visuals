from PIL import Image

from ride_visuals.video.instagram import (
    INSTAGRAM_STORY,
    INSTAGRAM_STORY_LANDSCAPE,
    place_safe_content,
    present_frame,
)


def test_instagram_frame_is_clockwise_and_remains_full_bleed():
    source = Image.new("RGB", (1920, 1080), "#ff0000")
    source.paste("#0000ff", (960, 0, 1920, 1080))
    result = present_frame(
        source,
        presentation=INSTAGRAM_STORY_LANDSCAPE,
    )

    assert result.size == (1080, 1920)
    assert result.getpixel((540, 0)) == (255, 0, 0)
    assert result.getpixel((540, 1919)) == (0, 0, 255)


def test_instagram_transparent_frame_remains_full_bleed():
    source = Image.new("RGBA", (1920, 1080), (255, 0, 0, 128))
    result = present_frame(
        source,
        presentation=INSTAGRAM_STORY_LANDSCAPE,
    )

    assert result.getpixel((540, 0))[3] == 128
    assert result.getpixel((540, INSTAGRAM_STORY.profile_safe_px))[3] == 128


def test_critical_content_is_placed_between_ui_zones():
    content = Image.new("RGB", (1480, 1080), "#00ff00")
    result = place_safe_content(
        content,
        presentation=INSTAGRAM_STORY_LANDSCAPE,
        background="#050505",
    )

    assert result.size == (1920, 1080)
    assert result.getpixel((219, 540)) == (5, 5, 5)
    assert result.getpixel((220, 540)) == (0, 255, 0)
    assert result.getpixel((1699, 540)) == (0, 255, 0)
    assert result.getpixel((1700, 540)) == (5, 5, 5)
