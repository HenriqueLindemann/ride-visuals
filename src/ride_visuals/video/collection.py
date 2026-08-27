"""Gerador de vídeos de coleção completa com Supersampling Anti-Aliasing 2x (SSAA)."""

import math
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from PIL import Image, ImageColor, ImageDraw, ImageEnhance

from ride_visuals.design import (
    ALTITUDE_COLORS,
    EFFORT_COLORS,
    GRADE_COLORS,
    SPEED_COLORS,
    TEMPERATURE_COLORS,
    get_theme,
    route_color,
)
from ride_visuals.ingest.metrics import haversine_distance
from ride_visuals.i18n import Translator, sanitize_display_text
from ride_visuals.video.layout import VideoPartitionLayout
from ride_visuals.video.fonts import FontManager
from ride_visuals.video.dashboard import DashboardPainter
from ride_visuals.maps.tiles import TILE_PROVIDERS, TileManager
from ride_visuals.privacy import load_privacy_zones
from ride_visuals.selection import ActivitySelection


def project_mercator(lon: float, lat: float) -> Tuple[float, float]:
    r_major = 6378137.0
    x = r_major * math.radians(lon)
    lat_rad = math.radians(max(min(lat, 89.5), -89.5))
    y = 3189068.5 * math.log((1.0 + math.sin(lat_rad)) / (1.0 - math.sin(lat_rad)))
    return x, y


def unproject_mercator(x: float, y: float) -> Tuple[float, float]:
    """Invert the collection's spherical Mercator projection."""
    r_major = 6378137.0
    lon = math.degrees(x / r_major)
    lat = math.degrees(2.0 * math.atan(math.exp(y / r_major)) - math.pi / 2.0)
    return lon, lat


DATA_STYLE_SPECS: Dict[str, Dict[str, Any]] = {
    "heart_rate": {
        "field": "point_hrs",
        "thresholds": (132.0, 150.0, 165.0, 175.0),
        "colors": EFFORT_COLORS,
        "labels": ("<132", "132–149", "150–164", "165–174", "≥175"),
        "legend_key": "collection.legend.effort",
    },
    "temperature": {
        "field": "point_temperatures",
        "thresholds": (15.0, 20.0, 25.0, 30.0),
        "colors": TEMPERATURE_COLORS,
        "labels": ("<15", "15–19", "20–24", "25–29", "≥30"),
        "legend_key": "collection.legend.temperature",
    },
    "speed": {
        "field": "point_speeds_kmh",
        "thresholds": (15.0, 22.0, 28.0, 35.0),
        "colors": SPEED_COLORS,
        "labels": ("<15", "15–21", "22–27", "28–34", "≥35"),
        "legend_key": "collection.legend.speed",
    },
    "grade": {
        "field": "point_grades",
        "thresholds": (-5.0, -1.0, 1.0, 5.0),
        "colors": GRADE_COLORS,
        "labels": ("<−5", "−5–−1", "−1–1", "1–5", "≥5"),
        "legend_key": "collection.legend.grade",
    },
    "altitude": {
        "field": "point_altitudes",
        "thresholds": (150.0, 250.0, 350.0, 425.0),
        "colors": ALTITUDE_COLORS,
        "labels": ("<150", "150–249", "250–349", "350–424", "≥425"),
        "legend_key": "collection.legend.altitude",
    },
}

def route_metric_color(style: str, value: Optional[float]) -> Optional[str]:
    """Return the discrete semantic color for one recorded route sample."""
    if style not in DATA_STYLE_SPECS:
        raise ValueError(f"Unsupported data route style: {style}")
    if value is None or not np.isfinite(value):
        return None
    spec = DATA_STYLE_SPECS[style]
    index = int(np.searchsorted(spec["thresholds"], float(value), side="right"))
    return str(spec["colors"][index])


def elapsed_point_count(elapsed_seconds: np.ndarray, cursor_seconds: float) -> int:
    """Number of samples visible at an elapsed-time cursor."""
    if len(elapsed_seconds) == 0 or cursor_seconds < 0:
        return 0
    return int(np.searchsorted(elapsed_seconds, cursor_seconds, side="right"))


def draw_dashed_path(draw: ImageDraw.ImageDraw, points: List[Tuple[int, int]], *,
                     fill: str, width: int, dash: int, gap: int) -> None:
    """Draw a distance-based dashed polyline, independent of sample density."""
    period = dash + gap
    distance_along = 0.0
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        segment_length = math.hypot(dx, dy)
        if segment_length == 0:
            continue
        cursor = 0.0
        while cursor < segment_length:
            phase = distance_along % period
            drawing = phase < dash
            run = (dash - phase) if drawing else (period - phase)
            step = min(run, segment_length - cursor)
            if drawing and step > 0:
                t0 = cursor / segment_length
                t1 = (cursor + step) / segment_length
                draw.line(
                    [
                        (round(start[0] + dx * t0), round(start[1] + dy * t0)),
                        (round(start[0] + dx * t1), round(start[1] + dy * t1)),
                    ],
                    fill=fill,
                    width=width,
                )
            cursor += step
            distance_along += step


class CollectionVideoRenderer:
    """Render all selected routes with optional 2x supersampling."""

    def __init__(self,
                 catalog_db_path: Path,
                 streams_dir: Path,
                 outputs_dir: Path,
                 privacy_zones_path: Optional[Path] = None,
                 locale: str = "pt-BR",
                 theme: str = "midnight",
                 selection: Optional[ActivitySelection] = None):
        self.catalog_db_path = Path(catalog_db_path)
        self.streams_dir = Path(streams_dir)
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.privacy_zones = load_privacy_zones(privacy_zones_path)
        self.i18n = Translator(locale)
        self.theme = get_theme(theme)
        self.tile_manager = TileManager()
        self.selection = selection or ActivitySelection()

    def _is_masked(self, lat: float, lon: float) -> bool:
        for z in self.privacy_zones:
            if haversine_distance(lat, lon, z["lat"], z["lon"]) <= z["radius_m"]:
                return True
        return False

    def _season_stats(self, tracks: List[Dict[str, Any]], position: float) -> Dict[str, Any]:
        """Return continuously evolving season metrics for a fractional ride index."""
        total = len(tracks)
        clamped = min(max(float(position), 0.0), float(total))
        completed = min(int(math.floor(clamped)), total)
        fraction = clamped - completed if completed < total else 0.0
        current_index = min(completed, total - 1)
        current = tracks[current_index]
        completed_tracks = tracks[:completed]

        distance_km = sum(float(track["dist_km"]) for track in completed_tracks)
        elevation_m = sum(float(track["elev_m"]) for track in completed_tracks)
        if fraction > 0.0:
            distance_km += float(current["dist_km"]) * fraction
            elevation_m += float(current["elev_m"]) * fraction

        current_timestamp = pd.Timestamp(current["date"])
        current_month = (current_timestamp.year, current_timestamp.month)
        month_distance_km = sum(
            float(track["dist_km"])
            for track in completed_tracks
            if (pd.Timestamp(track["date"]).year, pd.Timestamp(track["date"]).month) == current_month
        )
        if fraction > 0.0:
            month_distance_km += float(current["dist_km"]) * fraction

        distances_so_far = [float(track["dist_km"]) for track in completed_tracks]
        if fraction > 0.0:
            distances_so_far.append(float(current["dist_km"]) * fraction)
        effective_count = completed + fraction

        return {
            "position": clamped,
            "completed": completed,
            "fraction": fraction,
            "date": self.i18n.date(current["date"]),
            "ride_name": sanitize_display_text(
                current.get("name") or self.i18n.text("activity.default")
            ),
            "distance_km": distance_km,
            "elevation_m": elevation_m,
            "month_distance_km": month_distance_km,
            "average_ride_km": distance_km / effective_count if effective_count > 0.0 else 0.0,
            "longest_so_far_km": max(distances_so_far, default=0.0),
        }

    def load_all_collection_tracks(self) -> List[Dict[str, Any]]:
        where, parameters = self.selection.sql()
        con = duckdb.connect(str(self.catalog_db_path), read_only=True)
        df_acts = con.execute(
            f"SELECT id, name, start_date, distance_m, elevation_gain_m FROM activities{where} ORDER BY start_date",
            parameters,
        ).fetchdf()
        con.close()

        tracks = []
        for _, row in df_acts.iterrows():
            act_id = row["id"]
            dt = row["start_date"]
            p_file = self.streams_dir / f"{act_id}.parquet"
            if not p_file.exists():
                continue
            stream_df = pq.read_table(
                p_file,
                columns=[
                    "timestamp", "lat", "lon", "distance_m", "heart_rate_bpm",
                    "speed_mps", "temperature_c", "grade_pct", "altitude",
                ],
            ).to_pandas()
            if stream_df.empty:
                continue

            timestamps = pd.to_datetime(stream_df["timestamp"], utc=True)
            elapsed = (timestamps - timestamps.iloc[0]).dt.total_seconds().to_numpy(dtype=float)
            lats = stream_df["lat"].values
            lons = stream_df["lon"].values
            distances = stream_df["distance_m"].to_numpy(dtype=float)
            altitudes = stream_df["altitude"].to_numpy(dtype=float)
            smoothed_altitudes = (
                pd.Series(altitudes).interpolate(limit_direction="both")
                .rolling(5, center=True, min_periods=1).median().to_numpy(dtype=float)
            )
            raw_gain = np.concatenate(
                ([0.0], np.cumsum(np.maximum(np.diff(smoothed_altitudes), 0.0)))
            )
            if raw_gain[-1] > 0.0:
                cumulative_ascent = raw_gain * (float(row["elevation_gain_m"]) / raw_gain[-1])
            else:
                cumulative_ascent = np.zeros(len(stream_df), dtype=float)
            hrs = stream_df["heart_rate_bpm"].values if "heart_rate_bpm" in stream_df else np.full(len(lats), np.nan)
            speeds = stream_df["speed_mps"].values if "speed_mps" in stream_df else np.full(len(lats), np.nan)
            temperatures = stream_df["temperature_c"].values if "temperature_c" in stream_df else np.full(len(lats), np.nan)
            grades = stream_df["grade_pct"].values if "grade_pct" in stream_df else np.full(len(lats), np.nan)

            x_pts, y_pts = [], []
            valid_elapsed, valid_distances, valid_ascents, valid_altitudes = [], [], [], []
            valid_hrs, valid_spds, valid_temperatures, valid_grades = [], [], [], []
            for lat, lon, elapsed_s, distance_m, ascent_m, altitude_m, hr, spd, temp, grade in zip(
                lats, lons, elapsed, distances, cumulative_ascent, altitudes,
                hrs, speeds, temperatures, grades
            ):
                if not self._is_masked(lat, lon):
                    mx, my = project_mercator(lon, lat)
                    x_pts.append(mx)
                    y_pts.append(my)
                    valid_elapsed.append(elapsed_s)
                    valid_distances.append(distance_m)
                    valid_ascents.append(ascent_m)
                    valid_altitudes.append(altitude_m)
                    valid_hrs.append(hr)
                    valid_spds.append(spd)
                    valid_temperatures.append(temp)
                    valid_grades.append(grade)
                else:
                    x_pts.append(np.nan)
                    y_pts.append(np.nan)
                    valid_elapsed.append(elapsed_s)
                    valid_distances.append(np.nan)
                    valid_ascents.append(np.nan)
                    valid_altitudes.append(np.nan)
                    valid_hrs.append(np.nan)
                    valid_spds.append(np.nan)
                    valid_temperatures.append(np.nan)
                    valid_grades.append(np.nan)

            tracks.append({
                "id": act_id,
                "name": row["name"],
                "date": dt,
                "dist_km": row["distance_m"] / 1000.0,
                "elev_m": row["elevation_gain_m"],
                "xs": np.array(x_pts),
                "ys": np.array(y_pts),
                "elapsed_s": np.array(valid_elapsed, dtype=float),
                "distances_m": np.array(valid_distances, dtype=float),
                "ascents_m": np.array(valid_ascents, dtype=float),
                "altitudes": np.array(valid_altitudes, dtype=float),
                "hrs": np.array(valid_hrs),
                "speeds": np.array(valid_spds),
                "temperatures": np.array(valid_temperatures),
                "grades": np.array(valid_grades),
            })

        return tracks

    def _draw_route(self, draw: ImageDraw.ImageDraw, track: Dict[str, Any], style: str,
                    end_index: int, width: int, start_index: int = 0,
                    halo_width: int = 0) -> None:
        """Draw a route prefix, grouping equal semantic colors into clean runs."""
        points = track["pixel_points"]
        end = min(max(int(end_index), 0), len(points))
        start = min(max(int(start_index), 0), max(end - 1, 0))
        if end - start < 2:
            return
        if halo_width > 0:
            draw.line(
                points[start:end],
                fill=self.theme.canvas,
                width=width + 2 * halo_width,
            )
        if style not in DATA_STYLE_SPECS:
            draw.line(
                points[start:end],
                fill=route_color(style, track["date"], theme=self.theme),
                width=width,
            )
            return

        values = np.asarray(track[DATA_STYLE_SPECS[style]["field"]], dtype=float)
        finite = np.isfinite(values)
        if not np.any(finite):
            draw_dashed_path(
                draw, points[start:end], fill=self.theme.data_missing, width=width,
                dash=max(4, width * 2), gap=max(3, width),
            )
            return
        sample_positions = np.arange(len(values), dtype=float)
        values = np.interp(sample_positions, sample_positions[finite], values[finite])

        def draw_run(run_points: List[Tuple[int, int]], color: Optional[str]) -> None:
            assert color is not None
            draw.line(run_points, fill=color, width=width)

        run_start = start
        run_color = route_metric_color(style, values[start])
        for segment_index in range(start + 1, end - 1):
            color = route_metric_color(style, values[segment_index])
            if color != run_color:
                draw_run(points[run_start:segment_index + 1], run_color)
                run_start = segment_index
                run_color = color
        draw_run(points[run_start:end], run_color)

    def _draw_data_legend(self, draw: ImageDraw.ImageDraw, x: int, y: int, w: int,
                          style: str, tracks: List[Dict[str, Any]], *, scale: int,
                          wide: bool) -> int:
        """Draw a compact, square-ended legend inside the editorial grid."""
        if style not in DATA_STYLE_SPECS:
            return y
        spec = DATA_STYLE_SPECS[style]
        field = spec["field"]
        covered = sum(
            1 for track in tracks
            if np.any(np.isfinite(np.asarray(track[field], dtype=float)))
        )
        title_font = FontManager.get_font(11 * scale, bold=True)
        item_font = FontManager.get_font(10 * scale, bold=True)
        draw.text((x, y), self.i18n.text(spec["legend_key"]).upper(),
                  fill=self.theme.text_secondary, font=title_font)
        coverage = self.i18n.text(
            "collection.legend.coverage_short", count=covered, total=len(tracks)
        )
        coverage_w = int(round(title_font.getlength(coverage)))
        draw.text((x + w - coverage_w, y), coverage,
                  fill=self.theme.text_muted, font=title_font)

        items = [(color, label, False) for color, label in zip(spec["colors"], spec["labels"])] + [
            (self.theme.data_missing, self.i18n.text("collection.legend.no_data"), True)
        ]
        columns = 6 if wide else 3
        rows = int(math.ceil(len(items) / columns))
        item_w = w // columns
        item_y = y + 22 * scale
        for index, (color, label, missing) in enumerate(items):
            col = index % columns
            row = index // columns
            ix = x + col * item_w
            iy = item_y + row * 20 * scale
            if missing:
                draw.line([(ix, iy + 6 * scale), (ix + 6 * scale, iy + 6 * scale)],
                          fill=color, width=3 * scale)
                draw.line([(ix + 12 * scale, iy + 6 * scale), (ix + 18 * scale, iy + 6 * scale)],
                          fill=color, width=3 * scale)
            else:
                draw.line([(ix, iy + 6 * scale), (ix + 18 * scale, iy + 6 * scale)],
                          fill=color, width=3 * scale)
            draw.text((ix + 25 * scale, iy), str(label),
                      fill=self.theme.text_muted, font=item_font)
        return item_y + rows * 20 * scale + 8 * scale

    def _choose_map_legend_box(self, tracks: List[Dict[str, Any]], layout: VideoPartitionLayout,
                               *, scale: int, wide: bool, has_attribution: bool) -> Tuple[int, int, int, int]:
        """Pick the map corner with least route occupancy and greatest clearance."""
        padding = 28 * scale
        legend_w = min((760 if wide else 480) * scale, layout.map_rect.w - 2 * padding)
        legend_h = (62 if wide else 82) * scale
        candidates = [
            ("top_left", layout.map_rect.x0 + padding, layout.map_rect.y0 + padding),
            ("top_right", layout.map_rect.x1 - padding - legend_w, layout.map_rect.y0 + padding),
            ("bottom_left", layout.map_rect.x0 + padding, layout.map_rect.y1 - padding - legend_h),
            ("bottom_right", layout.map_rect.x1 - padding - legend_w, layout.map_rect.y1 - padding - legend_h),
        ]
        route_mask = Image.new("L", (layout.canvas_w, layout.canvas_h), 0)
        mask_draw = ImageDraw.Draw(route_mask)
        all_points: List[Tuple[int, int]] = []
        for track in tracks:
            points = track["pixel_points"]
            if len(points) >= 2:
                mask_draw.line(points, fill=255, width=8 * scale)
                all_points.extend(points[::max(1, len(points) // 500)])

        scored = []
        safety = 14 * scale
        for name, x, y in candidates:
            expanded = (
                max(layout.map_rect.x0, x - safety),
                max(layout.map_rect.y0, y - safety),
                min(layout.map_rect.x1, x + legend_w + safety),
                min(layout.map_rect.y1, y + legend_h + safety),
            )
            collision_pixels = int(np.count_nonzero(np.asarray(route_mask.crop(expanded))))
            if all_points:
                distances = []
                for px, py in all_points:
                    dx = max(x - px, 0, px - (x + legend_w))
                    dy = max(y - py, 0, py - (y + legend_h))
                    distances.append(math.hypot(dx, dy))
                clearance = min(distances)
            else:
                clearance = float("inf")
            reserved_penalty = 0
            if layout.aspect_ratio == "clean" and name == "top_left":
                reserved_penalty += 1_000_000
            if has_attribution and name == "bottom_left":
                reserved_penalty += 1_000_000
            scored.append((collision_pixels + reserved_penalty, -clearance, x, y))

        _, _, x, y = min(scored)
        return x, y, legend_w, legend_h

    def _draw_map_legend(self, draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int],
                         style: str, tracks: List[Dict[str, Any]], *, scale: int,
                         wide: bool) -> None:
        if style not in DATA_STYLE_SPECS:
            return
        x, y, w, h = box
        draw.rectangle((x, y, x + w, y + h), fill=self.theme.panel_background,
                       outline=self.theme.border, width=scale)
        inset = 12 * scale
        self._draw_data_legend(
            draw, x + inset, y + inset, w - 2 * inset, style, tracks,
            scale=scale, wide=wide,
        )

    @staticmethod
    def _distance_at(track: Dict[str, Any], point_count: int) -> float:
        """Return visible distance in metres with a catalog-backed fallback."""
        if point_count <= 0:
            return 0.0
        distances = np.asarray(track["point_distances_m"], dtype=float)
        if point_count >= len(distances):
            return float(track["dist_km"]) * 1000.0
        finite = distances[:point_count][np.isfinite(distances[:point_count])]
        if len(finite):
            return float(finite[-1])
        return float(track["dist_km"]) * 1000.0 * point_count / max(len(distances), 1)

    @staticmethod
    def _ascent_at(track: Dict[str, Any], point_count: int) -> float:
        if point_count <= 0:
            return 0.0
        ascents = np.asarray(track["point_ascents_m"], dtype=float)
        if point_count >= len(ascents):
            return float(track["elev_m"])
        finite = ascents[:point_count][np.isfinite(ascents[:point_count])]
        if len(finite):
            return float(finite[-1])
        return float(track["elev_m"]) * max(point_count - 1, 0) / max(len(ascents) - 1, 1)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total_minutes = max(0, int(round(seconds / 60.0)))
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours:02d}:{minutes:02d}"

    def _draw_finish_distribution(self, draw: ImageDraw.ImageDraw, x: int, y: int,
                                  w: int, h: int, durations: np.ndarray,
                                  cursor_seconds: float, *, scale: int) -> None:
        """Histogram of real route finish times with a truthful elapsed cursor."""
        values = np.asarray(durations, dtype=float)
        values = values[np.isfinite(values) & (values >= 0.0)]
        if len(values) == 0:
            return
        maximum = max(float(np.max(values)), 1.0)
        bins = np.linspace(0.0, maximum, 17)
        counts, _ = np.histogram(values, bins=bins)
        max_count = max(int(np.max(counts)), 1)
        label_h = 24 * scale
        plot_h = max(h - label_h, 10 * scale)
        draw.line([(x, y + plot_h), (x + w, y + plot_h)],
                  fill=self.theme.border, width=scale)
        gap = 3 * scale
        bar_w = max((w - gap * (len(counts) - 1)) // len(counts), 2 * scale)
        for index, count in enumerate(counts):
            x0 = x + index * (bar_w + gap)
            x1 = min(x + w, x0 + bar_w)
            bar_h = int(round((float(count) / max_count) * (plot_h - 8 * scale)))
            bin_end = bins[index + 1]
            color = self.theme.text_secondary if bin_end <= cursor_seconds else self.theme.route_inactive
            draw.rectangle((x0, y + plot_h - bar_h, x1, y + plot_h), fill=color)

        cursor_x = x + int(round(min(max(cursor_seconds / maximum, 0.0), 1.0) * w))
        draw.line([(cursor_x, y), (cursor_x, y + plot_h)],
                  fill=self.theme.route_primary, width=2 * scale)
        tick_font = FontManager.get_font(10 * scale, bold=True)
        ticks = ((0.0, "00:00"), (maximum / 2.0, self._format_elapsed(maximum / 2.0)),
                 (maximum, self._format_elapsed(maximum)))
        for value, label in ticks:
            tick_x = x + int(round(value / maximum * w))
            label_w = int(round(tick_font.getlength(label)))
            text_x = min(max(tick_x - label_w // 2, x), x + w - label_w)
            draw.text((text_x, y + plot_h + 7 * scale), label,
                      fill=self.theme.text_muted, font=tick_font)

    def render_collection(self,
                          output_mp4_path: Path,
                          motion: str = "chronological",
                          style: str = "orange",
                          mode: str = "16:9",
                          width: int = 1920,
                          height: int = 1080,
                          fps: int = 30,
                          duration_s: float = 14.0,
                          hold_s: float = 3.0,
                          keyframes_dir: Optional[Path] = None,
                          ssaa_scale: int = 2,
                          basemap: str = "plain",
                          map_detail: str = "standard",
                          show_progress_bar: bool = False) -> Tuple[Path, List[Path]]:
        output_mp4_path = Path(output_mp4_path)
        output_mp4_path.parent.mkdir(parents=True, exist_ok=True)
        if keyframes_dir:
            keyframes_dir = Path(keyframes_dir)
            keyframes_dir.mkdir(parents=True, exist_ok=True)

        tracks = self.load_all_collection_tracks()
        if not tracks:
            raise ValueError("Nenhuma rota carregada para renderização de coleção.")
        if basemap not in {"plain", *TILE_PROVIDERS}:
            raise ValueError(f"Basemap não suportado: {basemap}")
        if motion not in {"chronological", "simultaneous", "elapsed", "comet"}:
            raise ValueError(f"Motion não suportado: {motion}")
        if style not in {"orange", "monochrome", "monthly", *DATA_STYLE_SPECS}:
            raise ValueError(f"Estilo de rota não suportado: {style}")
        if map_detail not in {"standard", "high"}:
            raise ValueError("Map detail must be standard or high")

        sc = ssaa_scale
        render_w = width * sc
        render_h = height * sc
        output_scale = width / (1080.0 if mode == "9:16" else 1920.0)
        ui = max(1, int(round(sc * output_scale)))
        layout = VideoPartitionLayout.create(render_w, render_h, mode)

        all_xs = np.concatenate([t["xs"][~np.isnan(t["xs"])] for t in tracks if len(t["xs"]) > 0])
        all_ys = np.concatenate([t["ys"][~np.isnan(t["ys"])] for t in tracks if len(t["ys"]) > 0])

        min_x, max_x = np.min(all_xs), np.max(all_xs)
        min_y, max_y = np.min(all_ys), np.max(all_ys)
        dx = max(max_x - min_x, 1.0)
        dy = max(max_y - min_y, 1.0)

        map_margin = 24 * ui
        usable_w = max(layout.map_rect.w - 2 * map_margin, 10)
        usable_h = max(layout.map_rect.h - 2 * map_margin, 10)
        scale_val = min(usable_w / dx, usable_h / dy)

        x_center_geo = (min_x + max_x) / 2.0
        y_center_geo = (min_y + max_y) / 2.0
        x_center_pix = layout.map_rect.x0 + layout.map_rect.w / 2.0
        y_center_pix = layout.map_rect.y0 + layout.map_rect.h / 2.0

        projected_tracks = []
        for t in tracks:
            px = x_center_pix + (t["xs"] - x_center_geo) * scale_val
            py = y_center_pix - (t["ys"] - y_center_geo) * scale_val
            pts = []
            pts_elapsed = []
            pts_distances, pts_ascents, pts_altitudes = [], [], []
            pts_hrs = []
            pts_spds = []
            pts_temperatures = []
            pts_grades = []
            for x_val, y_val, elapsed_s, distance_m, ascent_m, altitude_m, hr, spd, temp, grade in zip(
                px, py, t["elapsed_s"], t["distances_m"], t["ascents_m"], t["altitudes"],
                t["hrs"], t["speeds"],
                t["temperatures"], t["grades"],
            ):
                if not np.isnan(x_val) and not np.isnan(y_val):
                    pts.append((int(round(x_val)), int(round(y_val))))
                    pts_elapsed.append(elapsed_s)
                    pts_distances.append(distance_m)
                    pts_ascents.append(ascent_m)
                    pts_altitudes.append(altitude_m)
                    pts_hrs.append(hr)
                    pts_spds.append(spd)
                    pts_temperatures.append(temp)
                    pts_grades.append(grade)
            projected_tracks.append({
                **t,
                "pixel_points": pts,
                "point_elapsed_s": np.asarray(pts_elapsed, dtype=float),
                "point_distances_m": np.asarray(pts_distances, dtype=float),
                "point_ascents_m": np.asarray(pts_ascents, dtype=float),
                "point_altitudes": np.asarray(pts_altitudes, dtype=float),
                "point_hrs": pts_hrs,
                "point_speeds_kmh": np.asarray(pts_spds, dtype=float) * 3.6,
                "point_temperatures": pts_temperatures,
                "point_grades": pts_grades,
            })

        basemap_layer: Optional[Image.Image] = None
        if basemap != "plain":
            # Invert the exact pixel projection at the full-canvas corners.
            # The map stays registered in its partition while imagery continues
            # naturally beneath the translucent telemetry partition.
            geo_left = x_center_geo + (0 - x_center_pix) / scale_val
            geo_right = x_center_geo + (render_w - x_center_pix) / scale_val
            geo_top = y_center_geo + (y_center_pix - 0) / scale_val
            geo_bottom = y_center_geo + (y_center_pix - render_h) / scale_val
            min_lon, min_lat = unproject_mercator(geo_left, geo_bottom)
            max_lon, max_lat = unproject_mercator(geo_right, geo_top)
            basemap_layer = self.tile_manager.render_basemap_layer(
                min_lon,
                min_lat,
                max_lon,
                max_lat,
                render_w,
                render_h,
                provider=basemap,
                dim_pct=0.28 if basemap == "satellite" else 0.40,
                detail_scale=2 if map_detail == "high" else 1,
            )
            basemap_layer = ImageEnhance.Color(basemap_layer).enhance(
                0.34 if basemap == "satellite" else 0.08
            )

        total_anim_frames = int(duration_s * fps)
        total_hold_frames = int(hold_s * fps)
        total_frames = total_anim_frames + total_hold_frames

        ffmpeg_cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{width}x{height}",
            "-pix_fmt", "rgb24",
            "-r", str(fps),
            "-i", "-",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            str(output_mp4_path)
        ]

        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        # Drain stderr concurrently: ffmpeg banner/stats/error output can fill the
        # 64 KiB pipe buffer and dead-lock the frame writer below (observed bug).
        stderr_sink: List[bytes] = []
        assert proc.stderr is not None
        threading.Thread(
            target=lambda: stderr_sink.append(proc.stderr.read()), daemon=True
        ).start()

        keyframe_indices = {
            "00": 0,
            "25": int(total_anim_frames * 0.25),
            "50": int(total_anim_frames * 0.50),
            "75": int(total_anim_frames * 0.75),
            "100": total_anim_frames,
        }
        saved_keyframes = []

        total_rides = len(projected_tracks)
        cumulative_km_profile = np.concatenate(
            ([0.0], np.cumsum([t["dist_km"] for t in projected_tracks], dtype=float))
        )
        ride_timestamps = [pd.Timestamp(track["date"]) for track in projected_tracks]
        season_time_profile = np.array(
            [ride_timestamps[0].timestamp(), *[timestamp.timestamp() for timestamp in ride_timestamps]],
            dtype=float,
        )
        first_month = ride_timestamps[0].replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_ticks = [
            (max(month.timestamp(), season_time_profile[0]), self.i18n.month_short(month))
            for month in pd.date_range(first_month, ride_timestamps[-1], freq="MS")
        ]

        parallel_axis = np.linspace(0.0, 1.0, 101)
        max_elapsed_s = max(
            (float(track["point_elapsed_s"][-1]) for track in projected_tracks
             if len(track["point_elapsed_s"])),
            default=0.0,
        )
        finish_durations = np.asarray(
            [float(track["point_elapsed_s"][-1]) for track in projected_tracks
             if len(track["point_elapsed_s"])],
            dtype=float,
        )

        def parallel_counts(progress: float, *, elapsed_mode: bool) -> List[int]:
            if elapsed_mode:
                cursor = max_elapsed_s * progress
                return [elapsed_point_count(track["point_elapsed_s"], cursor) for track in projected_tracks]
            return [min(int(round(len(track["pixel_points"]) * progress)), len(track["pixel_points"]))
                    for track in projected_tracks]

        def parallel_distance(progress: float, *, elapsed_mode: bool) -> float:
            counts = parallel_counts(progress, elapsed_mode=elapsed_mode)
            return sum(self._distance_at(track, count) for track, count in zip(projected_tracks, counts)) / 1000.0

        normalized_distance_profile = np.asarray(
            [parallel_distance(value, elapsed_mode=False) for value in parallel_axis], dtype=float
        )
        map_legend_wide = mode == "9:16"
        map_legend_box = (
            self._choose_map_legend_box(
                projected_tracks, layout, scale=ui, wide=map_legend_wide,
                has_attribution=basemap != "plain",
            )
            if style in DATA_STYLE_SPECS else None
        )

        for frame_idx in range(total_frames):
            if frame_idx < total_anim_frames:
                t_norm = frame_idx / float(total_anim_frames)
            else:
                t_norm = 1.0

            img = Image.new("RGB", (render_w, render_h), color=self.theme.canvas)
            if basemap_layer is not None:
                img.paste(basemap_layer, (0, 0))
            draw = ImageDraw.Draw(img)

            # 1. Traçado de fundo: contexto futuro permitido, sempre neutro.
            for pt_data in projected_tracks:
                pts = pt_data["pixel_points"]
                if len(pts) >= 2:
                    draw.line(pts, fill=self.theme.route_inactive, width=2 * ui)

            # 2. Animação de acordo com o Motion
            ease_t = t_norm * t_norm * (3.0 - 2.0 * t_norm)
            if motion == "chronological":
                progress_position = t_norm * total_rides
                active_rides_count = min(int(t_norm * total_rides), total_rides)
                for i_t in range(active_rides_count):
                    pt_data = projected_tracks[i_t]
                    self._draw_route(
                        draw, pt_data, style, len(pt_data["pixel_points"]),
                        3 * ui, halo_width=ui,
                    )

                if active_rides_count < total_rides:
                    cur_pt_data = projected_tracks[active_rides_count]
                    pts = cur_pt_data["pixel_points"]
                    sub_t = (t_norm * total_rides) - active_rides_count
                    k = int(sub_t * len(pts))
                    if k >= 2:
                        self._draw_route(
                            draw, cur_pt_data, style, k,
                            4 * ui, halo_width=ui,
                        )
                        cx, cy = pts[k - 1]
                        r = 4 * ui
                        draw.rectangle((cx - r, cy - r, cx + r, cy + r), fill=self.theme.route_primary)
                season = self._season_stats(projected_tracks, progress_position)
                active_rides_count = int(season["completed"])
                current_km = float(season["distance_km"])
                current_elev = float(season["elevation_m"])
                current_ride_name = str(season["ride_name"])
                if active_rides_count >= total_rides:
                    first_date = self.i18n.date(projected_tracks[0]["date"])
                    last_date = self.i18n.date(projected_tracks[-1]["date"])
                    current_ride_name = f"{first_date} – {last_date}"
                metric_rows = (
                    ((self.i18n.text("metric.current_date"), str(season["date"])),
                     (self.i18n.text("metric.rides_accumulated"), f"{active_rides_count} / {total_rides}")),
                    ((self.i18n.text("metric.month_distance"), f"{self.i18n.number(season['month_distance_km'], 1)} km"),
                     (self.i18n.text("metric.ascent"), f"{self.i18n.number(current_elev)} m")),
                    ((self.i18n.text("metric.average_ride"), f"{self.i18n.number(season['average_ride_km'], 1)} km"),
                     (self.i18n.text("metric.longest_so_far"), f"{self.i18n.number(season['longest_so_far_km'], 1)} km")),
                )
                progress_pct = float(season["position"]) / max(total_rides, 1)
                chart_values = cumulative_km_profile
                chart_position = float(season["position"])
                chart_x_values = season_time_profile
                chart_ticks = month_ticks
            else:
                elapsed_mode = motion == "elapsed"
                counts = parallel_counts(ease_t, elapsed_mode=elapsed_mode)
                distances_km = [
                    self._distance_at(track, count) / 1000.0
                    for track, count in zip(projected_tracks, counts)
                ]
                finished_count = sum(
                    count >= len(track["pixel_points"])
                    for track, count in zip(projected_tracks, counts)
                    if len(track["pixel_points"])
                )
                routes_in_motion = total_rides - finished_count
                for pt_data, k in zip(projected_tracks, counts):
                    pts = pt_data["pixel_points"]
                    if k >= 2:
                        if motion == "comet" and ease_t < 1.0:
                            tail = max(12, int(round(len(pts) * 0.12)))
                            self._draw_route(
                                draw, pt_data, style, k, 4 * ui,
                                max(0, k - tail), halo_width=ui,
                            )
                        else:
                            self._draw_route(
                                draw, pt_data, style, k,
                                4 * ui, halo_width=ui,
                            )
                    if 0 < k < len(pts):
                        cx, cy = pts[k - 1]
                        r = 2 * ui
                        draw.rectangle((cx - r, cy - r, cx + r, cy + r),
                                       fill=self.theme.route_highlight)

                current_km = float(sum(distances_km))
                current_elev = sum(
                    self._ascent_at(track, count)
                    for track, count in zip(projected_tracks, counts)
                )
                active_rides_count = finished_count
                current_ride_name = self.i18n.text(
                    "collection.parallel.elapsed" if elapsed_mode else "collection.parallel.normalized"
                )
                cursor_elapsed = max_elapsed_s * ease_t
                progress_value = self._format_elapsed(cursor_elapsed) if elapsed_mode else f"{ease_t * 100:.0f}%"
                metric_rows = (
                    ((self.i18n.text("metric.elapsed_time" if elapsed_mode else "metric.progress"), progress_value),
                     (self.i18n.text("metric.routes_finished"), f"{finished_count} / {total_rides}")),
                    ((self.i18n.text("metric.combined_distance"), f"{self.i18n.number(current_km, 1)} km"),
                     (self.i18n.text("metric.routes_in_motion"), str(routes_in_motion))),
                    ((self.i18n.text("metric.farthest_route"), f"{self.i18n.number(max(distances_km, default=0.0), 1)} km"),
                     (self.i18n.text("metric.ascent"), f"{self.i18n.number(current_elev)} m")),
                )
                progress_pct = ease_t
                chart_values = normalized_distance_profile
                chart_position = ease_t * (len(chart_values) - 1)
                chart_x_values = parallel_axis
                chart_ticks = None

            if map_legend_box is not None:
                self._draw_map_legend(
                    draw, map_legend_box, style, projected_tracks,
                    scale=ui, wide=map_legend_wide,
                )

            if basemap != "plain":
                attribution = TILE_PROVIDERS[basemap]["attribution"]
                font_size = max(10 * sc, 10 * ui)
                attribution_font = FontManager.get_font(font_size)
                available_w = layout.map_rect.w - 12 * sc
                while (
                    attribution_font.getlength(attribution) > available_w
                    and font_size > 8 * sc
                ):
                    font_size -= 1
                    attribution_font = FontManager.get_font(font_size)

                text_box = draw.textbbox((0, 0), attribution, font=attribution_font)
                pad_x = 4 * sc
                pad_y = 3 * sc
                attribution_x = layout.map_rect.x0 + 5 * sc - text_box[0]
                attribution_y = layout.map_rect.y1 - 6 * sc - text_box[3]
                visible_box = (
                    attribution_x + text_box[0],
                    attribution_y + text_box[1],
                    attribution_x + text_box[2],
                    attribution_y + text_box[3],
                )
                notice_box = (
                    int(visible_box[0] - pad_x),
                    int(visible_box[1] - pad_y),
                    int(visible_box[2] + pad_x),
                    int(visible_box[3] + pad_y),
                )
                notice_color = (*ImageColor.getrgb(self.theme.panel_background), 140)
                notice_layer = Image.new(
                    "RGBA",
                    (notice_box[2] - notice_box[0], notice_box[3] - notice_box[1]),
                    notice_color,
                )
                img.paste(notice_layer, notice_box[:2], notice_layer)
                draw = ImageDraw.Draw(img)
                draw.text(
                    (attribution_x, attribution_y),
                    attribution,
                    fill=self.theme.text_primary,
                    font=attribution_font,
                )

            # 3. Painel de Telemetria Sóbrio (em 2x)
            if mode == "16:9" and layout.telemetry_rect.w > 0:
                tr = layout.telemetry_rect
                if basemap_layer is not None:
                    panel_alpha = 204 if basemap == "satellite" else 220
                    panel_tint = Image.new("RGBA", (tr.w, tr.h), (5, 5, 5, panel_alpha))
                    img.paste(panel_tint, (tr.x0, tr.y0), panel_tint)
                    draw = ImageDraw.Draw(img)
                else:
                    draw.rectangle((tr.x0, tr.y0, tr.x1, tr.y1), fill=self.theme.panel_background)
                draw.line([(tr.x0, tr.y0), (tr.x0, tr.y1)], fill=self.theme.border, width=ui)

                card_w = tr.w - 70 * ui
                tx = tr.x0 + 35 * ui
                ty = tr.y0 + 40 * ui

                ty = DashboardPainter.draw_header(draw, tx, ty, card_w,
                                                  title=self.i18n.text("collection.title"),
                                                  subtitle=current_ride_name,
                                                  eyebrow="",
                                                  is_mobile=False,
                                                  scale=ui)
                col_gap = 18 * ui
                col_w = (card_w - col_gap) // 2
                col2_x = tx + col_w + col_gap
                card_h = 78 * ui
                grid_top = ty
                for row_index, row in enumerate(metric_rows):
                    row_y = grid_top + row_index * card_h
                    DashboardPainter.draw_card(
                        draw, tx, row_y, col_w, card_h,
                        label=row[0][0], value=row[0][1], is_mobile=False, scale=ui,
                    )
                    DashboardPainter.draw_card(
                        draw, col2_x, row_y, col_w, card_h,
                        label=row[1][0], value=row[1][1], is_mobile=False, scale=ui,
                    )
                draw.line(
                    [(tx + col_w + col_gap // 2, grid_top), (tx + col_w + col_gap // 2, grid_top + 3 * card_h)],
                    fill=self.theme.border,
                    width=ui,
                )
                ty = grid_top + 3 * card_h

                if show_progress_bar:
                    DashboardPainter.draw_progress_bar(
                        draw, tx, ty + 10 * ui, card_w, 10 * ui, pct=progress_pct, scale=ui,
                    )
                chart_top = ty + (42 if show_progress_bar else 16) * ui
                f_chart_label = FontManager.get_font(12 * ui, bold=True)
                f_chart_value = FontManager.get_font(27 * ui, bold=True)
                if motion == "elapsed":
                    chart_label = "collection.finish_distribution"
                    chart_value = f"{finished_count} / {total_rides}"
                else:
                    chart_label = "metric.season_distance" if motion == "chronological" else "metric.combined_distance"
                    chart_value = f"{self.i18n.number(current_km, 1)} km"
                draw.text((tx, chart_top), self.i18n.text(chart_label).upper(),
                          fill=self.theme.text_muted, font=f_chart_label)
                draw.text((tx, chart_top + 22 * ui), chart_value,
                          fill=self.theme.text_primary, font=f_chart_value)
                axis_top = chart_top + 64 * ui
                axis_h = max(100 * ui, tr.y1 - axis_top - 48 * ui)
                if motion == "elapsed":
                    self._draw_finish_distribution(
                        draw, tx, axis_top, card_w, axis_h,
                        finish_durations, cursor_elapsed, scale=ui,
                    )
                else:
                    DashboardPainter.draw_progress_chart(
                        draw,
                        tx,
                        axis_top,
                        card_w,
                        axis_h,
                        chart_values,
                        chart_position,
                        scale=ui,
                        x_values=chart_x_values,
                        x_ticks=chart_ticks,
                    )

            elif mode == "9:16" and layout.telemetry_rect.h > 0:
                tr = layout.telemetry_rect
                if basemap_layer is not None:
                    panel_alpha = 204 if basemap == "satellite" else 220
                    panel_tint = Image.new("RGBA", (tr.w, tr.h), (5, 5, 5, panel_alpha))
                    img.paste(panel_tint, (tr.x0, tr.y0), panel_tint)
                    draw = ImageDraw.Draw(img)
                else:
                    draw.rectangle((tr.x0, tr.y0, tr.x1, tr.y1), fill=self.theme.panel_background)
                draw.line([(tr.x0, tr.y0), (tr.x1, tr.y0)], fill=self.theme.border, width=ui)

                tx = tr.x0 + 50 * ui
                ty = tr.y0 + 35 * ui
                pw = tr.w - 100 * ui

                ty = DashboardPainter.draw_header(draw, tx, ty, pw,
                                                  title=self.i18n.text("collection.title"),
                                                  subtitle=current_ride_name,
                                                  eyebrow="",
                                                  is_mobile=True,
                                                  scale=ui)
                col_w = (pw - 20 * ui) // 2
                col2_x = tx + col_w + 20 * ui
                card_h = 94 * ui
                grid_top = ty
                for row_index, row in enumerate(metric_rows):
                    row_y = grid_top + row_index * card_h
                    DashboardPainter.draw_card(
                        draw, tx, row_y, col_w, card_h,
                        label=row[0][0], value=row[0][1], is_mobile=True, scale=ui,
                    )
                    DashboardPainter.draw_card(
                        draw, col2_x, row_y, col_w, card_h,
                        label=row[1][0], value=row[1][1], is_mobile=True, scale=ui,
                    )
                ty = grid_top + 3 * card_h + 12 * ui
                if show_progress_bar:
                    DashboardPainter.draw_progress_bar(
                        draw, tx, ty, pw, 12 * ui, pct=progress_pct, scale=ui,
                    )
                chart_top = ty + (28 if show_progress_bar else 0) * ui
                chart_h = max(70 * ui, tr.y1 - chart_top - 26 * ui)
                if motion == "elapsed":
                    self._draw_finish_distribution(
                        draw, tx, chart_top, pw, chart_h,
                        finish_durations, cursor_elapsed, scale=ui,
                    )
                else:
                    DashboardPainter.draw_progress_chart(
                        draw, tx, chart_top, pw, chart_h,
                        chart_values, chart_position, scale=ui,
                        x_values=chart_x_values, x_ticks=chart_ticks,
                    )

            else:
                f_title = FontManager.get_font(32 * ui, bold=True)
                f_sub = FontManager.get_font(18 * ui, bold=False)
                clean_x = layout.map_rect.x0 + 40 * ui
                draw.text((clean_x, layout.map_rect.y0 + 35 * ui),
                          self.i18n.text("video.season_title", count=total_rides), fill=self.theme.text_primary, font=f_title)
                draw.text((clean_x, layout.map_rect.y0 + 75 * ui),
                          self.i18n.text("video.season_summary", distance=f"{current_km:.1f}", ascent=f"{current_elev:,.0f}", count=f"{active_rides_count}/{total_rides}"),
                          fill=self.theme.text_secondary, font=f_sub)

            final_frame = img.resize((width, height), Image.Resampling.LANCZOS)

            # Salvar keyframe
            if keyframes_dir:
                for pct_label, k_idx in keyframe_indices.items():
                    if frame_idx == k_idx:
                        kf_file = keyframes_dir / f"keyframe_{motion}_{style}_{mode.replace(':', '_')}_{pct_label}pct.png"
                        final_frame.save(kf_file)
                        saved_keyframes.append(kf_file)

            proc.stdin.write(final_frame.tobytes())

        proc.stdin.close()
        proc.wait()

        if proc.returncode != 0:
            err = b"".join(stderr_sink).decode("utf-8", errors="replace")
            raise RuntimeError(f"FFmpeg collection error: {err}")

        return output_mp4_path, saved_keyframes
