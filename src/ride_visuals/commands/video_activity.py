"""Individual activity video and overlay orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ride_visuals.commands.video import VideoCommandContext
    from ride_visuals.video.presets import VideoPreset
    from ride_visuals.video.spec import ActivityRenderSpec


OVERLAY_COMPOSITIONS = {
    "overlay": "ActivityOverlay",
    "route-overlay": "RouteOverlay",
    "stats-overlay": "StatsOverlay",
}


@dataclass(frozen=True)
class ActivityRenderPaths:
    output_file: Path
    spec_path: Path
    keyframes_dir: Path | None
    basemap_tag: str


def _activity_paths(
    context: VideoCommandContext,
    *,
    output_extension: str,
) -> ActivityRenderPaths:
    args = context.args
    locale_tag = context.runtime.locale.lower().replace("-", "_")
    basemap_tag = "" if args.basemap == "plain" else f"_{args.basemap}"
    aspect_tag = args.aspect.replace(":", "_")
    preview_tag = "_preview" if args.preview else ""
    stem = f"activity_{args.activity_id}_{args.video_type}_{context.runtime.theme}_{locale_tag}"
    output_file = (
        context.outputs_dir
        / args.video_type
        / f"{stem}{basemap_tag}_{aspect_tag}{preview_tag}.{output_extension}"
    )
    spec_path = (
        context.outputs_dir.parent / "render-specs" / f"{stem}{basemap_tag}_{aspect_tag}.json"
    )
    keyframe_kind = "_clean" if args.video_type == "clean" else ""
    keyframes_dir = (
        context.outputs_dir
        / "keyframes"
        / (
            f"activity_{args.activity_id}{keyframe_kind}_{context.runtime.theme}_{locale_tag}"
            f"{basemap_tag}_{aspect_tag}"
        )
        if context.write_keyframes
        else None
    )
    return ActivityRenderPaths(output_file, spec_path, keyframes_dir, basemap_tag)


def _load_activity_metadata(catalog_db: Path, activity_id: int) -> tuple[Any, Any] | None:
    import duckdb

    with duckdb.connect(str(catalog_db), read_only=True) as connection:
        return connection.execute(
            "SELECT name, CAST(start_date AS VARCHAR) FROM activities WHERE id = ?",
            [activity_id],
        ).fetchone()


def _ensure_background_video_duration(
    video_path: Path,
    required_duration: float,
    outputs_dir: Path,
) -> Path:
    import hashlib
    import subprocess

    from ride_visuals.video.spec import probe_video

    media = probe_video(video_path)
    if media.duration_seconds >= required_duration - 1e-3:
        return video_path

    pad_duration = max(1.0, (required_duration - media.duration_seconds) + 1.0)
    bg_dir = outputs_dir / "backgrounds"
    bg_dir.mkdir(parents=True, exist_ok=True)
    with video_path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    target_path = bg_dir / f"{digest}_padded_{required_duration!r}s.mp4"
    if target_path.exists():
        media_padded = probe_video(target_path)
        if media_padded.duration_seconds >= required_duration - 1e-3:
            return target_path

    command = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"tpad=stop_mode=clone:stop_duration={pad_duration}",
        "-t",
        f"{required_duration + 0.5}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
    ]
    if media.has_audio:
        command.extend(
            [
                "-af",
                f"apad=whole_dur={required_duration + 0.5}",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ]
        )
    else:
        command.append("-an")
    command.append(str(target_path))
    subprocess.run(command, check=True)
    return target_path


def _build_render_spec(
    context: VideoCommandContext,
    preset: VideoPreset,
    parquet_path: Path,
) -> ActivityRenderSpec:
    from ride_visuals.i18n import sanitize_display_text
    from ride_visuals.video.spec import ActivityRenderSpec, RenderProfile

    args = context.args
    activity_row = _load_activity_metadata(context.runtime.catalog_db, args.activity_id)
    title_override = args.title
    if title_override is None:
        title_override = activity_row[0] if activity_row else f"Activity {args.activity_id}"
    activity_name = sanitize_display_text(title_override)
    activity_date = str(activity_row[1]) if activity_row and activity_row[1] else None
    supports_background = args.video_type in {"clean", "telemetry"} or (
        args.video_type == "minimal" and args.overlay_format is None
    )
    background_image = (
        Path(args.background_image)
        if supports_background and args.background_image
        else None
    )
    if args.background_video and not supports_background:
        print(
            "[Aviso] --background-video se aplica apenas a vídeos clean/telemetry/minimal; "
            "o overlay permanece transparente."
        )
    background_video = (
        Path(args.background_video)
        if supports_background and args.background_video
        else None
    )
    if background_video is not None:
        required_duration = preset.duration_seconds + preset.hold_seconds
        background_video = _ensure_background_video_duration(
            background_video, required_duration, context.outputs_dir
        )
    if background_video is not None and background_image is not None:
        raise ValueError(
            "Use either --background-image or --background-video for an activity render, not both"
        )
    if background_video is not None and args.basemap != "plain":
        raise ValueError(
            "Use either --background-video or --basemap for an activity render, not both"
        )
    if background_image is not None and args.basemap != "plain":
        raise ValueError(
            "Use either --background-image or --basemap for an activity render, not both"
        )
    if args.basemap != "plain" and args.background_blur > 0.0:
        raise ValueError(
            "A georeferenced basemap cannot be blurred because scaling it would misalign the route"
        )
    # The minimal layout is map-first: faint future routes are opt-in, while
    # clean and telemetry keep their existing always-on default.
    show_background_route = (
        args.video_type != "minimal"
        if args.background_tracks is None
        else args.background_tracks
    )
    return ActivityRenderSpec.from_parquet(
        parquet_path,
        activity_id=args.activity_id,
        title=activity_name,
        activity_date=activity_date,
        locale=context.runtime.locale,
        theme=context.runtime.theme,
        profile=RenderProfile(
            width=preset.canvas.render_width,
            height=preset.canvas.render_height,
            fps=preset.fps,
            duration_seconds=preset.duration_seconds,
            hold_seconds=preset.hold_seconds,
        ),
        max_points=6000 if args.preview else None,
        background_image=background_image,
        background_video=background_video,
        background_video_audio=args.background_video_audio,
        background_blur_px=args.background_blur,
        background_dim=args.background_dim,
        show_progress_bar=args.show_progress_bar,
        show_background_route=show_background_route,
        presentation=preset.canvas.presentation,
    )


def _apply_basemap(
    context: VideoCommandContext,
    preset: VideoPreset,
    spec: ActivityRenderSpec,
) -> ActivityRenderSpec:
    from ride_visuals.maps.tiles import TILE_PROVIDERS
    from ride_visuals.video.activity_basemap import render_activity_basemap
    from ride_visuals.video.instagram import safe_insets
    from ride_visuals.video.spec import BackgroundSpec

    args = context.args
    if args.basemap == "plain":
        return spec
    background_file = (
        context.outputs_dir.parent
        / "backgrounds"
        / f"activity_{args.activity_id}_{args.basemap}_{args.aspect.replace(':', '_')}.png"
    )
    print(f"[Basemap] Gerando fundo {args.basemap} georreferenciado...")
    safe_left_px, safe_right_px = safe_insets(preset.canvas.presentation)
    render_activity_basemap(
        spec.points,
        background_file,
        provider=args.basemap,
        width=preset.canvas.render_width,
        height=preset.canvas.render_height,
        layout=args.video_type,
        map_detail=args.map_detail,
        show_progress_bar=args.show_progress_bar,
        safe_left_px=safe_left_px,
        safe_right_px=safe_right_px,
    )
    return replace(
        spec,
        background=BackgroundSpec.from_image(
            background_file,
            blur_px=0.0,
            dim=args.background_dim,
            attribution=TILE_PROVIDERS[args.basemap]["attribution"],
            attribution_bottom_px=(
                preset.canvas.render_height - int(round(preset.canvas.render_height * 0.50)) + 8
                if (
                    args.video_type == "telemetry"
                    and preset.canvas.render_height > preset.canvas.render_width
                )
                else 6
            ),
        ),
    )


def _render_with_engine(
    context: VideoCommandContext,
    spec: ActivityRenderSpec,
    paths: ActivityRenderPaths,
    output_extension: str,
) -> None:
    from ride_visuals.video.engines.remotion import RemotionVideoEngine

    args = context.args
    engine = RemotionVideoEngine(renderer_dir=context.runtime.renderer_dir)
    if args.video_type in OVERLAY_COMPOSITIONS or (
        args.video_type == "minimal" and args.overlay_format is not None
    ):
        comp = (
            "ActivityMinimalOverlay"
            if args.video_type == "minimal"
            else OVERLAY_COMPOSITIONS[args.video_type]
        )
        print(
            f"[Overlay] Renderizando {output_extension.upper()} transparente "
            f"(locale: {context.runtime.locale}, theme: {context.runtime.theme})..."
        )
        if output_extension == "png":
            output = engine.render_overlay_still(
                spec,
                paths.output_file,
                spec_path=paths.spec_path,
                composition=comp,
            )
        else:
            output = engine.render_overlay_video(
                spec,
                paths.output_file,
                spec_path=paths.spec_path,
                composition=comp,
            )
        print(f"[Overlay] Saída transparente gerada: {output}")
        return

    print(
        f"[Vídeo] Renderizando com engine visual (locale: {context.runtime.locale}, "
        f"theme: {context.runtime.theme}, preview: {args.preview})..."
    )
    composition = (
        "ActivityClean"
        if args.video_type == "clean"
        else ("ActivityMinimal" if args.video_type == "minimal" else "ActivityTelemetry")
    )
    output, keyframes = engine.render_activity(
        spec,
        paths.output_file,
        spec_path=paths.spec_path,
        keyframes_dir=paths.keyframes_dir,
        composition=composition,
    )
    print(f"[Vídeo] Gerado: {output}")
    if paths.keyframes_dir:
        print(f"[Keyframes] {len(keyframes)} frames em: {paths.keyframes_dir}")


def render_activity(context: VideoCommandContext) -> None:
    from ride_visuals.video.presets import get_video_preset

    args = context.args
    parquet_path = context.runtime.streams_dir / f"{args.activity_id}.parquet"
    if not parquet_path.exists():
        print(
            f"[Erro] Stream Parquet para atividade {args.activity_id} "
            f"não encontrado em {parquet_path}"
        )
        raise SystemExit(1)

    preset = get_video_preset(
        "activity",
        args.aspect,
        preview=args.preview,
        clean=args.video_type == "clean",
    )
    if args.video_type == "stats-overlay":
        from ride_visuals.video.presets import CanvasPreset

        if args.aspect not in {"16:9", "9:16"}:
            raise ValueError("Stats overlays support --aspect 16:9 or 9:16")
        width, height = (960, 320) if args.aspect == "16:9" else (320, 640)
        preset = replace(preset, canvas=CanvasPreset(args.aspect, width, height, args.aspect))
    is_overlay = args.video_type in OVERLAY_COMPOSITIONS or (
        args.video_type == "minimal" and args.overlay_format is not None
    )
    output_extension = (
        args.overlay_format or ("png" if args.video_type == "overlay" else "webm")
        if is_overlay
        else "mp4"
    )
    if is_overlay and args.basemap != "plain":
        raise ValueError(
            "Individual basemaps are supported by clean and telemetry videos; "
            "overlays remain reusable and transparent"
        )
    engine_name = "remotion" if args.engine == "auto" else args.engine
    if engine_name != "remotion":
        raise ValueError(f"Engine de atividade não suportado: {engine_name}")

    paths = _activity_paths(context, output_extension=output_extension)
    spec = _build_render_spec(context, preset, parquet_path)
    spec = _apply_basemap(context, preset, spec)
    _render_with_engine(context, spec, paths, output_extension)
