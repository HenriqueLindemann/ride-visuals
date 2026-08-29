"""Editorial season-progress film built from lossless activity metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from ride_visuals.analytics.progress import SeasonAnalytics
from ride_visuals.design import EFFORT_COLORS, get_theme
from ride_visuals.i18n import Translator
from ride_visuals.selection import ActivitySelection
from ride_visuals.video.encoding import RawVideoEncoder
from ride_visuals.video.instagram import (
    place_safe_content,
    present_frame,
    safe_content_dimensions,
)


class ProgressMovieRenderer:
    """Render a restrained, localized eight-chapter season film."""

    CHAPTER_COUNT = 8

    def __init__(self, catalog_db_path: Path, streams_dir: Path, outputs_dir: Path,
                 *, locale: str = "pt-BR", theme: str = "midnight",
                 selection: ActivitySelection | None = None):
        self.catalog_db_path = Path(catalog_db_path)
        self.streams_dir = Path(streams_dir)
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.i18n = Translator(locale)
        self.theme = get_theme(theme)
        self.selection = selection or ActivitySelection()

    def extract_summary_metrics(self) -> Dict[str, Any]:
        return SeasonAnalytics(
            self.catalog_db_path,
            self.streams_dir,
            selection=self.selection,
        ).extract()

    def _month_labels(self, monthly: list[dict[str, Any]]) -> list[str]:
        return [self.i18n.month_short(pd.Timestamp(f"{row['month']}-01")) for row in monthly]

    def _measurement(self, value: float | int | None, unit: str = "", decimals: int = 0) -> str:
        if value is None or not np.isfinite(float(value)):
            return self.i18n.text("value.unavailable")
        suffix = f" {unit}" if unit else ""
        return f"{self.i18n.number(value, decimals)}{suffix}"

    def _new_figure(self, width: int, height: int, chapter: int, title: str):
        portrait = height > width
        base_height = 1920 if portrait else 1080
        dpi = max(30, int(round(100.0 * (height / base_height))))
        figure = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=self.theme.canvas)
        left = 0.075 if not portrait else 0.08
        right = 0.94 if not portrait else 0.92
        figure.text(left, 0.925, f"{chapter:02d} / {self.CHAPTER_COUNT:02d}",
                    color=self.theme.route_primary, fontsize=12, fontweight="bold")
        figure.text(left, 0.855, title, color=self.theme.text_primary,
                    fontsize=32 if not portrait else 28, fontweight="bold")
        figure.lines.append(plt.Line2D([left, right], [0.795, 0.795], transform=figure.transFigure,
                                       color=self.theme.border, linewidth=0.8))
        figure.text(left, 0.035, self.i18n.text("progress.footer").upper(),
                    color=self.theme.text_muted, fontsize=10, fontweight="bold")
        figure.lines.append(plt.Line2D([left, right], [0.065, 0.065], transform=figure.transFigure,
                                       color=self.theme.border, linewidth=1.0))
        figure.lines.append(plt.Line2D([left, left + (right - left) * chapter / self.CHAPTER_COUNT],
                                       [0.065, 0.065], transform=figure.transFigure,
                                       color=self.theme.route_primary, linewidth=2.0))
        return figure

    def _style_axis(self, axis, title: str) -> None:
        axis.set_facecolor(self.theme.canvas)
        axis.set_title(title.upper(), loc="left", color=self.theme.text_muted,
                       fontsize=11, fontweight="bold", pad=12)
        axis.tick_params(colors=self.theme.text_muted, labelsize=11, length=0)
        axis.grid(axis="y", color=self.theme.grid, linewidth=0.7)
        axis.set_axisbelow(True)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color(self.theme.border)
        axis.spines["bottom"].set_color(self.theme.border)

    def _metric_grid(self, figure, rows: list[tuple[str, ...]], *, portrait: bool) -> None:
        columns = 1 if portrait else 2
        row_count = int(np.ceil(len(rows) / columns))
        left, total_width = (0.08, 0.84) if portrait else (0.075, 0.865)
        top, bottom = 0.73, 0.13
        gap_x = 0.035 if columns == 2 else 0.0
        gap_y = 0.025
        cell_width = (total_width - gap_x * (columns - 1)) / columns
        cell_height = (top - bottom - gap_y * (row_count - 1)) / row_count
        for index, entry in enumerate(rows):
            label, value = entry[:2]
            description = entry[2] if len(entry) > 2 else ""
            column = index % columns
            row = index // columns
            x = left + column * (cell_width + gap_x)
            y = top - (row + 1) * cell_height - row * gap_y
            axis = figure.add_axes([x, y, cell_width, cell_height], facecolor=self.theme.canvas)
            axis.axis("off")
            axis.plot([0, 1], [1, 1], color=self.theme.border, linewidth=0.8, transform=axis.transAxes)
            axis.text(0.02, 0.70, label.upper(), color=self.theme.text_muted,
                      fontsize=11, fontweight="bold", transform=axis.transAxes)
            axis.text(0.02, 0.31 if description else 0.25, value, color=self.theme.text_primary,
                      fontsize=29 if not portrait else 26, fontweight="bold", transform=axis.transAxes)
            if description:
                axis.text(0.02, 0.10, description, color=self.theme.text_secondary,
                          fontsize=10, transform=axis.transAxes)

    def _render_chapter_slide(self, chapter: int, metrics: Dict[str, Any], width: int, height: int) -> Image.Image:
        title = self.i18n.text(f"progress.chapter.{chapter}.title")
        figure = self._new_figure(width, height, chapter, title)
        portrait = height > width
        monthly = metrics["monthly"]
        month_labels = self._month_labels(monthly)
        chart_rect = [0.09, 0.15, 0.82, 0.56] if portrait else [0.10, 0.15, 0.80, 0.54]

        if chapter == 1:
            self._metric_grid(figure, [
                (self.i18n.text("progress.metric.total_distance"), f"{self.i18n.number(metrics['total_km'], 1)} km"),
                (self.i18n.text("progress.metric.total_elevation"), f"{self.i18n.number(metrics['total_elev_m'])} m"),
                (self.i18n.text("progress.metric.total_rides"), self.i18n.number(metrics["total_rides"])),
                (self.i18n.text("progress.metric.moving_time"), f"{self.i18n.number(metrics['total_hours'], 1)} h"),
            ], portrait=portrait)

        elif chapter == 2:
            weekly = pd.DataFrame(metrics["weekly"])
            week_dates = pd.to_datetime(weekly["week_start"])
            upper = figure.add_axes([chart_rect[0], 0.42, chart_rect[2], 0.27], facecolor=self.theme.canvas)
            lower = figure.add_axes([chart_rect[0], 0.15, chart_rect[2], 0.18], facecolor=self.theme.canvas)
            self._style_axis(upper, self.i18n.text("progress.metric.weekly_distance"))
            self._style_axis(lower, self.i18n.text("progress.metric.weekly_rides"))
            upper.bar(week_dates, weekly["km"], width=5.0, color=self.theme.text_muted)
            upper.plot(week_dates, weekly["rolling_km"], color=self.theme.route_primary, linewidth=1.8)
            lower.bar(week_dates, weekly["rides"], width=5.0, color=self.theme.text_secondary)
            lower.set_ylim(0, max(weekly["rides"].max() * 1.25, 1))
            x_start = week_dates.iloc[0] - pd.Timedelta(days=4)
            x_end = week_dates.iloc[-1] + pd.Timedelta(days=4)
            months = pd.date_range(
                (week_dates.iloc[0] + pd.Timedelta(days=7)).replace(day=1),
                week_dates.iloc[-1],
                freq="MS",
            )
            for axis in (upper, lower):
                axis.set_xlim(x_start, x_end)
                for month in months:
                    axis.axvline(month, color=self.theme.grid, linewidth=0.65, zorder=0)
            upper.tick_params(labelbottom=False)
            lower.set_xticks(months)
            lower.set_xticklabels([self.i18n.month_short(month) for month in months])

        elif chapter == 3:
            speed = metrics["speed_stats"]
            metric_xs = (0.10, 0.39, 0.68) if not portrait else (0.09, 0.38, 0.67)
            speed_metrics = [
                (self.i18n.text("progress.metric.median_speed"), speed["median"]),
                (self.i18n.text("progress.metric.p90_speed"), speed["p90"]),
                (self.i18n.text("progress.metric.p99_speed"), speed["p99"]),
            ]
            for x, (label, value) in zip(metric_xs, speed_metrics):
                figure.text(x, 0.70, label.upper(), color=self.theme.text_muted, fontsize=10, fontweight="bold")
                displayed = value if metrics["sample_counts"]["speed"] else None
                figure.text(x, 0.65, self._measurement(displayed, "km/h", 1),
                            color=self.theme.text_primary, fontsize=22, fontweight="bold")
            axis = figure.add_axes([chart_rect[0], 0.15, chart_rect[2], 0.40], facecolor=self.theme.canvas)
            histogram = metrics["speed_histogram"]
            edges = np.asarray(histogram["edges"], dtype=float)
            counts = np.asarray(histogram["counts"], dtype=float)
            centers = (edges[:-1] + edges[1:]) / 2.0
            self._style_axis(axis, self.i18n.text("progress.metric.speed_distribution"))
            axis.bar(centers, counts, width=np.diff(edges) * 0.96,
                     color=self.theme.text_muted, edgecolor=self.theme.canvas)
            axis.axvline(speed["median"], color=self.theme.route_primary, linewidth=1.5)
            axis.set_xlabel("km/h", color=self.theme.text_muted, fontsize=10)

        elif chapter == 4:
            heart = metrics["heart_rate_stats"]
            metric_xs = (0.10, 0.39, 0.68) if not portrait else (0.09, 0.38, 0.67)
            heart_metrics = [
                (self.i18n.text("progress.metric.median_hr"), heart["median"]),
                (self.i18n.text("progress.metric.p90_hr"), heart["p90"]),
                (self.i18n.text("progress.metric.peak_hr"), heart["peak"]),
            ]
            for x, (label, value) in zip(metric_xs, heart_metrics):
                figure.text(x, 0.70, label.upper(), color=self.theme.text_muted, fontsize=10, fontweight="bold")
                displayed = value if metrics["sample_counts"]["heart_rate"] else None
                figure.text(x, 0.65, self._measurement(displayed, "bpm"),
                            color=self.theme.text_primary, fontsize=22, fontweight="bold")
            axis = figure.add_axes([chart_rect[0], 0.15, chart_rect[2], 0.40], facecolor=self.theme.canvas)
            zones = metrics["zones_pct"]
            labels, values = list(zones), list(zones.values())
            self._style_axis(axis, self.i18n.text("dashboard.zones"))
            bars = axis.barh(labels, values, height=0.48, color=EFFORT_COLORS)
            axis.invert_yaxis()
            axis.grid(axis="x", color=self.theme.grid, linewidth=0.7)
            axis.grid(axis="y", visible=False)
            maximum_zone = max(values, default=0.0)
            axis.set_xlim(0, maximum_zone * 1.28 if maximum_zone > 0.0 else 1.0)
            for bar, value in zip(bars, values):
                axis.text(value + maximum_zone * 0.025, bar.get_y() + bar.get_height() / 2,
                          f"{value:.1f}%", va="center", color=self.theme.text_secondary, fontsize=11)

        elif chapter == 5:
            hardest = metrics["records"]
            figure.text(0.10 if not portrait else 0.09, 0.71,
                        self.i18n.text("progress.metric.hardest_effort").upper(),
                        color=self.theme.text_muted, fontsize=10, fontweight="bold")
            effort = self._measurement(hardest["highest_effort"])
            effort_name = hardest["highest_effort_name"]
            figure.text(0.10 if not portrait else 0.09, 0.665,
                        f"{effort} · {effort_name}" if effort_name else effort,
                        color=self.theme.text_primary, fontsize=19, fontweight="bold")
            axis = figure.add_axes([chart_rect[0], 0.15, chart_rect[2], 0.40], facecolor=self.theme.canvas)
            values = [metrics["monthly_trimp"].get(row["month"], 0.0) for row in monthly]
            self._style_axis(axis, self.i18n.text("dashboard.trimp"))
            axis.plot(month_labels, values, color=self.theme.text_secondary, linewidth=1.8)
            axis.scatter(month_labels, values, marker="s", s=28, color=self.theme.route_primary, zorder=3)
            maximum_trimp = max(values, default=0.0)
            axis.set_ylim(0, maximum_trimp * 1.22 if maximum_trimp > 0.0 else 1.0)
            for label, value in zip(month_labels, values):
                axis.text(label, value + maximum_trimp * 0.04, f"{value:.0f}", ha="center",
                          color=self.theme.text_secondary, fontsize=11)

        elif chapter == 6:
            records = metrics["records"]
            temperature = metrics["temperature_stats"]
            average_elevation = metrics["total_elev_m"] / max(metrics["total_rides"], 1)
            if temperature["p10"] is None:
                temperature_band = self.i18n.text("value.unavailable")
                temperature_range = ""
            else:
                temperature_band = f"{temperature['p10']}—{temperature['p90']} °C"
                temperature_range = f"{temperature['min']}—{temperature['max']} °C"
            self._metric_grid(figure, [
                (self.i18n.text("progress.metric.total_elevation"), f"{self.i18n.number(metrics['total_elev_m'])} m"),
                (self.i18n.text("progress.metric.average_elevation"), f"{self.i18n.number(average_elevation)} m"),
                (self.i18n.text("dashboard.highest"), f"{self.i18n.number(records['highest_elev_m'])} m", records["highest_elev_name"]),
                (self.i18n.text("progress.metric.temperature_band"), temperature_band, temperature_range),
            ], portrait=portrait)

        elif chapter == 7:
            records = metrics["records"]
            self._metric_grid(figure, [
                (self.i18n.text("dashboard.longest"), f"{self.i18n.number(records['longest_km'], 1)} km", records["longest_name"]),
                (self.i18n.text("progress.metric.fastest_sustained"),
                 self._measurement(records["fastest_sustained_kmh"], "km/h", 1), records["fastest_sustained_name"]),
                (self.i18n.text("progress.metric.hardest_effort"),
                 self._measurement(records["highest_effort"]), records["highest_effort_name"]),
                (self.i18n.text("progress.metric.peak_hr"),
                 self._measurement(records["peak_hr"], "bpm"), records["peak_hr_name"]),
            ], portrait=portrait)

        else:
            figure.text(0.5, 0.58, f"{self.i18n.number(metrics['total_km'], 1)} km",
                        ha="center", color=self.theme.text_primary,
                        fontsize=56 if not portrait else 48, fontweight="bold")
            figure.text(0.5, 0.50,
                        f"{metrics['total_rides']} {self.i18n.text('unit.rides')}  ·  +{self.i18n.number(metrics['total_elev_m'])} m  ·  {self.i18n.number(metrics['total_hours'], 1)} h",
                        ha="center", color=self.theme.text_secondary, fontsize=17)

        figure.canvas.draw()
        rgba = np.frombuffer(figure.canvas.buffer_rgba(), dtype=np.uint8)
        image = Image.fromarray(rgba.reshape((height, width, 4))[:, :, :3])
        plt.close(figure)
        return image

    def render_movie(self, output_mp4_path: Optional[Path] = None, *, width: int = 1920,
                     height: int = 1080, fps: int = 30, chapter_duration_s: float = 3.5,
                     keyframes_dir: Optional[Path] = None,
                     presentation: str = "standard") -> Path:
        output = Path(output_mp4_path or (self.outputs_dir / f"progress_{self.selection.slug()}.mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        keyframes = Path(keyframes_dir) if keyframes_dir else None
        if keyframes:
            keyframes.mkdir(parents=True, exist_ok=True)

        render_width, render_height = safe_content_dimensions(width, height, presentation)
        metrics = self.extract_summary_metrics()
        slides = [
            present_frame(
                place_safe_content(
                    self._render_chapter_slide(chapter, metrics, render_width, render_height),
                    presentation=presentation,
                    background=self.theme.canvas,
                ),
                presentation=presentation,
            )
            for chapter in range(1, self.CHAPTER_COUNT + 1)
        ]
        if keyframes:
            for chapter, slide in enumerate(slides, start=1):
                slide.save(keyframes / f"chapter_{chapter:02d}.png")
        frames_per_chapter = max(1, int(round(chapter_duration_s * fps)))
        total_frames = frames_per_chapter * self.CHAPTER_COUNT
        transition_frames = min(max(1, int(round(0.25 * fps))), max(1, frames_per_chapter // 3))
        keyframe_indices = {0: "00", total_frames // 2: "50", total_frames - 1: "100"}

        with RawVideoEncoder(
            output,
            width=width,
            height=height,
            fps=fps,
            operation="progress movie",
        ) as encoder:
            frame_index = 0
            for chapter_index, slide in enumerate(slides):
                for local_frame in range(frames_per_chapter):
                    frame = slide
                    transition_start = frames_per_chapter - transition_frames
                    if chapter_index < len(slides) - 1 and local_frame >= transition_start:
                        phase = (local_frame - transition_start + 1) / transition_frames
                        eased = phase * phase * (3.0 - 2.0 * phase)
                        frame = Image.blend(slide, slides[chapter_index + 1], eased)
                    if keyframes and frame_index in keyframe_indices:
                        frame.save(keyframes / f"keyframe_{keyframe_indices[frame_index]}pct.png")
                    encoder.write(frame)
                    frame_index += 1
        return output
