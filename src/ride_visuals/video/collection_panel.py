"""Telemetry panel painting for collection video frames."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from PIL import Image, ImageColor, ImageDraw

from ride_visuals.design import VisualTheme
from ride_visuals.i18n import Translator
from ride_visuals.video.dashboard import DashboardPainter
from ride_visuals.video.fonts import FontManager
from ride_visuals.video.layout import VideoPartitionLayout


Metric = tuple[str, str]
MetricRow = tuple[Metric, Metric]


@dataclass(frozen=True)
class CollectionPanelState:
    ride_name: str
    metric_rows: Sequence[MetricRow]
    progress_pct: float
    current_distance_km: float
    current_ascent_m: float
    active_rides_count: int
    finished_count: int
    total_rides: int
    chart_values: np.ndarray
    chart_position: float
    chart_x_values: np.ndarray
    chart_ticks: Sequence[tuple[float, str]] | None
    finish_durations: np.ndarray
    cursor_elapsed_s: float


def format_elapsed(seconds: float) -> str:
    total_minutes = max(0, int(round(seconds / 60.0)))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def draw_finish_distribution(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    durations: np.ndarray,
    cursor_seconds: float,
    *,
    theme: VisualTheme,
    scale: int,
) -> None:
    """Draw real route finish times with a truthful elapsed cursor."""
    values = np.asarray(durations, dtype=float)
    values = values[np.isfinite(values) & (values >= 0.0)]
    if len(values) == 0:
        return
    maximum = max(float(np.max(values)), 1.0)
    bins = np.linspace(0.0, maximum, 17)
    counts, _ = np.histogram(values, bins=bins)
    max_count = max(int(np.max(counts)), 1)
    label_h = 24 * scale
    plot_h = max(height - label_h, 10 * scale)
    draw.line(
        [(x, y + plot_h), (x + width, y + plot_h)],
        fill=theme.border,
        width=scale,
    )
    gap = 3 * scale
    bar_w = max((width - gap * (len(counts) - 1)) // len(counts), 2 * scale)
    for index, count in enumerate(counts):
        x0 = x + index * (bar_w + gap)
        x1 = min(x + width, x0 + bar_w)
        bar_h = int(round((float(count) / max_count) * (plot_h - 8 * scale)))
        bin_end = bins[index + 1]
        color = theme.text_secondary if bin_end <= cursor_seconds else theme.route_inactive
        draw.rectangle((x0, y + plot_h - bar_h, x1, y + plot_h), fill=color)

    cursor_x = x + int(round(min(max(cursor_seconds / maximum, 0.0), 1.0) * width))
    draw.line(
        [(cursor_x, y), (cursor_x, y + plot_h)],
        fill=theme.route_primary,
        width=2 * scale,
    )
    tick_font = FontManager.get_font(10 * scale, bold=True)
    ticks = (
        (0.0, "00:00"),
        (maximum / 2.0, format_elapsed(maximum / 2.0)),
        (maximum, format_elapsed(maximum)),
    )
    for value, label in ticks:
        tick_x = x + int(round(value / maximum * width))
        label_w = int(round(tick_font.getlength(label)))
        text_x = min(max(tick_x - label_w // 2, x), x + width - label_w)
        draw.text(
            (text_x, y + plot_h + 7 * scale),
            label,
            fill=theme.text_muted,
            font=tick_font,
        )


def _draw_metric_grid(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    rows: Sequence[MetricRow],
    *,
    mobile: bool,
    scale: int,
    theme: VisualTheme,
) -> int:
    gap = (20 if mobile else 18) * scale
    column_width = (width - gap) // 2
    second_x = x + column_width + gap
    card_height = (94 if mobile else 78) * scale
    for row_index, row in enumerate(rows):
        row_y = y + row_index * card_height
        DashboardPainter.draw_card(
            draw,
            x,
            row_y,
            column_width,
            card_height,
            label=row[0][0],
            value=row[0][1],
            is_mobile=mobile,
            scale=scale,
            theme=theme,
        )
        DashboardPainter.draw_card(
            draw,
            second_x,
            row_y,
            column_width,
            card_height,
            label=row[1][0],
            value=row[1][1],
            is_mobile=mobile,
            scale=scale,
            theme=theme,
        )
    if not mobile:
        divider_x = x + column_width + gap // 2
        draw.line(
            [(divider_x, y), (divider_x, y + len(rows) * card_height)],
            fill=theme.border,
            width=scale,
        )
    return y + len(rows) * card_height


def _draw_chart(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    motion: str,
    state: CollectionPanelState,
    theme: VisualTheme,
    scale: int,
) -> None:
    if motion == "elapsed":
        draw_finish_distribution(
            draw,
            x,
            y,
            width,
            height,
            state.finish_durations,
            state.cursor_elapsed_s,
            theme=theme,
            scale=scale,
        )
    else:
        DashboardPainter.draw_progress_chart(
            draw,
            x,
            y,
            width,
            height,
            state.chart_values,
            state.chart_position,
            scale=scale,
            x_values=state.chart_x_values,
            x_ticks=state.chart_ticks,
            theme=theme,
        )


def draw_collection_panel(
    image: Image.Image,
    layout: VideoPartitionLayout,
    state: CollectionPanelState,
    *,
    motion: str,
    mode: str,
    basemap: str,
    has_basemap: bool,
    show_progress_bar: bool,
    i18n: Translator,
    theme: VisualTheme,
    scale: int,
) -> None:
    """Paint the desktop, portrait, or clean collection presentation."""
    draw = ImageDraw.Draw(image)
    if mode in {"16:9", "9:16"}:
        panel = layout.telemetry_rect
        if has_basemap:
            panel_alpha = 204 if basemap == "satellite" else 220
            panel_rgb = ImageColor.getrgb(theme.panel_background)
            panel_tint = Image.new("RGBA", (panel.w, panel.h), (*panel_rgb, panel_alpha))
            image.paste(panel_tint, (panel.x0, panel.y0), panel_tint)
            draw = ImageDraw.Draw(image)
        else:
            draw.rectangle(
                (panel.x0, panel.y0, panel.x1, panel.y1),
                fill=theme.panel_background,
            )

    if mode == "16:9" and layout.telemetry_rect.w > 0:
        panel = layout.telemetry_rect
        draw.line(
            [(panel.x0, panel.y0), (panel.x0, panel.y1)],
            fill=theme.border,
            width=scale,
        )
        content_width = panel.w - 70 * scale
        x = panel.x0 + 35 * scale
        y = panel.y0 + 40 * scale
        y = DashboardPainter.draw_header(
            draw,
            x,
            y,
            content_width,
            title=i18n.text("collection.title"),
            subtitle=state.ride_name,
            eyebrow="",
            is_mobile=False,
            scale=scale,
            theme=theme,
        )
        y = _draw_metric_grid(
            draw,
            x,
            y,
            content_width,
            state.metric_rows,
            mobile=False,
            scale=scale,
            theme=theme,
        )
        if show_progress_bar:
            DashboardPainter.draw_progress_bar(
                draw,
                x,
                y + 10 * scale,
                content_width,
                10 * scale,
                pct=state.progress_pct,
                scale=scale,
                theme=theme,
            )
        pad_x = 16 * scale
        chart_top = y + (42 if show_progress_bar else 16) * scale
        chart_label_font = FontManager.get_font(13 * scale, bold=True)
        chart_value_font = FontManager.get_font(28 * scale, bold=True)
        if motion == "elapsed":
            chart_label = "collection.finish_distribution"
            chart_value = f"{state.finished_count} / {state.total_rides}"
        else:
            chart_label = (
                "metric.season_distance"
                if motion == "chronological"
                else "metric.combined_distance"
            )
            chart_value = f"{i18n.number(state.current_distance_km, 1)} km"
        draw.text(
            (x + pad_x, chart_top),
            i18n.text(chart_label).upper(),
            fill=theme.text_muted,
            font=chart_label_font,
        )
        draw.text(
            (x + pad_x, chart_top + 22 * scale),
            chart_value,
            fill=theme.text_primary,
            font=chart_value_font,
        )
        axis_top = chart_top + 64 * scale
        axis_height = max(100 * scale, panel.y1 - axis_top - 48 * scale)
        _draw_chart(
            draw,
            x,
            axis_top,
            content_width,
            axis_height,
            motion=motion,
            state=state,
            theme=theme,
            scale=scale,
        )
        return

    if mode == "9:16" and layout.telemetry_rect.h > 0:
        panel = layout.telemetry_rect
        draw.line(
            [(panel.x0, panel.y0), (panel.x1, panel.y0)],
            fill=theme.border,
            width=scale,
        )
        x = panel.x0 + 50 * scale
        y = panel.y0 + 35 * scale
        content_width = panel.w - 100 * scale
        y = DashboardPainter.draw_header(
            draw,
            x,
            y,
            content_width,
            title=i18n.text("collection.title"),
            subtitle=state.ride_name,
            eyebrow="",
            is_mobile=True,
            scale=scale,
            theme=theme,
        )
        y = _draw_metric_grid(
            draw,
            x,
            y,
            content_width,
            state.metric_rows,
            mobile=True,
            scale=scale,
            theme=theme,
        ) + 12 * scale
        if show_progress_bar:
            DashboardPainter.draw_progress_bar(
                draw,
                x,
                y,
                content_width,
                12 * scale,
                pct=state.progress_pct,
                scale=scale,
                theme=theme,
            )
        chart_top = y + (28 if show_progress_bar else 0) * scale
        chart_height = max(70 * scale, panel.y1 - chart_top - 26 * scale)
        _draw_chart(
            draw,
            x,
            chart_top,
            content_width,
            chart_height,
            motion=motion,
            state=state,
            theme=theme,
            scale=scale,
        )
        return

    vertical = layout.canvas_h > layout.canvas_w
    h_scale = layout.canvas_h / (1920.0 if vertical else 1080.0)
    title_size = int(round((56 if vertical else 44) * h_scale))
    subtitle_size = int(round((26 if vertical else 22) * h_scale))
    title_font = FontManager.get_font(title_size, bold=True)
    subtitle_font = FontManager.get_font(subtitle_size, bold=False)

    clean_x = layout.map_rect.x0 + int(round((64 if vertical else 60) * h_scale))
    title_y = layout.map_rect.y0 + int(round((72 if vertical else 56) * h_scale))
    subtitle_y = title_y + int(round((64 if vertical else 48) * h_scale))

    draw.text(
        (clean_x, title_y),
        i18n.text("video.season_title", count=state.total_rides),
        fill=theme.text_primary,
        font=title_font,
    )
    draw.text(
        (clean_x, subtitle_y),
        i18n.text(
            "video.season_summary",
            distance=i18n.number(state.current_distance_km, 1),
            ascent=i18n.number(state.current_ascent_m),
            count=f"{state.active_rides_count}/{state.total_rides}",
        ),
        fill=theme.text_secondary,
        font=subtitle_font,
    )
