"""Aligned small-multiple timeline for the complete activity season."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from ride_visuals.design import get_theme
from ride_visuals.i18n import Translator
from ride_visuals.selection import ActivitySelection


class SeasonTimelineGenerator:
    """Render heterogeneous telemetry on a shared calendar without mixing units."""

    def __init__(self, catalog_db_path: Path, outputs_dir: Path, *,
                 locale: str = "pt-BR", theme: str = "midnight",
                 selection: ActivitySelection | None = None):
        self.catalog_db_path = Path(catalog_db_path)
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.i18n = Translator(locale)
        self.theme = get_theme(theme)
        self.selection = selection or ActivitySelection()

    def load_frame(self) -> pd.DataFrame:
        with duckdb.connect(str(self.catalog_db_path), read_only=True) as connection:
            columns = {row[0] for row in connection.execute("DESCRIBE activities").fetchall()}
            name_expression = "name" if "name" in columns else "NULL::VARCHAR AS name"
            where, parameters = self.selection.sql()
            frame = connection.execute(
                f"SELECT id, {name_expression}, start_date, distance_m, elevation_gain_m, moving_time_s, "
                "avg_speed_mps, avg_heart_rate, temperature_avg, point_count, "
                "has_hr_stream, has_temp_stream "
                f"FROM activities{where} ORDER BY start_date",
                parameters,
            ).fetchdf()
        if frame.empty:
            raise ValueError("No activities are available for the season timeline")
        frame["distance_km"] = frame["distance_m"] / 1000.0
        frame["cumulative_km"] = frame["distance_km"].cumsum()
        frame["average_speed_kmh"] = frame["avg_speed_mps"] * 3.6
        return frame

    def _style_axis(self, axis, label: str, *, show_x: bool) -> None:
        axis.set_facecolor(self.theme.canvas)
        axis.text(0.0, 0.92, label.upper(), transform=axis.transAxes,
                  color=self.theme.text_muted, fontsize=10, fontweight="bold",
                  bbox={"facecolor": self.theme.canvas, "edgecolor": "none", "pad": 2.0},
                  zorder=8)
        axis.tick_params(colors=self.theme.text_muted, labelsize=10, length=0, pad=7)
        axis.grid(axis="y", color=self.theme.grid, linewidth=0.65)
        axis.set_axisbelow(True)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color(self.theme.border)
        axis.spines["bottom"].set_color(self.theme.border if show_x else self.theme.canvas)
        if not show_x:
            axis.tick_params(labelbottom=False)

    @staticmethod
    def _finite_max(values: pd.Series) -> Optional[int]:
        finite = values.dropna()
        return int(finite.idxmax()) if len(finite) else None

    def generate(self, out_path: Optional[Path] = None, *, width: int = 1920,
                 height: int = 1080, animation_base: bool = False) -> Path:
        locale_tag = self.i18n.locale.lower().replace("-", "_")
        output = Path(out_path or (
            self.outputs_dir / f"ride_telemetry_timeline_{locale_tag}_{'9_16' if height > width else '16_9'}.png"
        ))
        output.parent.mkdir(parents=True, exist_ok=True)
        frame = self.load_frame()
        dates = pd.to_datetime(frame["start_date"], utc=True).dt.tz_convert(None)
        start, end = dates.iloc[0], dates.iloc[-1]
        portrait = height > width
        base_height = 1920 if portrait else 1080
        dpi = max(30, int(round(120.0 * (height / base_height))))
        figure = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=self.theme.canvas)

        left, right = (0.12, 0.92) if portrait else (0.095, 0.95)
        figure.text(left, 0.938, self.i18n.text("timeline.title"),
                    color=self.theme.text_primary, fontsize=24 if not portrait else 22,
                    fontweight="bold")
        figure.text(
            left,
            0.898,
            f"{self.i18n.date(start)} — {self.i18n.date(end)}",
            color=self.theme.text_muted,
            fontsize=11,
        )
        figure.lines.append(plt.Line2D([left, right], [0.870, 0.870], transform=figure.transFigure,
                                       color=self.theme.border, linewidth=0.8))

        summary = [
            (self.i18n.text("progress.metric.total_rides"), self.i18n.number(len(frame))),
            (self.i18n.text("progress.metric.total_distance"), f"{self.i18n.number(frame['distance_km'].sum(), 1)} km"),
            (self.i18n.text("progress.metric.samples"), self.i18n.number(frame["point_count"].fillna(0).sum())),
            (self.i18n.text("progress.metric.hr_coverage"), f"{int(frame['has_hr_stream'].fillna(False).sum())} / {len(frame)}"),
        ]
        summary_columns = 2 if portrait else len(summary)
        summary_width = (right - left) / summary_columns
        for index, (label, value) in enumerate(summary):
            row = index // summary_columns
            column = index % summary_columns
            x = left + column * summary_width
            label_y = (0.848 - row * 0.080) if portrait else 0.840
            value_y = (0.810 - row * 0.080) if portrait else 0.800
            figure.text(x + 0.008, label_y, label.upper(), color=self.theme.text_muted,
                        fontsize=9, fontweight="bold")
            if not animation_base:
                figure.text(x + 0.008, value_y, value, color=self.theme.text_primary,
                            fontsize=18, fontweight="bold")
        if portrait:
            midpoint = left + summary_width
            figure.lines.append(plt.Line2D([midpoint, midpoint], [0.715, 0.860], transform=figure.transFigure,
                                           color=self.theme.border, linewidth=0.7))
            figure.lines.append(plt.Line2D([left, right], [0.785, 0.785], transform=figure.transFigure,
                                           color=self.theme.border, linewidth=0.7))
        else:
            for index in range(1, len(summary)):
                x = left + index * summary_width
                figure.lines.append(plt.Line2D([x, x], [0.785, 0.855], transform=figure.transFigure,
                                               color=self.theme.border, linewidth=0.7))

        grid = figure.add_gridspec(
            6, 1,
            left=left, right=right, top=0.670 if portrait else 0.730, bottom=0.095,
            height_ratios=[1.65, 1, 1, 1, 1, 1],
            hspace=0.18,
        )
        axes = [figure.add_subplot(grid[index, 0]) for index in range(6)]
        labels = [
            self.i18n.text("timeline.cumulative_distance"),
            self.i18n.text("timeline.ride_distance"),
            self.i18n.text("timeline.elevation_gain"),
            self.i18n.text("timeline.average_speed"),
            self.i18n.text("timeline.average_hr"),
            self.i18n.text("timeline.temperature"),
        ]
        total_months = max(1, (end.year - start.year) * 12 + (end.month - start.month) + 1)
        if total_months <= 14:
            freq = "MS"
            month_ticks = pd.date_range(start.normalize().replace(day=1), end, freq=freq)
            month_ticks = pd.DatetimeIndex([max(month, start) for month in month_ticks])
            tick_labels = [self.i18n.month_short(month) for month in month_ticks]
        elif total_months <= 30:
            freq = "3MS"
            month_ticks = pd.date_range(start.normalize().replace(day=1), end, freq=freq)
            month_ticks = pd.DatetimeIndex([max(month, start) for month in month_ticks])
            tick_labels = [
                f"{self.i18n.month_short(month)} '{str(month.year)[2:]}" if month.month == 1 else self.i18n.month_short(month)
                for month in month_ticks
            ]
        elif total_months <= 60:
            freq = "6MS"
            month_ticks = pd.date_range(start.normalize().replace(day=1), end, freq=freq)
            month_ticks = pd.DatetimeIndex([max(month, start) for month in month_ticks])
            tick_labels = [
                f"{self.i18n.month_short(month)} '{str(month.year)[2:]}"
                for month in month_ticks
            ]
        else:
            freq = "YS"
            month_ticks = pd.date_range(start.normalize().replace(month=1, day=1), end, freq=freq)
            month_ticks = pd.DatetimeIndex([max(month, start) for month in month_ticks])
            tick_labels = [str(month.year) for month in month_ticks]

        for index, (axis, label) in enumerate(zip(axes, labels)):
            self._style_axis(axis, label, show_x=index == len(axes) - 1)
            axis.set_xlim(start - pd.Timedelta(days=3), end + pd.Timedelta(days=3))
            for tick in month_ticks:
                axis.axvline(tick, color=self.theme.grid, linewidth=0.65, zorder=0)

        # Full-season line first; square markers call out the current/latest state.
        axes[0].plot(dates, frame["cumulative_km"], color=self.theme.text_secondary, linewidth=1.8)
        if not animation_base:
            axes[0].scatter([dates.iloc[-1]], [frame["cumulative_km"].iloc[-1]],
                            marker="s", s=28, color=self.theme.route_primary, zorder=4)
        axes[0].set_ylim(0, frame["cumulative_km"].max() * 1.10)

        bar_width = 1.35
        axes[1].bar(dates, frame["distance_km"], width=bar_width, color=self.theme.text_secondary)
        axes[2].bar(dates, frame["elevation_gain_m"], width=bar_width, color=self.theme.text_muted)

        line_specs = [
            (axes[3], frame["average_speed_kmh"], self.theme.text_secondary, self.theme.route_primary),
            (axes[4], frame["avg_heart_rate"], self.theme.text_secondary, self.theme.heart_rate),
            (axes[5], frame["temperature_avg"], self.theme.text_muted, self.theme.route_primary),
        ]
        for axis, values, line_color, highlight in line_specs:
            axis.plot(dates, values, color=line_color, linewidth=1.15, marker="s", markersize=2.5)
            maximum = self._finite_max(values)
            if maximum is not None and not animation_base:
                axis.scatter([dates.iloc[maximum]], [values.iloc[maximum]], marker="s",
                             s=26, color=highlight, zorder=5)

        axes[-1].set_xticks(month_ticks)
        axes[-1].set_xticklabels(tick_labels, color=self.theme.text_muted, fontsize=10)

        if not animation_base:
            for axis in axes:
                axis.axvline(end, color=self.theme.route_primary, linewidth=0.9, alpha=0.70)

        if not animation_base:
            figure.text(right, 0.035, f"{self.i18n.number(len(frame))} / {self.i18n.number(len(frame))}",
                        ha="right", color=self.theme.text_muted, fontsize=10, fontweight="bold")
        figure.lines.append(plt.Line2D([left, right], [0.055, 0.055], transform=figure.transFigure,
                                       color=self.theme.border, linewidth=1.0))
        if not animation_base:
            figure.lines.append(plt.Line2D([left, right], [0.055, 0.055], transform=figure.transFigure,
                                           color=self.theme.route_primary, linewidth=2.0))

        figure.savefig(output, dpi=dpi, facecolor=figure.get_facecolor(), edgecolor="none")
        plt.close(figure)
        with Image.open(output) as rendered:
            rendered.convert("RGB").save(output)
        return output
