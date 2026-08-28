"""Flat, editorial season analytics output."""

from pathlib import Path
from typing import Optional

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ride_visuals.design import EFFORT_COLORS, get_theme
from ride_visuals.i18n import Translator
from ride_visuals.selection import ActivitySelection
from ride_visuals.analytics.progress import SeasonAnalytics


class AnalyticsDashboardGenerator:
    """Generate a high-resolution dashboard using the shared visual system."""

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

    def _style_axis(self, axis, title: str) -> None:
        axis.set_facecolor(self.theme.canvas)
        axis.set_title(title.upper(), color=self.theme.text_secondary, fontsize=12,
                       fontweight="bold", pad=14, loc="left")
        axis.tick_params(colors=self.theme.text_muted, labelsize=11, length=0)
        axis.grid(axis="y", linestyle="-", linewidth=0.7, color=self.theme.grid)
        axis.set_axisbelow(True)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_color(self.theme.border)
        axis.spines["bottom"].set_color(self.theme.border)

    def _month_labels(self, months) -> list[str]:
        multi_year = len(set(str(month)[:4] for month in months)) > 1
        is_dense = len(months) > 16
        step = max(1, len(months) // 8) if is_dense else 1
        labels = []
        for i, month in enumerate(months):
            ts = pd.Timestamp(str(month) + "-01")
            m_str = self.i18n.month_short(ts)
            if multi_year:
                full_label = f"{m_str}/{ts.strftime('%y')}"
            else:
                full_label = m_str
            if is_dense and i % step != 0 and i != len(months) - 1:
                labels.append("")
            else:
                labels.append(full_label)
        return labels

    def generate_dashboard(self, out_path: Optional[Path] = None, dpi: int = 300) -> Path:
        out_path = out_path or (self.outputs_dir / "ride_summary.png")
        where, parameters = self.selection.sql()
        with duckdb.connect(str(self.catalog_db_path), read_only=True) as connection:
            activities = connection.execute(
                "SELECT id, start_date, distance_m, moving_time_s, elevation_gain_m "
                f"FROM activities{where} ORDER BY start_date",
                parameters,
            ).fetchdf()
        if activities.empty:
            raise ValueError("No activities match the selected period")

        activities["month"] = activities["start_date"].dt.strftime("%Y-%m")
        monthly = activities.groupby("month").agg(
            km=("distance_m", lambda values: sum(values) / 1000.0),
            elev=("elevation_gain_m", "sum"),
            rides=("id", "count"),
            time_h=("moving_time_s", lambda values: sum(values) / 3600.0),
        ).reset_index()

        metrics = SeasonAnalytics(
            self.catalog_db_path, self.streams_dir,
            selection=self.selection,
        ).extract()

        fig = plt.figure(figsize=(16, 10), facecolor=self.theme.canvas)
        grid = fig.add_gridspec(2, 3, hspace=0.48, wspace=0.28,
                               left=0.065, right=0.94, top=0.76, bottom=0.09)

        fig.text(0.065, 0.92, self.i18n.text("dashboard.title"),
                 color=self.theme.text_primary, fontsize=28, fontweight="bold")
        subtitle = (
            f"{self.i18n.date(activities['start_date'].min())} — "
            f"{self.i18n.date(activities['start_date'].max())}  ·  "
            f"{metrics['total_rides']} {self.i18n.text('unit.rides')}  ·  "
            f"{self.i18n.number(metrics['total_km'], 1)} km  ·  "
            f"+{self.i18n.number(metrics['total_elev_m'])} m  ·  "
            f"{self.i18n.number(metrics['total_hours'], 1)} h"
        )
        fig.text(0.065, 0.875, subtitle, color=self.theme.text_muted, fontsize=15)
        fig.lines.append(plt.Line2D([0.065, 0.94], [0.835, 0.835], transform=fig.transFigure,
                                    color=self.theme.border, linewidth=0.8))

        months = monthly["month"].values
        month_labels = self._month_labels(months)
        x_indices = np.arange(len(months))
        is_dense = len(months) > 14
        step = max(1, len(months) // 8) if is_dense else 1

        zones_axis = fig.add_subplot(grid[0, 0])
        self._style_axis(zones_axis, self.i18n.text("dashboard.zones"))
        zones = metrics["zones_pct"]
        zone_labels = [key.split()[0] for key in zones.keys()]
        zone_values = list(zones.values())
        bars = zones_axis.barh(zone_labels, zone_values, color=EFFORT_COLORS, height=0.48)
        zones_axis.invert_yaxis()
        zones_axis.grid(axis="x", linestyle="-", linewidth=0.7, color=self.theme.grid)
        zones_axis.grid(axis="y", visible=False)
        for bar, value in zip(bars, zone_values):
            zones_axis.text(value + 0.8, bar.get_y() + bar.get_height() / 2,
                            f"{value:.1f}%", va="center", color=self.theme.text_primary, fontsize=11)

        distance_axis = fig.add_subplot(grid[0, 1])
        self._style_axis(distance_axis, self.i18n.text("dashboard.distance"))
        kms = monthly["km"].values
        distance_colors = [self.theme.text_muted] * max(0, len(kms) - 1) + [self.theme.route_primary]
        distance_bars = distance_axis.bar(x_indices, kms, color=distance_colors, width=0.6 if is_dense else 0.5)
        distance_axis.set_xticks(x_indices)
        distance_axis.set_xticklabels(month_labels)
        if is_dense:
            distance_axis.tick_params(axis="x", rotation=45, labelsize=8)
        for i, (bar, value) in enumerate(zip(distance_bars, kms)):
            if not is_dense or i % step == 0 or i == len(kms) - 1:
                distance_axis.text(bar.get_x() + bar.get_width() / 2, value + max(kms) * 0.035,
                                   f"{value:.0f}", ha="center", color=self.theme.text_secondary,
                                   fontsize=9 if is_dense else 11)
        distance_axis.set_ylim(0, max(kms) * 1.18)

        trimp_axis = fig.add_subplot(grid[0, 2])
        self._style_axis(trimp_axis, self.i18n.text("dashboard.trimp"))
        trimp = [metrics["monthly_trimp"].get(month, 0.0) for month in months]
        trimp_axis.plot(x_indices, trimp, color=self.theme.text_secondary, linewidth=1.8,
                        marker="s", markersize=3 if is_dense else 4, markerfacecolor=self.theme.route_primary,
                        markeredgewidth=0)
        trimp_axis.set_xticks(x_indices)
        trimp_axis.set_xticklabels(month_labels)
        if is_dense:
            trimp_axis.tick_params(axis="x", rotation=45, labelsize=8)
        for i, value in enumerate(trimp):
            if not is_dense or i % step == 0 or i == len(trimp) - 1:
                trimp_axis.text(x_indices[i], value + max(trimp) * 0.045, f"{value:.0f}", ha="center",
                                color=self.theme.text_secondary, fontsize=9 if is_dense else 11)
        trimp_axis.set_ylim(0, max(trimp) * 1.2)

        ascent_axis = fig.add_subplot(grid[1, 0])
        self._style_axis(ascent_axis, self.i18n.text("dashboard.ascent"))
        ascent = monthly["elev"].values
        ascent_bars = ascent_axis.bar(x_indices, ascent, color=self.theme.text_secondary, width=0.6 if is_dense else 0.5)
        ascent_bars[-1].set_color(self.theme.route_primary)
        ascent_axis.set_xticks(x_indices)
        ascent_axis.set_xticklabels(month_labels)
        if is_dense:
            ascent_axis.tick_params(axis="x", rotation=45, labelsize=8)
        for i, (bar, value) in enumerate(zip(ascent_bars, ascent)):
            if not is_dense or i % step == 0 or i == len(ascent) - 1:
                ascent_axis.text(bar.get_x() + bar.get_width() / 2, value + max(ascent) * 0.035,
                                 f"{value:,.0f}", ha="center", color=self.theme.text_secondary,
                                 fontsize=8 if is_dense else 10)
        ascent_axis.set_ylim(0, max(ascent) * 1.2)

        time_axis = fig.add_subplot(grid[1, 1])
        self._style_axis(time_axis, self.i18n.text("dashboard.time"))
        hours = monthly["time_h"].values
        time_axis.plot(x_indices, hours, color=self.theme.text_secondary, linewidth=1.8)
        time_axis.scatter(x_indices, hours, marker="s", s=16 if is_dense else 24, color=self.theme.route_primary, zorder=3)
        time_axis.set_xticks(x_indices)
        time_axis.set_xticklabels(month_labels)
        if is_dense:
            time_axis.tick_params(axis="x", rotation=45, labelsize=8)
        for i, value in enumerate(hours):
            if not is_dense or i % step == 0 or i == len(hours) - 1:
                time_axis.text(x_indices[i], value + max(hours) * 0.045, f"{value:.1f}", ha="center",
                               color=self.theme.text_secondary, fontsize=9 if is_dense else 11)
        time_axis.set_ylim(0, max(hours) * 1.2)

        records_axis = fig.add_subplot(grid[1, 2])
        records_axis.set_facecolor(self.theme.canvas)
        records_axis.axis("off")
        records_axis.set_title(self.i18n.text("dashboard.records").upper(),
                               color=self.theme.text_secondary, fontsize=12,
                               fontweight="bold", pad=14, loc="left")
        records = metrics["records"]
        fastest = records["fastest_sustained_kmh"]
        peak_hr = records["peak_hr"]
        rows = [
            (self.i18n.text("dashboard.longest"), f"{records['longest_km']:.1f} km"),
            (self.i18n.text("dashboard.highest"), f"{records['highest_elev_m']:,.0f} m"),
            (
                self.i18n.text("dashboard.fastest_sustained"),
                f"{fastest:.1f} km/h" if fastest is not None else self.i18n.text("value.unavailable"),
            ),
            (
                self.i18n.text("dashboard.peak_hr"),
                f"{peak_hr:.0f} bpm" if peak_hr is not None else self.i18n.text("value.unavailable"),
            ),
        ]
        for index, (label, value) in enumerate(rows):
            y = 0.9 - index * 0.23
            records_axis.plot([0, 1], [y, y], transform=records_axis.transAxes,
                              color=self.theme.border, linewidth=0.8)
            records_axis.text(0, y - 0.08, label.upper(), color=self.theme.text_muted,
                              fontsize=10, fontweight="bold", transform=records_axis.transAxes)
            records_axis.text(1, y - 0.09, value, color=self.theme.text_primary,
                              fontsize=19, fontweight="bold", ha="right",
                              transform=records_axis.transAxes)

        plt.savefig(out_path, dpi=dpi, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        return out_path
