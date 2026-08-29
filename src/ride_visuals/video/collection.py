"""Gerador de vídeos de coleção completa com Supersampling Anti-Aliasing 2x (SSAA)."""

import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Any
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageColor, ImageDraw, ImageEnhance

from ride_visuals.design import get_theme
from ride_visuals.i18n import Translator, sanitize_display_text
from ride_visuals.video.layout import VideoPartitionLayout
from ride_visuals.video.fonts import FontManager
from ride_visuals.maps.tiles import TILE_PROVIDERS, TileManager
from ride_visuals.maps.projection import unproject_mercator
from ride_visuals.selection import ActivitySelection
from ride_visuals.video.encoding import RawVideoEncoder
from ride_visuals.video.collection_data import (
    CollectionTrack,
    ProjectedCollectionTrack,
    load_collection_tracks,
    project_collection_tracks,
)
from ride_visuals.video.collection_motion import (
    SUPPORTED_MOTIONS,
    elapsed_point_count as elapsed_point_count,
    maximum_elapsed_seconds,
    normalized_distance_profile,
    parallel_motion_state,
    smoothstep,
)
from ride_visuals.video.collection_scene import (
    DATA_STYLE_SPECS,
    choose_map_legend_box,
    draw_map_legend,
    draw_route,
    route_metric_color as route_metric_color,
)
from ride_visuals.video.instagram import (
    INSTAGRAM_PANEL_SHARE,
    INSTAGRAM_STORY_LANDSCAPE,
    present_frame,
    render_dimensions,
    safe_insets,
)
from ride_visuals.video.collection_panel import (
    CollectionPanelState,
    draw_collection_panel,
    format_elapsed,
)


# One pass stays deliberately subtle; repeated passes converge toward the full
# route orange and reveal genuinely shared roads without glow or blur.
DENSITY_ROUTE_ALPHA = 0.18
DENSITY_ROUTE_WIDTH = 2.0
DENSITY_CURSOR_RADIUS = 3


class CollectionVideoRenderer:
    """Render all selected routes with optional 2x supersampling."""

    def __init__(self,
                 catalog_db_path: Path,
                 streams_dir: Path,
                 outputs_dir: Path,
                 locale: str = "pt-BR",
                 theme: str = "midnight",
                 selection: Optional[ActivitySelection] = None):
        self.catalog_db_path = Path(catalog_db_path)
        self.streams_dir = Path(streams_dir)
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.i18n = Translator(locale)
        self.theme = get_theme(theme)
        self.tile_manager = TileManager()
        self.selection = selection or ActivitySelection()

    def _season_stats(
        self,
        tracks: Sequence[ProjectedCollectionTrack],
        position: float,
    ) -> Dict[str, Any]:
        """Return continuously evolving season metrics for a fractional ride index."""
        total = len(tracks)
        clamped = min(max(float(position), 0.0), float(total))
        completed = min(int(math.floor(clamped)), total)
        fraction = clamped - completed if completed < total else 0.0
        current_index = min(completed, total - 1)
        current = tracks[current_index]
        completed_tracks = tracks[:completed]

        distance_km = sum(track.dist_km for track in completed_tracks)
        elevation_m = sum(track.elev_m for track in completed_tracks)
        if fraction > 0.0:
            distance_km += current.dist_km * fraction
            elevation_m += current.elev_m * fraction

        current_timestamp = pd.Timestamp(current.date)
        current_month = (current_timestamp.year, current_timestamp.month)
        month_distance_km = sum(
            track.dist_km
            for track in completed_tracks
            if (pd.Timestamp(track.date).year, pd.Timestamp(track.date).month) == current_month
        )
        if fraction > 0.0:
            month_distance_km += current.dist_km * fraction

        distances_so_far = [track.dist_km for track in completed_tracks]
        if fraction > 0.0:
            distances_so_far.append(current.dist_km * fraction)
        effective_count = completed + fraction

        return {
            "position": clamped,
            "completed": completed,
            "fraction": fraction,
            "date": self.i18n.date(current.date),
            "ride_name": sanitize_display_text(
                current.name or self.i18n.text("activity.default")
            ),
            "distance_km": distance_km,
            "elevation_m": elevation_m,
            "month_distance_km": month_distance_km,
            "average_ride_km": distance_km / effective_count if effective_count > 0.0 else 0.0,
            "longest_so_far_km": max(distances_so_far, default=0.0),
        }

    def load_all_collection_tracks(self) -> list[CollectionTrack]:
        return load_collection_tracks(
            self.catalog_db_path,
            self.streams_dir,
            self.selection,
        )

    def _draw_route(self, draw: ImageDraw.ImageDraw, track: ProjectedCollectionTrack, style: str,
                    end_index: int, width: int, start_index: int = 0,
                    halo_width: int = 0) -> None:
        draw_route(
            draw,
            track,
            style,
            end_index,
            width,
            theme=self.theme,
            start_index=start_index,
            halo_width=halo_width,
        )

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
                          show_progress_bar: bool = False,
                          show_background_tracks: Optional[bool] = None,
                          presentation: str = "standard") -> Tuple[Path, List[Path]]:
        output_mp4_path = Path(output_mp4_path)
        output_mp4_path.parent.mkdir(parents=True, exist_ok=True)
        if keyframes_dir:
            keyframes_dir = Path(keyframes_dir)
            keyframes_dir.mkdir(parents=True, exist_ok=True)

        effective_show_bg = (style != "density") if show_background_tracks is None else show_background_tracks

        tracks = self.load_all_collection_tracks()
        if not tracks:
            raise ValueError("Nenhuma rota carregada para renderização de coleção.")
        if basemap not in {"plain", *TILE_PROVIDERS}:
            raise ValueError(f"Basemap não suportado: {basemap}")
        if motion not in SUPPORTED_MOTIONS:
            raise ValueError(f"Motion não suportado: {motion}")
        if style not in {"orange", "density", "monochrome", "monthly", *DATA_STYLE_SPECS}:
            raise ValueError(f"Estilo de rota não suportado: {style}")
        if map_detail not in {"standard", "high"}:
            raise ValueError("Map detail must be standard or high")

        logical_width, logical_height = render_dimensions(width, height, presentation)
        sc = ssaa_scale
        render_w = logical_width * sc
        render_h = logical_height * sc
        output_scale = logical_width / (1080.0 if mode == "9:16" else 1920.0)
        ui = max(1, int(round(sc * output_scale)))
        safe_left_px, safe_right_px = safe_insets(presentation, scale=sc)
        layout = VideoPartitionLayout.create(
            render_w,
            render_h,
            mode,
            safe_left_px=safe_left_px,
            safe_right_px=safe_right_px,
            landscape_panel_share=(
                INSTAGRAM_PANEL_SHARE
                if presentation == INSTAGRAM_STORY_LANDSCAPE
                else 0.30
            ),
        )
        projection = project_collection_tracks(
            tracks,
            layout,
            margin_px=24 * ui,
        )
        projected_tracks = projection.tracks

        basemap_layer: Optional[Image.Image] = None
        if basemap != "plain":
            # Invert the exact pixel projection at the full-canvas corners.
            # The map stays registered in its partition while imagery continues
            # naturally beneath the translucent telemetry partition.
            geo_left = projection.geo_center_x + (0 - projection.pixel_center_x) / projection.scale
            geo_right = projection.geo_center_x + (render_w - projection.pixel_center_x) / projection.scale
            geo_top = projection.geo_center_y + (projection.pixel_center_y - 0) / projection.scale
            geo_bottom = projection.geo_center_y + (projection.pixel_center_y - render_h) / projection.scale
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
            ([0.0], np.cumsum([track.dist_km for track in projected_tracks], dtype=float))
        )
        ride_timestamps = [pd.Timestamp(track.date) for track in projected_tracks]
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
        max_elapsed_s = maximum_elapsed_seconds(projected_tracks)
        finish_durations = np.asarray(
            [float(track.point_elapsed_s[-1]) for track in projected_tracks
             if len(track.point_elapsed_s)],
            dtype=float,
        )

        distance_profile = normalized_distance_profile(projected_tracks, parallel_axis)
        map_legend_wide = mode == "9:16"
        map_legend_box = (
            choose_map_legend_box(
                projected_tracks, layout, scale=ui, wide=map_legend_wide,
                has_attribution=basemap != "plain",
            )
            if style in DATA_STYLE_SPECS else None
        )

        with RawVideoEncoder(
            output_mp4_path,
            width=width,
            height=height,
            fps=fps,
            operation="collection",
        ) as encoder:
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
                if effective_show_bg:
                    for pt_data in projected_tracks:
                        pts = pt_data.pixel_points
                        if len(pts) >= 2:
                            draw.line(pts, fill=self.theme.route_inactive, width=2 * ui)

                # 2. Animação de acordo com o Motion
                ease_t = smoothstep(t_norm)
                finished_count = 0
                cursor_elapsed = 0.0
                active_cursors = []

                if style == "density":
                    # High-precision vector AGG alpha accumulation layer
                    density_fig = plt.figure(figsize=(render_w / 100.0, render_h / 100.0), dpi=100)
                    density_fig.patch.set_alpha(0.0)
                    density_ax = density_fig.add_axes([0, 0, 1, 1])
                    density_ax.set_xlim(0, render_w)
                    density_ax.set_ylim(render_h, 0)
                    density_ax.axis("off")
                    density_ax.patch.set_alpha(0.0)

                    density_segments = []
                    if motion == "chronological":
                        progress_position = t_norm * total_rides
                        active_rides_count = min(int(t_norm * total_rides), total_rides)
                        for i_t in range(active_rides_count):
                            pts = np.asarray(projected_tracks[i_t].pixel_points)
                            if len(pts) >= 2:
                                density_segments.append(pts)
                        if active_rides_count < total_rides:
                            cur_pt_data = projected_tracks[active_rides_count]
                            pts = cur_pt_data.pixel_points
                            sub_t = (t_norm * total_rides) - active_rides_count
                            k = int(sub_t * len(pts))
                            if k >= 2:
                                density_segments.append(np.asarray(pts[:k]))
                                cx, cy = pts[k - 1]
                                active_cursors.append((
                                    cx, cy, DENSITY_CURSOR_RADIUS * ui,
                                    self.theme.route_primary,
                                ))
                        season = self._season_stats(projected_tracks, progress_position)
                        active_rides_count = int(season["completed"])
                        current_km = float(season["distance_km"])
                        current_elev = float(season["elevation_m"])
                        current_ride_name = str(season["ride_name"])
                        if active_rides_count >= total_rides:
                            first_date = self.i18n.date(projected_tracks[0].date)
                            last_date = self.i18n.date(projected_tracks[-1].date)
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
                        motion_state = parallel_motion_state(
                            projected_tracks,
                            ease_t,
                            elapsed=elapsed_mode,
                            max_elapsed_s=max_elapsed_s,
                        )
                        counts = motion_state.point_counts
                        distances_km = motion_state.distances_km
                        finished_count = motion_state.finished_count
                        routes_in_motion = motion_state.routes_in_motion
                        for pt_data, k in zip(projected_tracks, counts):
                            pts = pt_data.pixel_points
                            if k >= 2:
                                density_segments.append(np.asarray(pts[:k]))

                        current_km = motion_state.combined_distance_km
                        current_elev = motion_state.combined_ascent_m
                        active_rides_count = finished_count
                        current_ride_name = self.i18n.text(
                            "collection.parallel.elapsed" if elapsed_mode else "collection.parallel.normalized"
                        )
                        cursor_elapsed = motion_state.cursor_elapsed_s
                        progress_value = format_elapsed(cursor_elapsed) if elapsed_mode else f"{ease_t * 100:.0f}%"
                        metric_rows = (
                            ((self.i18n.text("metric.elapsed_time" if elapsed_mode else "metric.progress"), progress_value),
                             (self.i18n.text("metric.routes_finished"), f"{finished_count} / {total_rides}")),
                            ((self.i18n.text("metric.combined_distance"), f"{self.i18n.number(current_km, 1)} km"),
                             (self.i18n.text("metric.routes_in_motion"), str(routes_in_motion))),
                            ((self.i18n.text("metric.farthest_route"), f"{self.i18n.number(max(distances_km, default=0.0), 1)} km"),
                             (self.i18n.text("metric.ascent"), f"{self.i18n.number(current_elev)} m")),
                        )
                        progress_pct = ease_t
                        chart_values = distance_profile
                        chart_position = ease_t * (len(chart_values) - 1)
                        chart_x_values = parallel_axis
                        chart_ticks = None

                    if density_segments:
                        from matplotlib.collections import LineCollection
                        lc = LineCollection(
                            density_segments,
                            colors=self.theme.route_primary,
                            alpha=DENSITY_ROUTE_ALPHA,
                            linewidths=DENSITY_ROUTE_WIDTH * ui,
                            zorder=2,
                        )
                        density_ax.add_collection(lc)

                    density_fig.canvas.draw()
                    rgba_buf = np.asarray(density_fig.canvas.buffer_rgba())
                    route_layer = Image.fromarray(rgba_buf)
                    plt.close(density_fig)
                    img = Image.alpha_composite(img.convert("RGBA"), route_layer).convert("RGB")
                    draw = ImageDraw.Draw(img)
                elif motion == "chronological":
                    progress_position = t_norm * total_rides
                    active_rides_count = min(int(t_norm * total_rides), total_rides)
                    for i_t in range(active_rides_count):
                        pt_data = projected_tracks[i_t]
                        self._draw_route(
                            draw, pt_data, style, len(pt_data.pixel_points),
                            3 * ui, halo_width=ui,
                        )

                    if active_rides_count < total_rides:
                        cur_pt_data = projected_tracks[active_rides_count]
                        pts = cur_pt_data.pixel_points
                        sub_t = (t_norm * total_rides) - active_rides_count
                        k = int(sub_t * len(pts))
                        if k >= 2:
                            self._draw_route(
                                draw, cur_pt_data, style, k,
                                4 * ui, halo_width=ui,
                            )
                            cx, cy = pts[k - 1]
                            active_cursors.append((cx, cy, 4 * ui, self.theme.route_primary))
                    season = self._season_stats(projected_tracks, progress_position)
                    active_rides_count = int(season["completed"])
                    current_km = float(season["distance_km"])
                    current_elev = float(season["elevation_m"])
                    current_ride_name = str(season["ride_name"])
                    if active_rides_count >= total_rides:
                        first_date = self.i18n.date(projected_tracks[0].date)
                        last_date = self.i18n.date(projected_tracks[-1].date)
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
                    motion_state = parallel_motion_state(
                        projected_tracks,
                        ease_t,
                        elapsed=elapsed_mode,
                        max_elapsed_s=max_elapsed_s,
                    )
                    counts = motion_state.point_counts
                    distances_km = motion_state.distances_km
                    finished_count = motion_state.finished_count
                    routes_in_motion = motion_state.routes_in_motion
                    for pt_data, k in zip(projected_tracks, counts):
                        pts = pt_data.pixel_points
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
                            active_cursors.append((cx, cy, 2 * ui, self.theme.route_highlight))

                    current_km = motion_state.combined_distance_km
                    current_elev = motion_state.combined_ascent_m
                    active_rides_count = finished_count
                    current_ride_name = self.i18n.text(
                        "collection.parallel.elapsed" if elapsed_mode else "collection.parallel.normalized"
                    )
                    cursor_elapsed = motion_state.cursor_elapsed_s
                    progress_value = format_elapsed(cursor_elapsed) if elapsed_mode else f"{ease_t * 100:.0f}%"
                    metric_rows = (
                        ((self.i18n.text("metric.elapsed_time" if elapsed_mode else "metric.progress"), progress_value),
                         (self.i18n.text("metric.routes_finished"), f"{finished_count} / {total_rides}")),
                        ((self.i18n.text("metric.combined_distance"), f"{self.i18n.number(current_km, 1)} km"),
                         (self.i18n.text("metric.routes_in_motion"), str(routes_in_motion))),
                        ((self.i18n.text("metric.farthest_route"), f"{self.i18n.number(max(distances_km, default=0.0), 1)} km"),
                         (self.i18n.text("metric.ascent"), f"{self.i18n.number(current_elev)} m")),
                    )
                    progress_pct = ease_t
                    chart_values = distance_profile
                    chart_position = ease_t * (len(chart_values) - 1)
                    chart_x_values = parallel_axis
                    chart_ticks = None

                for cx, cy, r, color in active_cursors:
                    rad = max(2 * ui, r)
                    draw.ellipse(
                        (cx - rad, cy - rad, cx + rad, cy + rad),
                        fill=self.theme.route_highlight,
                        outline=color,
                        width=max(1, ui),
                    )

                if map_legend_box is not None:
                    draw_map_legend(
                        draw, map_legend_box, style, projected_tracks,
                        i18n=self.i18n, theme=self.theme,
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

                draw_collection_panel(
                    img,
                    layout,
                    CollectionPanelState(
                        ride_name=current_ride_name,
                        metric_rows=metric_rows,
                        progress_pct=progress_pct,
                        current_distance_km=current_km,
                        current_ascent_m=current_elev,
                        active_rides_count=active_rides_count,
                        finished_count=finished_count,
                        total_rides=total_rides,
                        chart_values=chart_values,
                        chart_position=chart_position,
                        chart_x_values=chart_x_values,
                        chart_ticks=chart_ticks,
                        finish_durations=finish_durations,
                        cursor_elapsed_s=cursor_elapsed,
                    ),
                    motion=motion,
                    mode=mode,
                    basemap=basemap,
                    has_basemap=basemap_layer is not None,
                    show_progress_bar=show_progress_bar,
                    i18n=self.i18n,
                    theme=self.theme,
                    scale=ui,
                )

                logical_frame = img.resize(
                    (logical_width, logical_height),
                    Image.Resampling.LANCZOS,
                )
                final_frame = present_frame(
                    logical_frame,
                    presentation=presentation,
                )

                # Salvar keyframe
                if keyframes_dir:
                    for pct_label, k_idx in keyframe_indices.items():
                        if frame_idx == k_idx:
                            kf_file = keyframes_dir / f"keyframe_{motion}_{style}_{mode.replace(':', '_')}_{pct_label}pct.png"
                            final_frame.save(kf_file)
                            saved_keyframes.append(kf_file)

                encoder.write(final_frame)

        return output_mp4_path, saved_keyframes
