"""Deterministic TrueType font loading for generated media."""

from pathlib import Path
from PIL import ImageFont


FONT_BOLD_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_REGULAR_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


class FontManager:
    """Carrega fontes TrueType com cache por tamanho."""

    _cache = {}

    @classmethod
    def get_font(cls, size: int = 16, bold: bool = False) -> ImageFont.ImageFont:
        key = (size, bold)
        if key in cls._cache:
            return cls._cache[key]

        target_path = FONT_BOLD_PATH if bold else FONT_REGULAR_PATH
        if target_path.exists():
            try:
                font = ImageFont.truetype(str(target_path), size)
                cls._cache[key] = font
                return font
            except Exception:
                pass

        font = ImageFont.load_default()
        cls._cache[key] = font
        return font
