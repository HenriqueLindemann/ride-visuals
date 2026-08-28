"""Canonical Python design tokens for every generated visual.

The interface is intentionally neutral: black, white and grey establish
hierarchy; route orange and semantic effort colors are reserved for data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class VisualTheme:
    name: str
    canvas: str
    map_background: str
    panel_background: str
    surface: str
    surface_hover: str
    border: str
    grid: str
    text_primary: str
    text_secondary: str
    text_muted: str
    data_missing: str
    route_inactive: str
    route_primary: str
    route_highlight: str
    speed: str
    heart_rate: str
    distance: str
    temperature: str
    elevation: str
    power: str
    grade: str


MIDNIGHT = VisualTheme(
    name="midnight",
    canvas="#050505",
    map_background="#080808",
    panel_background="#0A0A0A",
    surface="#0C0C0C",
    surface_hover="#11110F",
    border="#292927",
    grid="#171715",
    text_primary="#F4F4F1",
    text_secondary="#B6B6B0",
    text_muted="#72726D",
    data_missing="#D7D7D0",
    route_inactive="#333330",
    route_primary="#FF4D00",
    route_highlight="#FFF7F2",
    speed="#F4F4F1",
    heart_rate="#FF4F5E",
    distance="#F4F4F1",
    temperature="#A6A6A0",
    elevation="#F4F4F1",
    power="#F4F4F1",
    grade="#A6A6A0",
)


FROST = VisualTheme(
    name="frost",
    canvas="#F2F2EF",
    map_background="#EAEAE6",
    panel_background="#F7F7F4",
    surface="#F8F8F5",
    surface_hover="#FFFFFF",
    border="#C9C9C3",
    grid="#DEDED8",
    text_primary="#11110F",
    text_secondary="#494946",
    text_muted="#7B7B75",
    data_missing="#2F2F2C",
    route_inactive="#B8B8B1",
    route_primary="#F04400",
    route_highlight="#11110F",
    speed="#11110F",
    heart_rate="#D9283F",
    distance="#11110F",
    temperature="#666660",
    elevation="#11110F",
    power="#11110F",
    grade="#666660",
)


THEMES = {theme.name: theme for theme in (MIDNIGHT, FROST)}

# Structural colors stay neutral; these palettes are exclusively for paths.
MONTH_ROUTE_COLORS = {
    1: "#5D6770", 2: "#66727A", 3: "#747D7B", 4: "#85877D",
    5: "#979282", 6: "#AA9A82", 7: "#BE9A75", 8: "#D48E61",
    9: "#E77D4C", 10: "#F36A36", 11: "#FA5921", 12: "#FF4D00",
}
EFFORT_COLORS = ("#8B9294", "#AFC1AE", "#D8C96D", "#F08A45", "#E5484D")

# Discrete, data-only palettes. They deliberately avoid gradients: every color
# maps to a named interval in the collection legend. Structural UI remains
# neutral and orange stays the focus color.
TEMPERATURE_COLORS = ("#56758A", "#78989A", "#C6B96A", "#D98345", "#E0523E")
SPEED_COLORS = ("#686864", "#8A8A84", "#B3A58E", "#D77A46", "#FF4D00")
GRADE_COLORS = ("#647785", "#89959B", "#B6B6B0", "#D7875D", "#FF4D00")
ALTITUDE_COLORS = ("#5F7480", "#819091", "#AAA58F", "#D08350", "#FF4D00")


def get_theme(name: str | VisualTheme = "midnight") -> VisualTheme:
    if isinstance(name, VisualTheme):
        return name
    try:
        return THEMES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown theme {name!r}. Choose one of: {', '.join(THEMES)}") from exc


def route_color(style: str, when: date | datetime | None = None, *, theme: VisualTheme = MIDNIGHT) -> str:
    if style in ("orange", "density"):
        return theme.route_primary
    if style == "monochrome":
        return theme.text_secondary
    if style == "monthly":
        month = when.month if when is not None else 1
        return MONTH_ROUTE_COLORS.get(month, theme.text_secondary)
    raise ValueError("Route style must be orange, density, monochrome or monthly")
