"""Editorial season-progress film built from lossless activity metrics."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from PIL import Image

from ride_visuals.analytics.climbs import ClimbAnalyzer
from ride_visuals.analytics.drift import DriftAnalyzer
from ride_visuals.analytics.trimp import TRIMPAnalyzer
from ride_visuals.analytics.zones import HRZoneProfile
from ride_visuals.design import EFFORT_COLORS, get_theme
from ride_visuals.i18n import Translator, sanitize_display_text
from ride_visuals.selection import ActivitySelection


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
        where, parameters = self.selection.sql()
        with duckdb.connect(str(self.catalog_db_path), read_only=True) as connection:
            activities = connection.execute(
                f"SELECT * FROM activities{where} ORDER BY start_date", parameters
            ).fetchdf()
        if activities.empty:
            raise ValueError("No activities match the selected period")

        total_rides = len(activities)
        total_km = float(activities["distance_m"].sum() / 1000.0)
        total_elevation = float(activities["elevation_gain_m"].sum())
        total_hours = float(activities["moving_time_s"].sum() / 3600.0)

        activities["month"] = activities["start_date"].dt.strftime("%Y-%m")
        monthly = activities.groupby("month").agg(
            rides=("id", "count"),
            km=("distance_m", lambda values: float(values.sum() / 1000.0)),
            elev=("elevation_gain_m", "sum"),
            hours=("moving_time_s", lambda values: float(values.sum() / 3600.0)),
            avg_hr=("avg_heart_rate", "mean"),
        ).reset_index()

        activities["week_start"] = (
            activities["start_date"]
            - pd.to_timedelta(activities["start_date"].dt.weekday, unit="D")
        ).dt.normalize()
        weekly = activities.groupby("week_start").agg(
            rides=("id", "count"),
            km=("distance_m", lambda values: float(values.sum() / 1000.0)),
        )
        complete_weeks = pd.date_range(
            activities["week_start"].min(),
            activities["week_start"].max(),
            freq="7D",
        )
        weekly = weekly.reindex(complete_weeks, fill_value=0).rename_axis("week_start").reset_index()
        weekly["rolling_km"] = weekly["km"].rolling(4, min_periods=1).mean()
        weekly["week_start"] = weekly["week_start"].dt.strftime("%Y-%m-%d")

        all_heart_rates: list[float] = []
        all_speeds_kmh: list[float] = []
        all_temperatures: list[float] = []
        drifts: list[float] = []
        climbs: list[dict[str, float]] = []
        rides_with_hr = 0
        trimp_analyzer = TRIMPAnalyzer()
        monthly_trimp = {month: 0.0 for month in monthly["month"]}

        for _, activity in activities.iterrows():
            stream_path = self.streams_dir / f"{activity['id']}.parquet"
            if not stream_path.exists():
                continue
            stream = pq.read_table(
                stream_path,
                columns=["heart_rate_bpm", "speed_mps", "temperature_c", "altitude", "timestamp"],
            ).to_pandas()
            heart_rates = stream["heart_rate_bpm"].dropna().values
            if len(heart_rates):
                rides_with_hr += 1
                all_heart_rates.extend(heart_rates)
            speeds_kmh = stream["speed_mps"].dropna().values * 3.6
            all_speeds_kmh.extend(speeds_kmh[np.isfinite(speeds_kmh)])
            temperatures = stream["temperature_c"].dropna().values
            all_temperatures.extend(temperatures[np.isfinite(temperatures)])

            drift = DriftAnalyzer.calculate_aerobic_drift(
                stream["speed_mps"].values,
                stream["heart_rate_bpm"].values,
            )
            if drift["valid"]:
                drifts.append(float(drift["drift_pct"]))

            timestamps = stream["timestamp"].astype("int64").values / 1e9
            climbs.extend(ClimbAnalyzer.calculate_climb_vam(stream["altitude"].values, timestamps))

            month = activity["month"]
            monthly_trimp[month] = monthly_trimp.get(month, 0.0) + trimp_analyzer.calculate_activity_trimp(
                heart_rates,
                activity["moving_time_s"] / 60.0,
            )

        zone_distribution = HRZoneProfile().calculate_time_in_zones(np.asarray(all_heart_rates))
        speed_samples = np.asarray(all_speeds_kmh, dtype=float)
        heart_rate_samples = np.asarray(all_heart_rates, dtype=float)
        temperature_samples = np.asarray(all_temperatures, dtype=float)
        speed_hist_counts, speed_hist_edges = np.histogram(
            speed_samples[(speed_samples >= 0) & (speed_samples <= 70)],
            bins=np.linspace(0, 70, 15),
        )
        longest = activities.sort_values("distance_m", ascending=False).iloc[0]
        highest = activities.sort_values("elevation_gain_m", ascending=False).iloc[0]
        fastest = activities.sort_values("max_speed_mps", ascending=False).iloc[0]
        sustained = activities[activities["distance_m"] >= 20_000].sort_values("avg_speed_mps", ascending=False).iloc[0]
        hardest = activities.dropna(subset=["relative_effort"]).sort_values("relative_effort", ascending=False).iloc[0]
        highest_hr = activities.dropna(subset=["max_heart_rate"]).sort_values("max_heart_rate", ascending=False).iloc[0]

        return {
            "total_rides": total_rides,
            "total_km": round(total_km, 1),
            "total_elev_m": round(total_elevation),
            "total_hours": round(total_hours, 1),
            "rides_with_hr": rides_with_hr,
            "sample_counts": {
                "total": int(activities["point_count"].fillna(0).sum()),
                "speed": int(len(speed_samples)),
                "heart_rate": int(len(heart_rate_samples)),
                "temperature": int(len(temperature_samples)),
            },
            "activity_avg_speeds_kmh": [
                float(value * 3.6) for value in activities["avg_speed_mps"].dropna().values
            ],
            "speed_stats": {
                "median": round(float(np.percentile(speed_samples, 50)), 1),
                "p90": round(float(np.percentile(speed_samples, 90)), 1),
                "peak": round(float(activities["max_speed_mps"].max() * 3.6), 1),
            },
            "speed_histogram": {
                "counts": speed_hist_counts.tolist(),
                "edges": speed_hist_edges.tolist(),
            },
            "heart_rate_stats": {
                "median": round(float(np.percentile(heart_rate_samples, 50))),
                "p90": round(float(np.percentile(heart_rate_samples, 90))),
                "peak": round(float(activities["max_heart_rate"].max())),
            },
            "temperature_stats": {
                "p10": round(float(np.percentile(temperature_samples, 10))),
                "p90": round(float(np.percentile(temperature_samples, 90))),
                "min": round(float(np.min(temperature_samples))),
                "max": round(float(np.max(temperature_samples))),
            },
            "monthly": monthly.to_dict(orient="records"),
            "weekly": weekly.to_dict(orient="records"),
            "monthly_trimp": monthly_trimp,
            "zones_pct": {f"Z{index}": zone_distribution[f"z{index}_pct"] for index in range(1, 6)},
            "avg_drift_pct": round(float(np.mean(drifts)), 2) if drifts else 0.0,
            "top_climbs_count": len(climbs),
            "avg_climb_vam": round(float(np.mean([climb["vam_mh"] for climb in climbs])), 1) if climbs else 0.0,
            "records": {
                "longest_km": round(float(longest["distance_m"]) / 1000.0, 1),
                "longest_name": sanitize_display_text(longest["name"]),
                "highest_elev_m": round(float(highest["elevation_gain_m"])),
                "highest_elev_name": sanitize_display_text(highest["name"]),
                "max_speed_kmh": round(float(fastest["max_speed_mps"]) * 3.6, 1)
                if pd.notna(fastest["max_speed_mps"]) else 0.0,
                "max_speed_name": sanitize_display_text(fastest["name"]),
                "fastest_sustained_kmh": round(float(sustained["avg_speed_mps"]) * 3.6, 1),
                "fastest_sustained_name": sanitize_display_text(sustained["name"]),
                "highest_effort": round(float(hardest["relative_effort"])),
                "highest_effort_name": sanitize_display_text(hardest["name"]),
                "peak_hr": round(float(highest_hr["max_heart_rate"])),
                "peak_hr_name": sanitize_display_text(highest_hr["name"]),
            },
        }

    def _month_labels(self, monthly: list[dict[str, Any]]) -> list[str]:
        return [self.i18n.month_short(pd.Timestamp(f"{row['month']}-01")) for row in monthly]

    def _new_figure(self, width: int, height: int, chapter: int, title: str):
        dpi = 100
        figure = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=self.theme.canvas)
        portrait = height > width
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
                (self.i18n.text("progress.metric.peak_speed"), speed["peak"]),
            ]
            for x, (label, value) in zip(metric_xs, speed_metrics):
                figure.text(x, 0.70, label.upper(), color=self.theme.text_muted, fontsize=10, fontweight="bold")
                figure.text(x, 0.65, f"{self.i18n.number(value, 1)} km/h",
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
                figure.text(x, 0.65, f"{self.i18n.number(value)} bpm",
                            color=self.theme.text_primary, fontsize=22, fontweight="bold")
            axis = figure.add_axes([chart_rect[0], 0.15, chart_rect[2], 0.40], facecolor=self.theme.canvas)
            zones = metrics["zones_pct"]
            labels, values = list(zones), list(zones.values())
            self._style_axis(axis, self.i18n.text("dashboard.zones"))
            bars = axis.barh(labels, values, height=0.48, color=EFFORT_COLORS)
            axis.invert_yaxis()
            axis.grid(axis="x", color=self.theme.grid, linewidth=0.7)
            axis.grid(axis="y", visible=False)
            axis.set_xlim(0, max(values) * 1.28)
            for bar, value in zip(bars, values):
                axis.text(value + max(values) * 0.025, bar.get_y() + bar.get_height() / 2,
                          f"{value:.1f}%", va="center", color=self.theme.text_secondary, fontsize=11)

        elif chapter == 5:
            hardest = metrics["records"]
            figure.text(0.10 if not portrait else 0.09, 0.71,
                        self.i18n.text("progress.metric.hardest_effort").upper(),
                        color=self.theme.text_muted, fontsize=10, fontweight="bold")
            figure.text(0.10 if not portrait else 0.09, 0.665,
                        f"{self.i18n.number(hardest['highest_effort'])} · {hardest['highest_effort_name']}",
                        color=self.theme.text_primary, fontsize=19, fontweight="bold")
            axis = figure.add_axes([chart_rect[0], 0.15, chart_rect[2], 0.40], facecolor=self.theme.canvas)
            values = [metrics["monthly_trimp"].get(row["month"], 0.0) for row in monthly]
            self._style_axis(axis, self.i18n.text("dashboard.trimp"))
            axis.plot(month_labels, values, color=self.theme.text_secondary, linewidth=1.8)
            axis.scatter(month_labels, values, marker="s", s=28, color=self.theme.route_primary, zorder=3)
            axis.set_ylim(0, max(values) * 1.22)
            for label, value in zip(month_labels, values):
                axis.text(label, value + max(values) * 0.04, f"{value:.0f}", ha="center",
                          color=self.theme.text_secondary, fontsize=11)

        elif chapter == 6:
            records = metrics["records"]
            temperature = metrics["temperature_stats"]
            average_elevation = metrics["total_elev_m"] / max(metrics["total_rides"], 1)
            self._metric_grid(figure, [
                (self.i18n.text("progress.metric.total_elevation"), f"{self.i18n.number(metrics['total_elev_m'])} m"),
                (self.i18n.text("progress.metric.average_elevation"), f"{self.i18n.number(average_elevation)} m"),
                (self.i18n.text("dashboard.highest"), f"{self.i18n.number(records['highest_elev_m'])} m", records["highest_elev_name"]),
                (self.i18n.text("progress.metric.temperature_band"), f"{temperature['p10']}—{temperature['p90']} °C",
                 f"{temperature['min']}—{temperature['max']} °C"),
            ], portrait=portrait)

        elif chapter == 7:
            records = metrics["records"]
            self._metric_grid(figure, [
                (self.i18n.text("dashboard.longest"), f"{self.i18n.number(records['longest_km'], 1)} km", records["longest_name"]),
                (self.i18n.text("progress.metric.fastest_sustained"),
                 f"{self.i18n.number(records['fastest_sustained_kmh'], 1)} km/h", records["fastest_sustained_name"]),
                (self.i18n.text("dashboard.max_speed"), f"{self.i18n.number(records['max_speed_kmh'], 1)} km/h", records["max_speed_name"]),
                (self.i18n.text("progress.metric.peak_hr"), f"{self.i18n.number(records['peak_hr'])} bpm", records["peak_hr_name"]),
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
                     keyframes_dir: Optional[Path] = None) -> Path:
        output = Path(output_mp4_path or (self.outputs_dir / f"progress_{self.selection.slug()}.mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        keyframes = Path(keyframes_dir) if keyframes_dir else None
        if keyframes:
            keyframes.mkdir(parents=True, exist_ok=True)

        metrics = self.extract_summary_metrics()
        slides = [self._render_chapter_slide(chapter, metrics, width, height)
                  for chapter in range(1, self.CHAPTER_COUNT + 1)]
        if keyframes:
            for chapter, slide in enumerate(slides, start=1):
                slide.save(keyframes / f"chapter_{chapter:02d}.png")
        frames_per_chapter = max(1, int(round(chapter_duration_s * fps)))
        total_frames = frames_per_chapter * self.CHAPTER_COUNT
        transition_frames = min(max(1, int(round(0.25 * fps))), max(1, frames_per_chapter // 3))
        keyframe_indices = {0: "00", total_frames // 2: "50", total_frames - 1: "100"}

        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{width}x{height}", "-pix_fmt", "rgb24", "-r", str(fps), "-i", "-",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(output),
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        # Drain stderr concurrently so ffmpeg output can never fill the pipe
        # buffer and dead-lock the frame writer below.
        stderr_sink = []
        assert process.stderr is not None
        threading.Thread(
            target=lambda: stderr_sink.append(process.stderr.read()), daemon=True
        ).start()
        assert process.stdin is not None

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
                process.stdin.write(frame.tobytes())
                frame_index += 1

        process.stdin.close()
        process.wait()
        if process.returncode != 0:
            error = b"".join(stderr_sink).decode("utf-8", errors="replace")
            raise RuntimeError(f"FFmpeg progress movie error: {error}")
        return output
