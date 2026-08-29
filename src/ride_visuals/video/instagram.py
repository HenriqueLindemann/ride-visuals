"""Instagram Story geometry for full-bleed, turn-the-phone media."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

INSTAGRAM_STORY_LANDSCAPE = "instagram-story-landscape"
INSTAGRAM_PANEL_SHARE = 0.36


@dataclass(frozen=True)
class InstagramStoryGeometry:
    output_width: int = 1080
    output_height: int = 1920
    landscape_width: int = 1920
    landscape_height: int = 1080
    profile_safe_px: int = 220
    reply_safe_px: int = 220

    @property
    def content_left_px(self) -> int:
        return self.profile_safe_px

    @property
    def content_width(self) -> int:
        return self.landscape_width - self.profile_safe_px - self.reply_safe_px


INSTAGRAM_STORY = InstagramStoryGeometry()


def render_dimensions(
    output_width: int,
    output_height: int,
    presentation: str,
) -> tuple[int, int]:
    """Return the unrotated dimensions used to build a presentation."""
    if presentation == INSTAGRAM_STORY_LANDSCAPE:
        geometry = INSTAGRAM_STORY
        if (output_width, output_height) != (
            geometry.output_width,
            geometry.output_height,
        ):
            raise ValueError("Instagram Story output must be 1080x1920")
        return geometry.landscape_width, geometry.landscape_height
    if presentation != "standard":
        raise ValueError(f"Unknown video presentation: {presentation}")
    return output_width, output_height


def present_frame(
    frame: Image.Image,
    *,
    presentation: str,
) -> Image.Image:
    """Rotate a full-bleed logical frame into its fixed delivery orientation."""
    if presentation == "standard":
        return frame
    if presentation != INSTAGRAM_STORY_LANDSCAPE:
        raise ValueError(f"Unknown video presentation: {presentation}")

    geometry = INSTAGRAM_STORY
    if frame.size != (geometry.landscape_width, geometry.landscape_height):
        raise ValueError("Instagram Story source frame must be 1920x1080")
    return frame.transpose(Image.Transpose.ROTATE_270)


def safe_content_dimensions(
    output_width: int,
    output_height: int,
    presentation: str,
) -> tuple[int, int]:
    """Return the area available to critical content before delivery rotation."""
    render_width, render_height = render_dimensions(
        output_width,
        output_height,
        presentation,
    )
    if presentation == INSTAGRAM_STORY_LANDSCAPE:
        return INSTAGRAM_STORY.content_width, render_height
    return render_width, render_height


def safe_insets(presentation: str, *, scale: int = 1) -> tuple[int, int]:
    """Return logical left/right UI exclusions at an optional render scale."""
    if presentation == INSTAGRAM_STORY_LANDSCAPE:
        return (
            INSTAGRAM_STORY.profile_safe_px * scale,
            INSTAGRAM_STORY.reply_safe_px * scale,
        )
    if presentation != "standard":
        raise ValueError(f"Unknown video presentation: {presentation}")
    return 0, 0


def place_safe_content(
    content: Image.Image,
    *,
    presentation: str,
    background: str | tuple[int, ...],
) -> Image.Image:
    """Place a critical-content visual over a full-size neutral background."""
    if presentation == "standard":
        return content
    if presentation != INSTAGRAM_STORY_LANDSCAPE:
        raise ValueError(f"Unknown video presentation: {presentation}")

    geometry = INSTAGRAM_STORY
    if content.size != (geometry.content_width, geometry.landscape_height):
        raise ValueError(
            "Instagram Story safe content must be "
            f"{geometry.content_width}x{geometry.landscape_height}"
        )
    mode = "RGBA" if content.mode == "RGBA" else "RGB"
    canvas = Image.new(
        mode,
        (geometry.landscape_width, geometry.landscape_height),
        background,
    )
    canvas.paste(content.convert(mode), (geometry.content_left_px, 0))
    return canvas


def ffmpeg_filter(*, transparent: bool = False) -> str:
    """Return the fixed clockwise delivery-orientation video filter."""
    return "format=rgba,transpose=clock,format=rgba" if transparent else "transpose=clock"
