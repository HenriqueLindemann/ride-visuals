"""Design sóbrio, minimalista e telemetria com gráficos de rastro / cometa (sparklines)."""

from typing import Optional, Sequence
import numpy as np
from PIL import ImageDraw
from ride_visuals.design import MIDNIGHT
from ride_visuals.video.fonts import FontManager


class DashboardPainter:
    """Desenha painéis de telemetria refinados com sparklines estáveis e sem oscilações bruscas."""

    @staticmethod
    def draw_header(draw: ImageDraw.Draw,
                    x: int, y: int, w: int,
                    title: str, subtitle: str,
                    eyebrow: str = "",
                    badge: Optional[str] = None,
                    is_mobile: bool = False,
                    scale: int = 1) -> int:
        """Cabeçalho sóbrio, limpo e sem redundâncias visuais."""
        tag = badge or eyebrow
        if is_mobile:
            f_eyebrow = FontManager.get_font(16 * scale, bold=True)
            f_title = FontManager.get_font(34 * scale, bold=True)
            f_sub = FontManager.get_font(19 * scale, bold=False)
            step_y = 41 * scale
        else:
            f_eyebrow = FontManager.get_font(13 * scale, bold=True)
            f_title = FontManager.get_font(28 * scale, bold=True)
            f_sub = FontManager.get_font(16 * scale, bold=False)
            step_y = 34 * scale

        cur_y = y
        if tag:
            draw.text((x, cur_y), tag.upper(), fill=MIDNIGHT.text_muted, font=f_eyebrow)
            cur_y += (25 if is_mobile else 21) * scale

        title = DashboardPainter._fit_text(title, f_title, w)
        draw.text((x, cur_y), title, fill=MIDNIGHT.text_primary, font=f_title)
        cur_y += step_y

        subtitle = DashboardPainter._fit_text(subtitle, f_sub, w)
        draw.text((x, cur_y), subtitle, fill=MIDNIGHT.text_secondary, font=f_sub)
        cur_y += (31 if is_mobile else 25) * scale

        draw.line([(x, cur_y), (x + w, cur_y)], fill=MIDNIGHT.border, width=scale)
        return cur_y + (23 if is_mobile else 19) * scale

    @staticmethod
    def _fit_text(text: str, font, max_width: int) -> str:
        """Keep a single-line label inside its editorial grid."""
        if font.getlength(text) <= max_width:
            return text
        suffix = "…"
        trimmed = text
        while trimmed and font.getlength(trimmed + suffix) > max_width:
            trimmed = trimmed[:-1]
        return trimmed.rstrip() + suffix

    @staticmethod
    def draw_sparkline(draw: ImageDraw.Draw,
                       sx: int, sy: int, sw: int, sh: int,
                       recent_values: np.ndarray,
                       line_color: str = MIDNIGHT.text_secondary,
                       min_val: Optional[float] = None,
                       max_val: Optional[float] = None,
                       scale: int = 1):
        """Desenha o rastro com escala fixa e amortecimento suave (sem oscilação ou flicker)."""
        valid_vals = recent_values[~np.isnan(recent_values)]
        draw.line([(sx, sy), (sx, sy + sh), (sx + sw, sy + sh)], fill=MIDNIGHT.border, width=scale)
        if len(valid_vals) == 0:
            return

        v_min = min_val if min_val is not None else np.min(valid_vals)
        v_max = max_val if max_val is not None else np.max(valid_vals)
        if v_max <= v_min:
            v_max = v_min + 1.0

        n = len(recent_values)
        pts = []
        for i, val in enumerate(recent_values):
            if np.isnan(val):
                continue
            px = sx + (i / max(1, n - 1)) * sw
            norm = (val - v_min) / (v_max - v_min)
            norm = max(0.05, min(0.95, norm))
            py = sy + sh - (norm * sh)
            pts.append((int(round(px)), int(round(py))))

        if len(pts) >= 2:
            draw.line(pts, fill=line_color, width=2 * scale)
        if pts:
            lx, ly = pts[-1]
            marker = 3 * scale
            draw.line([(lx, ly), (lx, sy + sh)], fill=MIDNIGHT.route_primary, width=scale)
            draw.rectangle((lx - marker, ly - marker, lx + marker, ly + marker), fill=MIDNIGHT.route_primary)

    @staticmethod
    def draw_card(draw: ImageDraw.Draw,
                  x: int, y: int, w: int, h: int,
                  label: str, value: str, unit: str = "",
                  color: str = MIDNIGHT.text_primary,
                  recent_trail: Optional[np.ndarray] = None,
                  trail_color: str = MIDNIGHT.text_secondary,
                  min_val: Optional[float] = None,
                  max_val: Optional[float] = None,
                  accent_color: Optional[str] = None,
                  is_mobile: bool = False,
                  scale: int = 1):
        """Flat metric row with a typographic value and optional axis chart."""
        draw.line([(x, y), (x + w, y)], fill=MIDNIGHT.border, width=scale)

        if is_mobile:
            f_label = FontManager.get_font(15 * scale, bold=True)
            f_val = FontManager.get_font(38 * scale, bold=True)
            f_unit = FontManager.get_font(17 * scale, bold=False)
            pad_x = 18 * scale
            lbl_y = y + 10 * scale
            val_y = y + 36 * scale
            spark_w = int(w * 0.44)
        else:
            f_label = FontManager.get_font(13 * scale, bold=True)
            f_val = FontManager.get_font(32 * scale, bold=True)
            f_unit = FontManager.get_font(15 * scale, bold=False)
            pad_x = 16 * scale
            lbl_y = y + 10 * scale
            val_y = y + 32 * scale
            spark_w = int(w * 0.42)

        # Rótulo
        draw.text((x + pad_x, lbl_y), label.upper(), fill=MIDNIGHT.text_muted, font=f_label)

        # Valor
        draw.text((x + pad_x, val_y), value, fill=MIDNIGHT.text_primary, font=f_val)

        # Unidade
        if unit:
            val_w = int(round(f_val.getlength(value)))
            draw.text((x + pad_x + val_w + 8 * scale, val_y + (10 if is_mobile else 8) * scale),
                      unit, fill=MIDNIGHT.text_muted, font=f_unit)

        # Sparkline trail se fornecido
        if recent_trail is not None and len(recent_trail) > 1:
            spark_x = x + w - spark_w - pad_x
            spark_y = y + 14 * scale
            spark_h = h - 28 * scale
            DashboardPainter.draw_sparkline(draw, spark_x, spark_y, spark_w, spark_h,
                                            recent_trail, line_color=trail_color,
                                            min_val=min_val, max_val=max_val, scale=scale)

    draw_metric_card = draw_card

    @staticmethod
    def draw_progress_chart(draw: ImageDraw.Draw,
                            x: int, y: int, w: int, h: int,
                            values: np.ndarray,
                            current_index: float,
                            scale: int = 1,
                            x_values: Optional[np.ndarray] = None,
                            x_ticks: Optional[Sequence[tuple[float, str]]] = None) -> None:
        """Draw a full-series axis chart with completed progress highlighted."""
        valid = np.asarray(values, dtype=float)
        if len(valid) < 2 or not np.any(np.isfinite(valid)):
            return
        v_min = float(np.nanmin(valid))
        v_max = float(np.nanmax(valid))
        span = max(v_max - v_min, 1.0)
        horizontal = np.asarray(x_values, dtype=float) if x_values is not None else np.arange(len(valid), dtype=float)
        if len(horizontal) != len(valid) or not np.all(np.isfinite(horizontal)):
            horizontal = np.arange(len(valid), dtype=float)
        h_min = float(np.min(horizontal))
        h_span = max(float(np.max(horizontal)) - h_min, 1.0)
        points = []
        for index, value in enumerate(valid):
            if not np.isfinite(value):
                continue
            px = x + int(round((horizontal[index] - h_min) / h_span * w))
            py = y + h - int(round((value - v_min) / span * h))
            points.append((px, py))
        if len(points) < 2:
            return
        if x_ticks:
            tick_font = FontManager.get_font(10 * scale, bold=True)
            for tick_value, tick_label in x_ticks:
                tick_x = x + int(round((float(tick_value) - h_min) / h_span * w))
                if x <= tick_x <= x + w:
                    draw.line([(tick_x, y), (tick_x, y + h)], fill=MIDNIGHT.grid, width=scale)
                    draw.text((tick_x + 4 * scale, y + h + 7 * scale), tick_label,
                              fill=MIDNIGHT.text_muted, font=tick_font)
        draw.line([(x, y), (x, y + h), (x + w, y + h)], fill=MIDNIGHT.border, width=scale)
        draw.line(points, fill=MIDNIGHT.text_muted, width=scale)
        position = min(max(float(current_index), 0.0), len(points) - 1)
        completed_index = int(np.floor(position))
        fraction = position - completed_index
        cx, cy = points[completed_index]
        completed_points = points[:completed_index + 1]
        if fraction > 0 and completed_index < len(points) - 1:
            nx, ny = points[completed_index + 1]
            cx = int(round(cx + (nx - cx) * fraction))
            cy = int(round(cy + (ny - cy) * fraction))
            completed_points = [*completed_points, (cx, cy)]
        if len(completed_points) >= 2:
            draw.line(completed_points, fill=MIDNIGHT.text_secondary, width=2 * scale)
        marker = 3 * scale
        draw.line([(cx, cy), (cx, y + h)], fill=MIDNIGHT.route_primary, width=scale)
        draw.rectangle((cx - marker, cy - marker, cx + marker, cy + marker), fill=MIDNIGHT.route_primary)

    @staticmethod
    def draw_progress_bar(draw: ImageDraw.Draw,
                          x: int, y: int, w: int, h: int,
                          pct: float,
                          color: str = MIDNIGHT.route_primary,
                          scale: int = 1):
        """Barra de progresso fina e elegante."""
        line_y = y + max(0, h // 2 - scale)
        draw.rectangle((x, line_y, x + w, line_y + 2 * scale), fill=MIDNIGHT.border)
        fill_w = max(int(w * min(max(pct, 0.0), 1.0)), 2 * scale)
        draw.rectangle((x, line_y, x + fill_w, line_y + 2 * scale), fill=color)
