"""Animated calendar cursor for the aligned season telemetry timeline."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from PIL import Image, ImageColor, ImageDraw

from ride_visuals.analytics.season_timeline import SeasonTimelineGenerator
from ride_visuals.design import get_theme
from ride_visuals.i18n import Translator, sanitize_display_text
from ride_visuals.selection import ActivitySelection
from ride_visuals.validate.media_validator import MediaValidator
from ride_visuals.video.fonts import FontManager
from ride_visuals.video.encoding import RawVideoEncoder
from ride_visuals.video.instagram import (
    place_safe_content,
    present_frame,
    safe_content_dimensions,
)


class SeasonTimelineVideoRenderer:
    """Animate one truthful shared calendar instead of mixing telemetry units."""

    def __init__(self, catalog_db_path: Path, outputs_dir: Path, *,
                 locale: str = "pt-BR", theme: str = "midnight",
                 selection: ActivitySelection | None = None):
        self.catalog_db_path = Path(catalog_db_path)
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.i18n = Translator(locale)
        self.theme = get_theme(theme)
        self.selection = selection or ActivitySelection()

    def render(self, output_mp4_path: Path, *, width: int = 1920, height: int = 1080,
               fps: int = 30, duration_s: float = 5.0, hold_s: float = 1.0,
               keyframes_dir: Optional[Path] = None,
               presentation: str = "standard") -> Path:
        output = Path(output_mp4_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        keyframes = Path(keyframes_dir) if keyframes_dir else None
        if keyframes:
            keyframes.mkdir(parents=True, exist_ok=True)

        output_width, output_height = width, height
        width, height = safe_content_dimensions(output_width, output_height, presentation)

        with tempfile.TemporaryDirectory(prefix="ride-visuals-timeline-", dir="/tmp") as temporary:
            generator = SeasonTimelineGenerator(
                self.catalog_db_path,
                Path(temporary),
                locale=self.i18n.locale,
                theme=self.theme.name,
                selection=self.selection,
            )
            base_path = generator.generate(
                Path(temporary) / "timeline.png",
                width=width,
                height=height,
                animation_base=True,
            )
            with Image.open(base_path) as rendered:
                base = rendered.convert("RGB")
            frame = generator.load_frame()

            dates = pd.to_datetime(frame["start_date"], utc=True).dt.tz_convert(None)
            date_values = np.asarray([float(pd.Timestamp(value).value) for value in dates], dtype=float)
            start = dates.iloc[0]
            end = dates.iloc[-1]
            start_value = float(start.value)
            end_value = float(end.value)
            x_min = float((start - pd.Timedelta(days=3)).value)
            x_max = float((end + pd.Timedelta(days=3)).value)

            portrait = height > width
            base_height = 1920 if portrait else 1080
            dpi = max(30, int(round(120.0 * (height / base_height))))
            plot_left = int(round((0.12 if portrait else 0.095) * width))
            plot_right = int(round((0.92 if portrait else 0.95) * width))
            plot_top = int(round((1.0 - (0.690 if portrait else 0.730)) * height))
            plot_bottom = int(round((1.0 - 0.095) * height))
            footer_y = int(round((1.0 - 0.045) * height))
            summary_left = int(round((0.12 if portrait else 0.095) * width))
            summary_right = int(round((0.92 if portrait else 0.95) * width))
            summary_columns = 2 if portrait else 4
            summary_width = (summary_right - summary_left) / summary_columns
            canvas_rgb = ImageColor.getrgb(self.theme.canvas)
            route_rgb = ImageColor.getrgb(self.theme.route_primary)
            muted_rgb = ImageColor.getrgb(self.theme.text_muted)
            footer_font_size = max(8, int(round(9.5 * (dpi / 72.0))))
            summary_font_size = max(10, int(round(18.0 * (dpi / 72.0))))
            font = FontManager.get_font(footer_font_size, bold=True)
            summary_font = FontManager.get_font(summary_font_size, bold=True)

            animation_frames = max(1, int(round(duration_s * fps)))
            hold_frames = max(0, int(round(hold_s * fps)))
            total_frames = animation_frames + hold_frames
            keyframe_indices = {0: "00", total_frames // 2: "50", total_frames - 1: "100"}

            with RawVideoEncoder(
                output,
                width=output_width,
                height=output_height,
                fps=fps,
                operation="timeline video",
            ) as encoder:
                for frame_index in range(total_frames):
                    if frame_index < animation_frames:
                        linear = frame_index / max(animation_frames - 1, 1)
                        progress = linear * linear * (3.0 - 2.0 * linear)
                    else:
                        progress = 1.0
                    current_value = start_value + (end_value - start_value) * progress
                    cursor_x = plot_left + int(round((current_value - x_min) / (x_max - x_min) * (plot_right - plot_left)))
                    cursor_x = min(max(cursor_x, plot_left), plot_right)
                    completed = int(np.searchsorted(date_values, current_value, side="left"))
                    if progress >= 1.0:
                        completed = len(frame)
                    current_km = float(frame["distance_km"].iloc[:completed].sum())
                    current_samples = int(frame["point_count"].iloc[:completed].fillna(0).sum())
                    current_hr_rides = int(frame["has_hr_stream"].iloc[:completed].fillna(False).sum())
                    current_date = pd.Timestamp(int(round(current_value)))

                    image = base.copy()
                    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                    overlay_draw = ImageDraw.Draw(overlay)
                    if cursor_x < plot_right:
                        overlay_draw.rectangle(
                            (cursor_x, plot_top, plot_right, plot_bottom),
                            fill=(*canvas_rgb, 178),
                        )
                    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
                    draw = ImageDraw.Draw(image)

                    # Summary values are accumulated at the cursor. Labels stay fixed,
                    # making the changing quantities readable without layout movement.
                    summary_values = [
                        self.i18n.number(completed),
                        f"{self.i18n.number(current_km, 1)} km",
                        self.i18n.number(current_samples),
                        f"{current_hr_rides} / {completed}",
                    ]
                    for summary_index, value in enumerate(summary_values):
                        row = summary_index // summary_columns
                        column = summary_index % summary_columns
                        value_left = int(round(summary_left + column * summary_width)) + int(round(0.008 * width))
                        value_figure_y = (0.810 - row * 0.080) if portrait else 0.800
                        summary_value_top = int(round((1.0 - value_figure_y) * height))
                        draw.text(
                            (value_left, summary_value_top),
                            value,
                            fill=ImageColor.getrgb(self.theme.text_primary),
                            font=summary_font,
                        )

                    draw.line([(cursor_x, plot_top), (cursor_x, plot_bottom)], fill=route_rgb, width=2)
                    marker = max(3, width // 480)
                    draw.rectangle((cursor_x - marker, plot_top - marker, cursor_x + marker, plot_top + marker),
                                   fill=route_rgb)

                    # Top counters own cumulative season state. The footer instead
                    # identifies the latest completed ride at the calendar cursor.
                    if completed > 0:
                        latest = frame.iloc[completed - 1]
                        ride_name = sanitize_display_text(latest.get("name") or "")
                        if len(ride_name) > 34:
                            ride_name = f"{ride_name[:31].rstrip()}…"
                        ride_label = self.i18n.text("timeline.ride_number", number=completed)
                        ride_speed = float(latest["average_speed_kmh"])
                        footer_parts = [
                            self.i18n.date(pd.Timestamp(latest["start_date"])),
                            ride_label,
                        ]
                        if ride_name:
                            footer_parts.append(ride_name)
                        footer_parts.extend([
                            f"{self.i18n.number(float(latest['distance_km']), 1)} km",
                            f"+{self.i18n.number(float(latest['elevation_gain_m']))} m",
                            f"{self.i18n.number(ride_speed, 1)} km/h",
                        ])
                        footer_text = "  ·  ".join(footer_parts)
                    else:
                        footer_text = (
                            f"{self.i18n.date(current_date)}  ·  "
                            f"{self.i18n.text('timeline.waiting_first_ride')}"
                        )
                    footer_width = int(round(font.getlength(footer_text)))
                    draw.rectangle((plot_left, footer_y - 2, plot_right, height),
                                   fill=canvas_rgb)
                    draw.text((plot_right - footer_width, footer_y), footer_text, fill=muted_rgb, font=font)

                    final_image = present_frame(
                        place_safe_content(
                            image,
                            presentation=presentation,
                            background=self.theme.canvas,
                        ),
                        presentation=presentation,
                    )
                    if keyframes and frame_index in keyframe_indices:
                        final_image.save(
                            keyframes / f"keyframe_{keyframe_indices[frame_index]}pct.png"
                        )
                    encoder.write(final_image)

        validation = MediaValidator.validate_video(output)
        if not validation.get("valid") or validation.get("has_faststart") is not True:
            raise RuntimeError(f"Timeline video failed validation: {validation}")
        return output
