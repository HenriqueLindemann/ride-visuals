"""Collection-level video orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ride_visuals.commands.video import VideoCommandContext


def render_timeline(context: VideoCommandContext) -> None:
    from ride_visuals.video.presets import get_video_preset
    from ride_visuals.video.season_timeline import SeasonTimelineVideoRenderer

    args = context.args
    timeline_dir = context.outputs_dir / "timeline"
    aspect = args.aspect
    preset = get_video_preset("timeline", aspect, preview=args.preview)
    preview_tag = "_preview" if args.preview else ""
    output = (
        timeline_dir
        / f"timeline_{context.selection_tag}_{aspect.replace(':', '_')}{preview_tag}.mp4"
    )
    keyframes = (
        context.outputs_dir
        / "keyframes"
        / f"timeline_{aspect.replace(':', '_')}_{context.runtime.locale.lower().replace('-', '_')}"
        if context.write_keyframes
        else None
    )
    renderer = SeasonTimelineVideoRenderer(
        context.runtime.catalog_db,
        timeline_dir,
        locale=context.runtime.locale,
        theme=context.runtime.theme,
        selection=context.selection,
    )
    renderer.render(
        output,
        width=preset.canvas.width,
        height=preset.canvas.height,
        fps=preset.fps,
        duration_s=preset.duration_seconds,
        hold_s=preset.hold_seconds,
        keyframes_dir=keyframes,
    )
    print(f"[Vídeo] Timeline unificada gerada: {output}")
    if keyframes:
        print(f"[Keyframes] Frames 0/50/100 em: {keyframes}")


def render_collection(context: VideoCommandContext) -> None:
    from ride_visuals.video.collection import CollectionVideoRenderer
    from ride_visuals.video.presets import get_video_preset

    args = context.args
    collection_dir = context.outputs_dir / "collection"
    detail_tag = "_map-high" if args.map_detail == "high" else ""
    keyframes_dir = (
        context.outputs_dir
        / "keyframes"
        / (
            f"collection_{args.motion}_{args.style}_{args.basemap}{detail_tag}_"
            f"{args.aspect.replace(':', '_')}"
        )
        if context.write_keyframes
        else None
    )
    print(
        f"[Vídeo] Coleção {context.selection.describe()} "
        f"(motion: {args.motion}, basemap: {args.basemap})..."
    )
    renderer = CollectionVideoRenderer(
        context.runtime.catalog_db,
        context.runtime.streams_dir,
        collection_dir,
        locale=context.runtime.locale,
        theme=context.runtime.theme,
        selection=context.selection,
    )
    preset = get_video_preset("collection", args.aspect, preview=args.preview, clean=args.clean)
    clean_tag = "_clean" if args.clean else ""
    basemap_tag = "" if args.basemap == "plain" else f"_{args.basemap}"
    preview_tag = "_preview" if args.preview else ""
    output_file = collection_dir / (
        f"collection_{context.selection_tag}_{args.motion}_{args.style}{basemap_tag}{detail_tag}_"
        f"{args.aspect.replace(':', '_')}{clean_tag}{preview_tag}.mp4"
    )
    output_path, keyframes = renderer.render_collection(
        output_mp4_path=output_file,
        motion=args.motion,
        style=args.style,
        mode=preset.canvas.layout,
        width=preset.canvas.width,
        height=preset.canvas.height,
        fps=preset.fps,
        duration_s=preset.duration_seconds,
        hold_s=preset.hold_seconds,
        keyframes_dir=keyframes_dir,
        ssaa_scale=1 if args.aspect == "4k" else 2,
        basemap=args.basemap,
        map_detail=args.map_detail,
        show_progress_bar=args.show_progress_bar,
        show_background_tracks=args.background_tracks,
    )
    print(f"[Vídeo] Coleção gerada com sucesso em: {output_path}")
    if keyframes_dir:
        print(f"[Keyframes] {len(keyframes)} frames-chave salvos em: {keyframes_dir}")


def render_progress(context: VideoCommandContext) -> None:
    from ride_visuals.video.presets import get_video_preset
    from ride_visuals.video.progress_movie import ProgressMovieRenderer

    args = context.args
    progress_dir = context.outputs_dir / "progress"
    print(f"[Vídeo] Progresso: {context.selection.describe()}")
    renderer = ProgressMovieRenderer(
        context.runtime.catalog_db,
        context.runtime.streams_dir,
        progress_dir,
        locale=context.runtime.locale,
        theme=context.runtime.theme,
        selection=context.selection,
    )
    preset = get_video_preset("progress", args.aspect, preview=args.preview)
    preview_tag = "_preview" if args.preview else ""
    output_file = (
        progress_dir
        / f"progress_{context.selection_tag}_{args.aspect.replace(':', '_')}{preview_tag}.mp4"
    )
    keyframes_dir = (
        context.outputs_dir
        / "keyframes"
        / f"progress_{args.aspect.replace(':', '_')}_{context.runtime.locale.lower().replace('-', '_')}"
        if context.write_keyframes
        else None
    )
    renderer.render_movie(
        output_mp4_path=output_file,
        width=preset.canvas.width,
        height=preset.canvas.height,
        fps=preset.fps,
        chapter_duration_s=preset.duration_seconds,
        keyframes_dir=keyframes_dir,
    )
    print(f"[Vídeo] Filme de progresso gerado com sucesso: {output_file}")
    if keyframes_dir:
        print(f"[Keyframes] Frames 0/50/100 em: {keyframes_dir}")
