"""High-resolution route maps, density maps, and raster basemaps."""

import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from PIL import Image

from ride_visuals.ingest.metrics import haversine_distance
from ride_visuals.design import EFFORT_COLORS, MONTH_ROUTE_COLORS, get_theme, route_color
from ride_visuals.i18n import Translator
from ride_visuals.maps.tiles import TILE_PROVIDERS, TileManager
from ride_visuals.privacy import load_privacy_zones
from ride_visuals.selection import ActivitySelection


def project_mercator(lon: float, lat: float) -> Tuple[float, float]:
    """Projeção EPSG:3857 (Spherical Mercator)."""
    r_major = 6378137.0
    x = r_major * math.radians(lon)
    lat_rad = math.radians(max(min(lat, 89.5), -89.5))
    y = 3189068.5 * math.log((1.0 + math.sin(lat_rad)) / (1.0 - math.sin(lat_rad)))
    return x, y


def unproject_mercator(x: float, y: float) -> Tuple[float, float]:
    """Inverte coordenadas Mercator para (lon, lat)."""
    r_major = 6378137.0
    lon = math.degrees(x / r_major)
    lat = math.degrees(2.0 * math.atan(math.exp(y / r_major)) - math.pi / 2.0)
    return lon, lat


class MapGenerator:
    """Gera visualizações cartográficas de rotas, densidade e gradientes de esforço com basemaps."""

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
        self.tile_mgr = TileManager()
        self.i18n = Translator(locale)
        self.theme = get_theme(theme)
        self.selection = selection or ActivitySelection()

    @staticmethod
    def _map_detail_scale(map_detail: str) -> int:
        if map_detail == "standard":
            return 1
        if map_detail == "high":
            return 2
        raise ValueError("Map detail must be standard or high")

    @staticmethod
    def _basemap_target_px(dpi: int) -> int:
        """Match raster detail to the plotted map area, with a safe memory cap."""
        return min(4096, max(1800, int(round(12.0 * 0.84 * dpi))))

    def _add_header(self, fig, title: str, subtitle: str) -> None:
        """Add the shared flat editorial header used by every map output."""
        fig.text(0.08, 0.925, title, color=self.theme.text_primary, fontsize=27,
                 fontweight="bold", family="sans-serif", ha="left")
        fig.text(0.08, 0.885, subtitle, color=self.theme.text_muted, fontsize=14,
                 family="sans-serif", ha="left")
        fig.add_artist(Line2D([0.08, 0.92], [0.855, 0.855], transform=fig.transFigure,
                              color=self.theme.border, linewidth=0.8))

    def _add_month_legend(self, fig, tracks: List[Dict[str, Any]]) -> None:
        months = sorted({track["date"].month for track in tracks})
        step = min(0.105, 0.84 / max(len(months), 1))
        for index, month in enumerate(months):
            label = self.i18n.month_short(datetime(2000, month, 1))
            x = 0.08 + index * step
            fig.add_artist(Line2D([x, x + min(0.026, step * 0.32)], [0.035, 0.035], transform=fig.transFigure,
                                  color=MONTH_ROUTE_COLORS[month], linewidth=2.2))
            fig.text(x + min(0.034, step * 0.42), 0.029, label, color=self.theme.text_muted,
                     fontsize=10, fontweight="bold", family="sans-serif", ha="left")

    def _add_attribution(self, fig, basemap: str) -> None:
        """Keep provider credits visible in every raster-basemap export."""
        # Static ``dark`` is a local canvas; only these modes fetch tiles.
        if basemap not in {"satellite", "topo", "osm"}:
            return
        fig.text(
            0.91,
            0.068,
            TILE_PROVIDERS[basemap]["attribution"],
            color=self.theme.text_primary,
            fontsize=9,
            family="sans-serif",
            ha="right",
            va="bottom",
            bbox={"facecolor": self.theme.panel_background, "edgecolor": "none", "pad": 2.5},
        )

    def _is_masked(self, lat: float, lon: float) -> bool:
        for z in self.privacy_zones:
            if haversine_distance(lat, lon, z["lat"], z["lon"]) <= z["radius_m"]:
                return True
        return False

    def load_all_tracks(self, month_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Carrega todas as trajetórias do catálogo."""
        con = duckdb.connect(str(self.catalog_db_path), read_only=True)
        where, parameters = self.selection.sql()
        query = f"SELECT id, name, start_date, distance_m, elevation_gain_m FROM activities{where} ORDER BY start_date"
        df_acts = con.execute(query, parameters).fetchdf()
        con.close()

        tracks = []
        for _, row in df_acts.iterrows():
            act_id = row["id"]
            dt = row["start_date"]
            if month_filter:
                if not dt.strftime("%Y-%m").startswith(month_filter):
                    continue

            p_file = self.streams_dir / f"{act_id}.parquet"
            if not p_file.exists():
                continue

            stream_df = pq.read_table(p_file, columns=["lat", "lon", "altitude", "heart_rate_bpm", "speed_mps"]).to_pandas()
            if stream_df.empty:
                continue

            lats = stream_df["lat"].values
            lons = stream_df["lon"].values
            hrs = stream_df["heart_rate_bpm"].values if "heart_rate_bpm" in stream_df else np.full(len(lats), np.nan)
            speeds = stream_df["speed_mps"].values if "speed_mps" in stream_df else np.full(len(lats), np.nan)

            x_pts, y_pts, valid_hrs, valid_spds = [], [], [], []
            for lat, lon, hr, spd in zip(lats, lons, hrs, speeds):
                if not self._is_masked(lat, lon):
                    mx, my = project_mercator(lon, lat)
                    x_pts.append(mx)
                    y_pts.append(my)
                    valid_hrs.append(hr)
                    valid_spds.append(spd)
                else:
                    x_pts.append(np.nan)
                    y_pts.append(np.nan)
                    valid_hrs.append(np.nan)
                    valid_spds.append(np.nan)

            tracks.append({
                "id": act_id,
                "name": row["name"],
                "date": dt,
                "dist_km": row["distance_m"] / 1000.0,
                "elev_m": row["elevation_gain_m"],
                "xs": np.array(x_pts),
                "ys": np.array(y_pts),
                "hrs": np.array(valid_hrs),
                "speeds": np.array(valid_spds),
            })

        return tracks

    def render_overview(self, out_path: Optional[Path] = None, dpi: int = 300,
                        basemap: str = "dark", route_style: str = "orange",
                        map_detail: str = "standard") -> Path:
        """Render the selected routes with a 1:1 map scale."""
        tracks = self.load_all_tracks()
        if not tracks:
            raise ValueError("Nenhuma rota carregada para o mapa overview.")

        base_tag = f"_{basemap}" if basemap != "dark" else ""
        style_tag = f"_{route_style}" if route_style != "orange" else ""
        detail_tag = "_map-high" if map_detail == "high" else ""
        detail_scale = self._map_detail_scale(map_detail)
        out_path = out_path or (self.outputs_dir / f"overview_{self.selection.slug()}{style_tag}{base_tag}{detail_tag}.png")

        all_xs = np.concatenate([t["xs"][~np.isnan(t["xs"])] for t in tracks if len(t["xs"]) > 0])
        all_ys = np.concatenate([t["ys"][~np.isnan(t["ys"])] for t in tracks if len(t["ys"]) > 0])

        x_min, x_max = np.min(all_xs), np.max(all_xs)
        y_min, y_max = np.min(all_ys), np.max(all_ys)

        dx = x_max - x_min
        dy = y_max - y_min
        max_span = max(dx, dy) * 1.15
        x_center = (x_min + x_max) / 2.0
        y_center = (y_min + y_max) / 2.0

        bg_color = "#000000" if basemap == "satellite" else self.theme.canvas
        fig = plt.figure(figsize=(12, 12), facecolor=bg_color)
        ax = fig.add_axes([0.08, 0.06, 0.84, 0.76], facecolor=bg_color)

        # Inserir basemap raster se solicitado
        if basemap in ["satellite", "topo", "osm"]:
            min_lon, min_lat = unproject_mercator(x_center - max_span / 2.0, y_center - max_span / 2.0)
            max_lon, max_lat = unproject_mercator(x_center + max_span / 2.0, y_center + max_span / 2.0)
            basemap_px = self._basemap_target_px(dpi)
            bg_img = self.tile_mgr.render_basemap_layer(
                min_lon, min_lat, max_lon, max_lat, basemap_px, basemap_px,
                provider=basemap, dim_pct=0.25 if basemap == "satellite" else 0.15,
                detail_scale=detail_scale,
            )
            ax.imshow(bg_img, extent=[x_center - max_span / 2.0, x_center + max_span / 2.0,
                                      y_center - max_span / 2.0, y_center + max_span / 2.0],
                      zorder=0, aspect="equal")

        for t in tracks:
            xs = t["xs"]
            ys = t["ys"]
            valid = ~np.isnan(xs) & ~np.isnan(ys)
            if np.any(valid):
                color = route_color(route_style, t["date"], theme=self.theme)
                ax.plot(xs[valid], ys[valid], color=color, alpha=0.62, linewidth=1.25, zorder=2)

        ax.set_xlim(x_center - max_span / 2.0, x_center + max_span / 2.0)
        ax.set_ylim(y_center - max_span / 2.0, y_center + max_span / 2.0)
        ax.set_aspect("equal", adjustable="box")
        ax.axis("off")

        tot_km = sum(t["dist_km"] for t in tracks)
        tot_elev = sum(t["elev_m"] for t in tracks)
        self._add_header(
            fig,
            self.i18n.text("map.overview.title"),
            self.i18n.text(
                "map.overview.subtitle",
                count=len(tracks),
                distance=self.i18n.number(tot_km, 1),
                ascent=self.i18n.number(tot_elev),
                start=self.i18n.date(min(t["date"] for t in tracks)),
                end=self.i18n.date(max(t["date"] for t in tracks)),
            ),
        )
        if route_style == "monthly":
            self._add_month_legend(fig, tracks)
        self._add_attribution(fig, basemap)

        plt.savefig(out_path, dpi=dpi, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        return out_path

    def render_heatmap(self, out_path: Optional[Path] = None, month: Optional[str] = None,
                       dpi: int = 300, basemap: str = "dark", route_style: str = "orange",
                       map_detail: str = "standard") -> Path:
        """Gera um mapa de calor / densidade com ampla separação superior."""
        tracks = self.load_all_tracks(month_filter=month)
        if not tracks:
            raise ValueError(f"Nenhuma rota para heatmap (filtro: {month}).")

        month_label = f"_{month}" if month else ""
        base_tag = f"_{basemap}" if basemap != "dark" else ""
        style_tag = f"_{route_style}" if route_style != "orange" else ""
        detail_tag = "_map-high" if map_detail == "high" else ""
        detail_scale = self._map_detail_scale(map_detail)
        out_path = out_path or (self.outputs_dir / f"density_{self.selection.slug()}{month_label}{style_tag}{base_tag}{detail_tag}.png")

        all_xs = np.concatenate([t["xs"][~np.isnan(t["xs"])] for t in tracks if len(t["xs"]) > 0])
        all_ys = np.concatenate([t["ys"][~np.isnan(t["ys"])] for t in tracks if len(t["ys"]) > 0])

        x_min, x_max = np.min(all_xs), np.max(all_xs)
        y_min, y_max = np.min(all_ys), np.max(all_ys)
        
        max_span = max(x_max - x_min, y_max - y_min) * 1.35
        x_center = (x_min + x_max) / 2.0
        y_center = (y_min + y_max) / 2.0 - (max_span * 0.08)

        bg_color = "#000000" if basemap == "satellite" else self.theme.canvas
        fig = plt.figure(figsize=(12, 12), facecolor=bg_color)
        ax = fig.add_axes([0.08, 0.06, 0.84, 0.76], facecolor=bg_color)

        if basemap in ["satellite", "topo", "osm"]:
            min_lon, min_lat = unproject_mercator(x_center - max_span / 2.0, y_center - max_span / 2.0)
            max_lon, max_lat = unproject_mercator(x_center + max_span / 2.0, y_center + max_span / 2.0)
            basemap_px = self._basemap_target_px(dpi)
            bg_img = self.tile_mgr.render_basemap_layer(
                min_lon, min_lat, max_lon, max_lat, basemap_px, basemap_px,
                provider=basemap, dim_pct=0.35 if basemap == "satellite" else 0.20,
                detail_scale=detail_scale,
            )
            ax.imshow(bg_img, extent=[x_center - max_span / 2.0, x_center + max_span / 2.0,
                                      y_center - max_span / 2.0, y_center + max_span / 2.0],
                      zorder=0, aspect="equal")

        for t in tracks:
            xs = t["xs"]
            ys = t["ys"]
            valid = ~np.isnan(xs) & ~np.isnan(ys)
            if np.any(valid):
                color = route_color(route_style, t["date"], theme=self.theme)
                # Alpha accumulation is the density encoding: repeated paths
                # become brighter without glow, blur or a second stroke.
                ax.plot(xs[valid], ys[valid], color=color, alpha=0.20, linewidth=1.45, zorder=2)

        ax.set_xlim(x_center - max_span / 2.0, x_center + max_span / 2.0)
        ax.set_ylim(y_center - max_span / 2.0, y_center + max_span / 2.0)
        ax.set_aspect("equal", adjustable="box")
        ax.axis("off")

        title = self.i18n.text("map.density.title") + (f" · {month}" if month else "")
        self._add_header(
            fig,
            title,
            self.i18n.text("map.density.subtitle", count=len(tracks)),
        )
        self._add_attribution(fig, basemap)

        plt.savefig(out_path, dpi=dpi, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        return out_path

    def render_effort_map(self, out_path: Optional[Path] = None, dpi: int = 300,
                          basemap: str = "dark", map_detail: str = "standard") -> Path:
        """Gera o mapa colorido ponto a ponto pelas zonas cardíacas de esforço (Z1 a Z5)."""
        tracks = self.load_all_tracks()
        if not tracks:
            raise ValueError("Nenhuma rota carregada para o mapa de esforço.")

        base_tag = f"_{basemap}" if basemap != "dark" else ""
        detail_tag = "_map-high" if map_detail == "high" else ""
        detail_scale = self._map_detail_scale(map_detail)
        out_path = out_path or (self.outputs_dir / f"effort_{self.selection.slug()}{base_tag}{detail_tag}.png")

        all_xs = np.concatenate([t["xs"][~np.isnan(t["xs"])] for t in tracks if len(t["xs"]) > 0])
        all_ys = np.concatenate([t["ys"][~np.isnan(t["ys"])] for t in tracks if len(t["ys"]) > 0])

        x_min, x_max = np.min(all_xs), np.max(all_xs)
        y_min, y_max = np.min(all_ys), np.max(all_ys)
        max_span = max(x_max - x_min, y_max - y_min) * 1.30
        x_center = (x_min + x_max) / 2.0
        y_center = (y_min + y_max) / 2.0 - (max_span * 0.06)

        bg_color = "#000000" if basemap == "satellite" else self.theme.canvas
        fig = plt.figure(figsize=(12, 12), facecolor=bg_color)
        ax = fig.add_axes([0.08, 0.10, 0.84, 0.72], facecolor=bg_color)

        if basemap in ["satellite", "topo", "osm"]:
            min_lon, min_lat = unproject_mercator(x_center - max_span / 2.0, y_center - max_span / 2.0)
            max_lon, max_lat = unproject_mercator(x_center + max_span / 2.0, y_center + max_span / 2.0)
            basemap_px = self._basemap_target_px(dpi)
            bg_img = self.tile_mgr.render_basemap_layer(
                min_lon, min_lat, max_lon, max_lat, basemap_px, basemap_px,
                provider=basemap, dim_pct=0.35 if basemap == "satellite" else 0.20,
                detail_scale=detail_scale,
            )
            ax.imshow(bg_img, extent=[x_center - max_span / 2.0, x_center + max_span / 2.0,
                                      y_center - max_span / 2.0, y_center + max_span / 2.0],
                      zorder=0, aspect="equal")

        for t in tracks:
            xs, ys, hrs = t["xs"], t["ys"], t["hrs"]
            base_valid = ~np.isnan(xs) & ~np.isnan(ys)
            finite_hr = np.isfinite(hrs)
            if np.any(base_valid) and not np.any(finite_hr):
                ax.plot(xs[base_valid], ys[base_valid], color=self.theme.data_missing,
                        alpha=0.82, linewidth=1.15, linestyle=(0, (2.0, 2.8)), zorder=1)
                continue
            sample_positions = np.arange(len(hrs), dtype=float)
            filled_hrs = np.interp(sample_positions, sample_positions[finite_hr], hrs[finite_hr])
            visual_hrs = (
                pd.Series(filled_hrs)
                .rolling(window=15, center=True, min_periods=1)
                .median()
                .to_numpy()
            )
            valid_mask = (~np.isnan(xs[:-1]) & ~np.isnan(ys[:-1]) &
                          ~np.isnan(xs[1:]) & ~np.isnan(ys[1:]))
            if not np.any(valid_mask):
                continue

            boundaries = [0, 132, 150, 165, 175, 250]
            cmap = ListedColormap(EFFORT_COLORS)
            norm = BoundaryNorm(boundaries, cmap.N)
            zone_indices = np.searchsorted(
                np.asarray(boundaries[1:-1], dtype=float), visual_hrs[:-1], side="right"
            )
            route_runs: list[np.ndarray] = []
            run_colors: list[str] = []
            run_start: int | None = None
            run_zone: int | None = None

            def append_run(last_segment: int) -> None:
                if run_start is None or run_zone is None:
                    return
                route_runs.append(np.column_stack((xs[run_start:last_segment + 1],
                                                   ys[run_start:last_segment + 1])))
                run_colors.append(EFFORT_COLORS[run_zone])

            for segment_index, (is_valid, zone_index) in enumerate(zip(valid_mask, zone_indices)):
                if not is_valid:
                    append_run(segment_index)
                    run_start = None
                    run_zone = None
                    continue
                zone = int(zone_index)
                if run_start is None:
                    run_start = segment_index
                    run_zone = zone
                elif zone != run_zone:
                    append_run(segment_index)
                    run_start = segment_index
                    run_zone = zone
            append_run(len(zone_indices))

            lc = LineCollection(
                route_runs,
                colors=run_colors,
                linewidth=1.65,
                alpha=0.94,
                capstyle="round",
                joinstyle="round",
                zorder=2,
            )
            ax.add_collection(lc)

        ax.set_xlim(x_center - max_span / 2.0, x_center + max_span / 2.0)
        ax.set_ylim(y_center - max_span / 2.0, y_center + max_span / 2.0)
        ax.set_aspect("equal", adjustable="box")
        ax.axis("off")

        self._add_header(
            fig,
            self.i18n.text("map.effort.title"),
            self.i18n.text(
                "map.effort.subtitle",
                with_data=sum(bool(np.isfinite(track["hrs"]).any()) for track in tracks),
                count=len(tracks),
            ),
        )

        cax = fig.add_axes([0.25, 0.06, 0.50, 0.02])
        cmap = ListedColormap(EFFORT_COLORS)
        norm = BoundaryNorm([0, 132, 150, 165, 175, 250], cmap.N)
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = fig.colorbar(sm, cax=cax, orientation="horizontal")
        cbar.set_ticks([100, 141, 157, 170, 190])
        cbar.set_ticklabels(["Z1", "Z2", "Z3", "Z4", "Z5"], color=self.theme.text_secondary, fontsize=11)
        cbar.ax.tick_params(colors=self.theme.text_secondary, labelsize=9, length=0)
        fig.add_artist(Line2D([0.08, 0.105], [0.07, 0.07], transform=fig.transFigure,
                              color=self.theme.data_missing, linewidth=2.2,
                              linestyle=(0, (2.5, 2.0))))
        fig.text(0.115, 0.061, self.i18n.text("collection.legend.no_data"),
                 color=self.theme.text_muted, fontsize=10, family="sans-serif", ha="left")
        self._add_attribution(fig, basemap)
        cbar.outline.set_edgecolor(self.theme.border)

        plt.savefig(out_path, dpi=dpi, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        return out_path
