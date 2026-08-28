"""Ride Visuals command-line interface."""

import argparse
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
import duckdb
import tomllib
from typing import Optional

from ride_visuals.ingest.pipeline import IngestPipeline
from ride_visuals.i18n import sanitize_display_text
from ride_visuals.validate.audit import ActivityAuditor
from ride_visuals.validate.media_validator import MediaValidator
from ride_visuals.maps.generator import MapGenerator
from ride_visuals.maps.tiles import TILE_PROVIDERS
from ride_visuals.video.activity_basemap import render_activity_basemap
from ride_visuals.video.progress_movie import ProgressMovieRenderer
from ride_visuals.video.engines.remotion import RemotionVideoEngine
from ride_visuals.video.presets import get_video_preset
from ride_visuals.video.season_timeline import SeasonTimelineVideoRenderer
from ride_visuals.video.spec import ActivityRenderSpec, BackgroundSpec, RenderProfile
from ride_visuals.selection import ActivitySelection


def load_config(config_path: Optional[Path] = None) -> dict:
    if config_path is None:
        config_path = Path("config/config.toml")
    if not config_path.exists():
        return {}
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def activity_selection(args, config: dict) -> ActivitySelection:
    """Build the shared temporal selection from CLI overrides and local config."""
    configured = config.get("selection", {})
    years = getattr(args, "year", None)
    months = getattr(args, "month", None)
    return ActivitySelection.from_values(
        start_date=getattr(args, "start_date", None) or configured.get("start_date"),
        end_date=getattr(args, "end_date", None) or configured.get("end_date"),
        years=years if years is not None else configured.get("years", []),
        months=months if months is not None else configured.get("months", []),
    )


def add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start-date", help="Inclusive ISO date/time, for example 2024-02-01")
    parser.add_argument("--end-date", help="Inclusive ISO date/time, for example 2024-12-31")
    parser.add_argument("--year", type=int, action="append", help="Calendar year; repeat to select several")
    parser.add_argument("--month", type=int, choices=range(1, 13), action="append",
                        help="Calendar month (1-12); repeat to select several")


def cmd_doctor(args):
    """Executa diagnóstico do ambiente de execução e ferramentas instaladas."""
    print("==================================================")
    print(" Ride Visuals — System check")
    print("==================================================")

    tools = {
        "Python": (sys.executable, True),
        "FFmpeg": (shutil.which("ffmpeg"), True),
        "FFprobe": (shutil.which("ffprobe"), True),
        "Node": (shutil.which("node"), True),
        "npm": (shutil.which("npm"), True),
    }

    all_ok = True
    for name, (path, required) in tools.items():
        if path:
            print(f"  [OK] {name:<12} -> {path}")
        else:
            status = "[ERRO]" if required else "[AVISO (Opcional)]"
            print(f"  {status} {name:<12} -> Não encontrado no PATH")
            if required:
                all_ok = False

    # Checar módulos python
    modules = [
        "fitdecode", "gpxpy", "duckdb", "pyarrow", "pandas", "numpy",
        "matplotlib", "PIL", "dateutil", "pytz",
    ]
    for mod in modules:
        try:
            __import__(mod)
            print(f"  [OK] Python mod   -> {mod}")
        except ImportError:
            print(f"  [ERRO] Python mod -> {mod} NÃO INSTALADO")
            all_ok = False

    config = load_config()
    renderer_dir = Path(config["paths"]["renderer_dir"]) if config.get("paths", {}).get("renderer_dir") else None
    for error in RemotionVideoEngine(renderer_dir=renderer_dir).doctor():
        print(f"  [ERRO] Renderer     -> {error}")
        all_ok = False

    print("--------------------------------------------------")
    if all_ok:
        print(" Diagnóstico concluído: Ambiente pronto para execução.")
    else:
        print(" Diagnóstico com pendências: Verifique os itens acima.")
    print("==================================================")
    if not all_ok:
        raise SystemExit(1)


def cmd_ingest(args):
    """Executa a ingestão lossless de dados para DuckDB + Parquet."""
    config = load_config(Path(args.config) if args.config else None)
    bulk_dir = Path(args.bulk_dir or config.get("paths", {}).get("bulk_dir", "bulk_download"))
    catalog_db = Path(args.catalog_db or config.get("paths", {}).get("catalog_db", "data/catalog/activities.duckdb"))
    streams_dir = Path(args.streams_dir or config.get("paths", {}).get("streams_dir", "data/streams"))
    selection = ActivitySelection() if getattr(args, "all", False) else activity_selection(args, config)
    clean = getattr(args, "clean", False)
    activity_types = (
        args.activity_type
        if args.activity_type is not None
        else config.get("selection", {}).get("activity_types", ["Ride", "Pedalada"])
    )

    print(f"[Ingestão] Seleção: {selection.describe()}")
    print(f"  Fonte: {bulk_dir}")
    print(f"  Catálogo DuckDB: {catalog_db}")
    print(f"  Streams Parquet: {streams_dir}")
    if clean:
        print("  Modo: Limpeza total e reconstrução (--clean)")

    pipeline = IngestPipeline(
        bulk_dir=bulk_dir,
        catalog_db_path=catalog_db,
        streams_dir=streams_dir,
        selection=selection,
        activity_types=activity_types,
        clean=clean,
    )
    stats = pipeline.run_ingest()

    print("\n==================================================")
    print(" Ingestão Concluída com Sucesso!")
    print("==================================================")
    print(f"  Atividades no recorte:        {stats['total_scoped']}")
    print(f"  Atividades salvas:            {stats['ingested_activities']}")
    print(f"  Total de pontos de telemetria:{stats['total_points']:,}")
    print(f"  Arquivos originais:           {stats['fit_count']} FIT · {stats['tcx_count']} TCX · {stats['gpx_count']} GPX")
    print(f"  Streams com Frequência Card.: {stats['with_hr_stream']}/{stats['ingested_activities']}")
    print(f"  Streams com Velocidade expl.: {stats['with_speed_stream']}/{stats['ingested_activities']}")
    print(f"  Streams com Temperatura:      {stats['with_temp_stream']}/{stats['ingested_activities']}")
    print(f"  Streams com Watts estimados:  {stats['with_watts_stream']}/{stats['ingested_activities']}")
    print(f"  Distância total acumulada:    {stats['total_distance_m']/1000.0:.1f} km")
    print(f"  Altimetria acumulada:         {stats['total_elevation_m']:.0f} m")
    print("==================================================")


def cmd_audit(args):
    """Audita cobertura de métricas, divergências e hashes."""
    config = load_config(Path(args.config) if args.config else None)
    catalog_db = Path(args.catalog_db or config.get("paths", {}).get("catalog_db", "data/catalog/activities.duckdb"))
    streams_dir = Path(args.streams_dir or config.get("paths", {}).get("streams_dir", "data/streams"))

    selection = activity_selection(args, config)
    auditor = ActivityAuditor(catalog_db, streams_dir, selection=selection)
    res = auditor.run_audit()

    print("==================================================")
    print(f" Ride Visuals — Data audit ({selection.describe()})")
    print("==================================================")
    print(f"  Total de pedaladas:           {res['total_activities']}")
    print(f"  Período analisado:            {res['period_min']} a {res['period_max']}")
    print(f"  Distância total acumulada:    {res['total_distance_km']:.1f} km")
    print(f"  Ganho de elevação total:      {res['total_elevation_m']:.0f} m")
    print(f"  Originais no catálogo:        {res['format_counts']}")
    print(f"  FC no resumo CSV:             {res['hr_summary_count']}/{res['total_activities']}")
    print(f"  FC ponto a ponto no Parquet:  {res['hr_stream_count']}/{res['total_activities']}")
    print(f"  Velocidade explícita medida:  {res['speed_stream_count']}/{res['total_activities']}")
    print(f"  Temperatura de sensor:        {res['temp_stream_count']}/{res['total_activities']}")
    print(f"  Watts nos streams:            {res['watts_stream_count']}/{res['total_activities']}")
    print("==================================================")


def cmd_map(args):
    """Render maps for the selected activities."""
    config = load_config(Path(args.config) if args.config else None)
    catalog_db = Path(args.catalog_db or config.get("paths", {}).get("catalog_db", "data/catalog/activities.duckdb"))
    streams_dir = Path(args.streams_dir or config.get("paths", {}).get("streams_dir", "data/streams"))
    outputs_dir = Path(args.outputs_dir or config.get("paths", {}).get("outputs_dir", "outputs")) / "maps"
    locale = getattr(args, "locale", None) or config.get("app", {}).get("locale", "pt-BR")
    theme = getattr(args, "theme", None) or config.get("video", {}).get("theme", "midnight")
    selection = activity_selection(args, config)
    generator = MapGenerator(
        catalog_db_path=catalog_db,
        streams_dir=streams_dir,
        outputs_dir=outputs_dir,
        locale=locale,
        theme=theme,
        selection=selection,
    )

    basemap = getattr(args, "basemap", "dark")
    route_style = getattr(args, "route_style", "orange")
    map_detail = getattr(args, "map_detail", "standard")
    if args.map_type == "overview":
        print(f"[Mapa] Visão geral ({selection.describe()}, {args.dpi} DPI, basemap: {basemap})...")
        out_f = generator.render_overview(dpi=args.dpi, basemap=basemap, route_style=route_style, map_detail=map_detail)
        print(f"[Mapa] Salvo com sucesso em: {out_f}")

    elif args.map_type == "heatmap":
        print(f"[Mapa] Densidade ({selection.describe()}, basemap: {basemap})...")
        out_f = generator.render_heatmap(dpi=args.dpi, basemap=basemap, route_style=route_style, map_detail=map_detail)
        print(f"[Mapa] Salvo com sucesso em: {out_f}")

    elif args.map_type == "effort":
        print(f"[Mapa] Gerando mapa do espectro cardiovascular (Z1 a Z5, basemap: {basemap})...")
        out_f = generator.render_effort_map(dpi=args.dpi, basemap=basemap, map_detail=map_detail)
        print(f"[Mapa] Salvo com sucesso em: {out_f}")


from ride_visuals.video.collection import CollectionVideoRenderer
from ride_visuals.analytics.dashboard import AnalyticsDashboardGenerator
from ride_visuals.analytics.season_timeline import SeasonTimelineGenerator


def _render_timeline(args, catalog_db: Path, outputs_dir: Path, locale: str, theme: str,
                     selection: ActivitySelection, selection_tag: str, write_keyframes: bool):
    timeline_dir = outputs_dir / "timeline"
    aspect = getattr(args, "aspect", "16:9")
    is_preview = getattr(args, "preview", False)
    preset = get_video_preset("timeline", aspect, preview=is_preview)
    preview_tag = "_preview" if is_preview else ""
    output = timeline_dir / f"timeline_{selection_tag}_{aspect.replace(':', '_')}{preview_tag}.mp4"
    keyframes = (
        outputs_dir / "keyframes" / f"timeline_{aspect.replace(':', '_')}_{locale.lower().replace('-', '_')}"
        if write_keyframes else None
    )
    renderer = SeasonTimelineVideoRenderer(
        catalog_db, timeline_dir, locale=locale, theme=theme, selection=selection
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


def _render_collection(args, catalog_db: Path, streams_dir: Path, outputs_dir: Path, locale: str, theme: str,
                       selection: ActivitySelection, selection_tag: str, write_keyframes: bool):
    coll_dir = outputs_dir / "collection"
    collection_basemap = getattr(args, "basemap", "plain")
    map_detail = getattr(args, "map_detail", "standard")
    style = getattr(args, "style", "orange")
    detail_tag = "_map-high" if map_detail == "high" else ""
    keyframes_dir = (
        outputs_dir / "keyframes" / f"collection_{args.motion}_{style}_{collection_basemap}{detail_tag}_{args.aspect.replace(':', '_')}"
        if write_keyframes else None
    )
    print(f"[Vídeo] Coleção {selection.describe()} (motion: {args.motion}, basemap: {collection_basemap})...")
    renderer = CollectionVideoRenderer(
        catalog_db,
        streams_dir,
        coll_dir,
        locale=locale,
        theme=theme,
        selection=selection,
    )
    aspect = getattr(args, "aspect", "16:9")
    preset = get_video_preset(
        "collection", aspect,
        preview=getattr(args, "preview", False),
        clean=getattr(args, "clean", False),
    )
    mode = preset.canvas.layout
    w, h = preset.canvas.width, preset.canvas.height
    dur, hold = preset.duration_seconds, preset.hold_seconds
    clean_tag = "_clean" if getattr(args, "clean", False) else ""
    basemap_tag = "" if collection_basemap == "plain" else f"_{collection_basemap}"
    out_file = coll_dir / f"collection_{selection_tag}_{args.motion}_{style}{basemap_tag}{detail_tag}_{aspect.replace(':', '_')}{clean_tag}{'_preview' if args.preview else ''}.mp4"
    out_path, keyframes = renderer.render_collection(
        output_mp4_path=out_file,
        motion=args.motion,
        style=style,
        mode=mode,
        width=w,
        height=h,
        fps=preset.fps,
        duration_s=dur,
        hold_s=hold,
        keyframes_dir=keyframes_dir,
        ssaa_scale=1 if aspect == "4k" else 2,
        basemap=collection_basemap,
        map_detail=map_detail,
        show_progress_bar=getattr(args, "show_progress_bar", False),
        show_background_tracks=getattr(args, "background_tracks", None),
    )
    print(f"[Vídeo] Coleção gerada com sucesso em: {out_path}")
    if keyframes_dir:
        print(f"[Keyframes] {len(keyframes)} frames-chave salvos em: {keyframes_dir}")


def _render_progress(args, catalog_db: Path, streams_dir: Path, outputs_dir: Path, locale: str, theme: str,
                     selection: ActivitySelection, selection_tag: str, write_keyframes: bool):
    prog_dir = outputs_dir / "progress"
    print(f"[Vídeo] Progresso: {selection.describe()}")
    renderer = ProgressMovieRenderer(
        catalog_db, streams_dir, prog_dir, locale=locale, theme=theme, selection=selection
    )
    aspect = getattr(args, "aspect", "16:9")
    preset = get_video_preset("progress", aspect, preview=getattr(args, "preview", False))
    w, h = preset.canvas.width, preset.canvas.height
    dur = preset.duration_seconds
    preview_tag = "_preview" if getattr(args, "preview", False) else ""
    out_file = prog_dir / f"progress_{selection_tag}_{aspect.replace(':', '_')}{preview_tag}.mp4"
    progress_keyframes = (
        outputs_dir / "keyframes" / f"progress_{aspect.replace(':', '_')}_{locale.lower().replace('-', '_')}"
        if write_keyframes else None
    )
    renderer.render_movie(
        output_mp4_path=out_file,
        width=w,
        height=h,
        fps=preset.fps,
        chapter_duration_s=dur,
        keyframes_dir=progress_keyframes,
    )
    print(f"[Vídeo] Filme de progresso gerado com sucesso: {out_file}")
    if progress_keyframes:
        print(f"[Keyframes] Frames 0/50/100 em: {progress_keyframes}")


def _render_activity(args, catalog_db: Path, streams_dir: Path, outputs_dir: Path, locale: str, theme: str,
                     write_keyframes: bool):
    act_id = args.activity_id
    engine_name = getattr(args, "engine", "auto")
    if engine_name == "auto":
        engine_name = "remotion"
    parquet_path = streams_dir / f"{act_id}.parquet"
    if not parquet_path.exists():
        print(f"[Erro] Stream Parquet para atividade {act_id} não encontrado em {parquet_path}")
        sys.exit(1)

    is_preview = getattr(args, "preview", False)
    aspect = getattr(args, "aspect", "16:9")
    preset = get_video_preset("activity", aspect, preview=is_preview, clean=args.video_type == "clean")
    w, h = preset.canvas.width, preset.canvas.height
    dur, hold = preset.duration_seconds, preset.hold_seconds

    sub_dir = outputs_dir / args.video_type
    locale_tag = locale.lower().replace("-", "_")
    output_extension = getattr(args, "overlay_format", "png") if args.video_type == "overlay" else "mp4"
    activity_basemap = getattr(args, "basemap", "plain")
    if args.video_type == "overlay" and activity_basemap != "plain":
        raise ValueError("Individual basemaps are supported by clean and telemetry videos; overlays remain reusable and transparent")
    basemap_tag = "" if activity_basemap == "plain" else f"_{activity_basemap}"
    output_file = sub_dir / f"activity_{act_id}_{args.video_type}_{theme}_{locale_tag}{basemap_tag}_{aspect.replace(':', '_')}{'_preview' if is_preview else ''}.{output_extension}"

    if engine_name != "remotion":
        raise ValueError(f"Engine de atividade não suportado: {engine_name}")

    with duckdb.connect(str(catalog_db), read_only=True) as con:
        activity_row = con.execute(
            "SELECT name, CAST(start_date AS VARCHAR) FROM activities WHERE id = ?",
            [act_id],
        ).fetchone()
    title_override = getattr(args, "title", None)
    if title_override is None:
        title_override = activity_row[0] if activity_row else f"Activity {act_id}"
    activity_name = sanitize_display_text(title_override)
    activity_date = str(activity_row[1]) if activity_row and activity_row[1] else None
    background_image = (
        Path(args.background_image)
        if args.video_type in {"clean", "telemetry"} and getattr(args, "background_image", None)
        else None
    )
    if background_image is not None and activity_basemap != "plain":
        raise ValueError("Use either --background-image or --basemap for an activity render, not both")
    background_blur = float(getattr(args, "background_blur", 0.0))
    if activity_basemap != "plain" and background_blur > 0.0:
        raise ValueError("A georeferenced basemap cannot be blurred because scaling it would misalign the route")

    spec = ActivityRenderSpec.from_parquet(
        parquet_path,
        activity_id=act_id,
        title=activity_name,
        activity_date=activity_date,
        locale=locale,
        theme=theme,
        profile=RenderProfile(
            width=w,
            height=h,
            fps=preset.fps,
            duration_seconds=dur,
            hold_seconds=hold,
        ),
        max_points=6000 if is_preview else None,
        background_image=background_image,
        background_blur_px=background_blur,
        background_dim=float(getattr(args, "background_dim", 0.35)),
        show_progress_bar=getattr(args, "show_progress_bar", False),
        show_background_route=True if getattr(args, "background_tracks", None) is None else getattr(args, "background_tracks", None),
    )
    if activity_basemap != "plain":
        background_file = (
            outputs_dir.parent
            / "backgrounds"
            / f"activity_{act_id}_{activity_basemap}_{aspect.replace(':', '_')}.png"
        )
        print(f"[Basemap] Gerando fundo {activity_basemap} georreferenciado...")
        render_activity_basemap(
            spec.points,
            background_file,
            provider=activity_basemap,
            width=w,
            height=h,
            layout="clean" if args.video_type == "clean" else "telemetry",
            map_detail=getattr(args, "map_detail", "standard"),
            show_progress_bar=getattr(args, "show_progress_bar", False),
        )
        spec = replace(
            spec,
            background=BackgroundSpec.from_image(
                background_file,
                blur_px=0.0,
                dim=float(getattr(args, "background_dim", 0.35)),
                attribution=TILE_PROVIDERS[activity_basemap]["attribution"],
                attribution_bottom_px=(
                    h - int(round(h * 0.50)) + 8  # MAP_SHARE_PORTRAIT in renderer/src/design/layout.ts
                    if args.video_type == "telemetry" and h > w
                    else 6
                ),
            ),
        )
    spec_path = outputs_dir.parent / "render-specs" / f"activity_{act_id}_{args.video_type}_{theme}_{locale_tag}{basemap_tag}_{aspect.replace(':', '_')}.json"
    keyframe_kind = "_clean" if args.video_type == "clean" else ""
    keyframes_dir = (
        outputs_dir / "keyframes" / f"activity_{act_id}{keyframe_kind}_{theme}_{locale_tag}{basemap_tag}_{aspect.replace(':', '_')}"
        if write_keyframes else None
    )
    config = load_config(Path(args.config) if getattr(args, "config", None) else None)
    renderer_dir = Path(config["paths"]["renderer_dir"]) if config.get("paths", {}).get("renderer_dir") else None
    engine = RemotionVideoEngine(renderer_dir=renderer_dir)
    if args.video_type == "overlay":
        print(f"[Overlay] Renderizando {output_extension.upper()} transparente (locale: {locale}, theme: {theme})...")
        if output_extension == "png":
            output = engine.render_overlay_still(spec, output_file, spec_path=spec_path)
        else:
            output = engine.render_overlay_video(spec, output_file, spec_path=spec_path)
        print(f"[Overlay] Saída transparente gerada: {output}")
        return

    print(f"[Vídeo] Renderizando com engine visual (locale: {locale}, theme: {theme}, preview: {is_preview})...")
    output, keyframes = engine.render_activity(
        spec,
        output_file,
        spec_path=spec_path,
        keyframes_dir=keyframes_dir,
        composition="ActivityClean" if args.video_type == "clean" else "ActivityTelemetry",
    )
    print(f"[Vídeo] Gerado: {output}")
    if keyframes_dir:
        print(f"[Keyframes] {len(keyframes)} frames em: {keyframes_dir}")


def cmd_video(args):
    """Renderiza vídeos com ou sem telemetria, filme de progresso e coleções completas."""
    config = load_config(Path(args.config) if args.config else None)
    streams_dir = Path(config.get("paths", {}).get("streams_dir", "data/streams"))
    catalog_db = Path(config.get("paths", {}).get("catalog_db", "data/catalog/activities.duckdb"))
    outputs_dir = Path(config.get("paths", {}).get("outputs_dir", "outputs")) / "videos"
    locale = getattr(args, "locale", None) or config.get("app", {}).get("locale", "pt-BR")
    theme = getattr(args, "theme", None) or config.get("video", {}).get("theme", "midnight")
    selection = activity_selection(args, config)
    selection_tag = selection.slug()
    write_keyframes = not getattr(args, "no_keyframes", False)

    if args.video_type == "timeline":
        return _render_timeline(args, catalog_db, outputs_dir, locale, theme, selection, selection_tag, write_keyframes)
    if args.video_type == "collection":
        return _render_collection(args, catalog_db, streams_dir, outputs_dir, locale, theme, selection, selection_tag, write_keyframes)
    if args.video_type == "progress":
        return _render_progress(args, catalog_db, streams_dir, outputs_dir, locale, theme, selection, selection_tag, write_keyframes)
    return _render_activity(args, catalog_db, streams_dir, outputs_dir, locale, theme, write_keyframes)



def cmd_report(args):
    """Gera relatórios de dados, dashboards e progresso esportivo."""
    config = load_config(Path(args.config) if args.config else None)
    streams_dir = Path(config.get("paths", {}).get("streams_dir", "data/streams"))
    catalog_db = Path(config.get("paths", {}).get("catalog_db", "data/catalog/activities.duckdb"))
    reports_dir = Path(config.get("paths", {}).get("outputs_dir", "outputs")) / "reports"
    locale = getattr(args, "locale", None) or config.get("app", {}).get("locale", "pt-BR")
    theme = getattr(args, "theme", None) or config.get("video", {}).get("theme", "midnight")
    selection = activity_selection(args, config)
    reports_dir.mkdir(parents=True, exist_ok=True)

    if args.report_type == "dashboard":
        print("[Relatório] Gerando painel visual e infográfico de analytics esportivo...")
        gen = AnalyticsDashboardGenerator(
            catalog_db, streams_dir, reports_dir,
            locale=locale, theme=theme, selection=selection,
        )
        out_f = gen.generate_dashboard(
            reports_dir / f"ride_summary_{selection.slug()}.png"
        )
        print(f"[Relatório] Infográfico gerado com sucesso em: {out_f}")
        return

    if args.report_type == "timeline":
        print("[Relatório] Gerando timeline unificada da telemetria...")
        generator = SeasonTimelineGenerator(
            catalog_db, reports_dir, locale=locale, theme=theme, selection=selection
        )
        locale_tag = locale.lower().replace("-", "_")
        out_f = generator.generate(
            reports_dir / f"ride_telemetry_timeline_{selection.slug()}_{locale_tag}_16_9.png"
        )
        print(f"[Relatório] Timeline gerada com sucesso em: {out_f}")
        return

    renderer = ProgressMovieRenderer(
        catalog_db, streams_dir, reports_dir,
        locale=locale, theme=theme, selection=selection,
    )
    metrics = renderer.extract_summary_metrics()

    out_json = reports_dir / f"progress_metrics_{selection.slug()}.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[Relatório] Métricas consolidadas exportadas em: {out_json}")


def final_video_paths(outputs_dir: Path, selection: ActivitySelection, *,
                      motion: str, style: str, basemap: str) -> list[Path]:
    """Return the exact videos produced by the canonical final workflow."""
    slug = selection.slug()
    basemap_tag = "" if basemap == "plain" else f"_{basemap}"
    return [
        outputs_dir / "videos" / "collection"
        / f"collection_{slug}_{motion}_{style}{basemap_tag}_{aspect}.mp4"
        for aspect in ("16_9", "9_16")
    ] + [
        outputs_dir / "videos" / kind / f"{kind}_{slug}_{aspect}.mp4"
        for kind in ("progress", "timeline")
        for aspect in ("16_9", "9_16")
    ]


def cmd_validate(args):
    """Valida saídas de vídeo e arquivos gerados em outputs/."""
    config = load_config(Path(args.config) if args.config else None)
    target_dir = Path(
        args.target_dir
        or config.get("paths", {}).get("outputs_dir", "outputs")
    )
    if not target_dir.exists():
        print(f"[Erro] Diretório {target_dir} não encontrado.")
        sys.exit(1)

    if getattr(args, "final_set", False):
        selection = activity_selection(args, config)
        mp4_files = final_video_paths(
            target_dir,
            selection,
            motion=args.motion,
            style=args.style,
            basemap=args.basemap,
        )
        alpha_videos: list[Path] = []
        alpha_stills: list[Path] = []
    else:
        mp4_files = list(target_dir.rglob("*.mp4"))
        alpha_videos = [*target_dir.rglob("*.webm"), *target_dir.rglob("*.mov")]
        alpha_stills = [path for path in target_dir.rglob("*.png") if "overlay" in path.parts]
    media_count = len(mp4_files) + len(alpha_videos) + len(alpha_stills)
    print(f"[Validação] Analisando {media_count} mídias finais em {target_dir}...")

    all_valid = True
    for v in mp4_files:
        res = MediaValidator.validate_video(v)
        if res.get("valid"):
            print(f"  [OK] {v.name:<45} -> {res['width']}x{res['height']}, {res['duration_s']}s, codec: {res['video_codec']}/{res['audio_codec']}, faststart: {res['has_faststart']}")
        else:
            details = res.get("error") or "; ".join(res.get("violations", [])) or "Inválido"
            print(f"  [FALHA] {v.name:<45} -> {details}")
            all_valid = False

    for video in alpha_videos:
        res = MediaValidator.validate_transparent_video(video)
        if res.get("valid"):
            print(f"  [OK] {video.name:<45} -> {res['width']}x{res['height']}, {res['duration_s']}s, alpha: sim")
        else:
            details = res.get("error") or "; ".join(res.get("violations", [])) or "Inválido"
            print(f"  [FALHA] {video.name:<45} -> {details}")
            all_valid = False

    for still in alpha_stills:
        res = MediaValidator.validate_transparent_still(still)
        if res.get("valid"):
            print(f"  [OK] {still.name:<45} -> {res['width']}x{res['height']}, alpha: sim")
        else:
            details = res.get("error") or "; ".join(res.get("violations", [])) or "Inválido"
            print(f"  [FALHA] {still.name:<45} -> {details}")
            all_valid = False

    print("--------------------------------------------------")
    if all_valid and media_count:
        print(" Todas as mídias foram validadas e estão conformes com os padrões de saída.")
    elif not media_count:
        print(" Nenhuma mídia encontrada para validação.")
        raise SystemExit(1)
    else:
        print(" Atenção: Foram encontradas inconsistências nos vídeos.")
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description="Ride Visuals CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # doctor
    p_doc = subparsers.add_parser("doctor", help="Verifica ambiente e dependências")
    p_doc.set_defaults(func=cmd_doctor)

    # ingest
    p_ing = subparsers.add_parser("ingest", help="Ingestão lossless de atividades")
    add_selection_arguments(p_ing)
    p_ing.add_argument("--all", action="store_true", help="Ingere todas as atividades do arquivo ignorando filtros temporais")
    p_ing.add_argument("--clean", action="store_true", help="Limpa o catálogo DuckDB e streams antes de iniciar a ingestão")
    p_ing.add_argument("--activity-type", action="append",
                       help="Activity type to ingest; repeat to select several")
    p_ing.add_argument("--bulk-dir", type=str, help="Caminho para o diretório bulk_download")
    p_ing.add_argument("--catalog-db", type=str, help="Caminho para o DuckDB de catálogo")
    p_ing.add_argument("--streams-dir", type=str, help="Caminho para pasta de Parquet streams")
    p_ing.add_argument("--config", type=str, help="Caminho para config/config.toml")
    p_ing.set_defaults(func=cmd_ingest)

    # audit
    p_aud = subparsers.add_parser("audit", help="Audita dados e cobertura de telemetria")
    p_aud.add_argument("--catalog-db", type=str, help="Caminho para o DuckDB de catálogo")
    p_aud.add_argument("--streams-dir", type=str, help="Caminho para pasta de Parquet streams")
    p_aud.add_argument("--config", type=str, help="Caminho para config/config.toml")
    add_selection_arguments(p_aud)
    p_aud.set_defaults(func=cmd_audit)

    # map
    p_map = subparsers.add_parser("map", help="Gera mapas cartográficos e heatmaps")
    p_map.add_argument("map_type", choices=["overview", "heatmap", "effort"], help="Tipo de mapa")
    add_selection_arguments(p_map)
    p_map.add_argument("--basemap", choices=["plain", *TILE_PROVIDERS], default="dark", help="Provedor de mapa base")
    p_map.add_argument("--dpi", type=int, default=300, help="Resolução DPI da imagem")
    p_map.add_argument("--map-detail", choices=["standard", "high"], default="standard", help="Tiles padrão ou uma camada extra de resolução antes do downsample")
    p_map.add_argument("--route-style", choices=["orange", "monochrome", "monthly"], default="orange", help="Paleta aplicada somente aos traçados")
    p_map.add_argument("--locale", choices=["en", "pt-BR"], help="Idioma do conteúdo visual")
    p_map.add_argument("--theme", choices=["midnight", "frost"], help="Tema editorial compartilhado")
    p_map.add_argument("--catalog-db", type=str, help="Caminho para o DuckDB de catálogo")
    p_map.add_argument("--streams-dir", type=str, help="Caminho para pasta de Parquet streams")
    p_map.add_argument("--outputs-dir", type=str, help="Caminho para pasta de saídas")
    p_map.add_argument("--config", type=str, help="Caminho para config/config.toml")
    p_map.set_defaults(func=cmd_map)

    # video
    p_vid = subparsers.add_parser("video", help="Renderiza vídeos de rotas, progresso e coleções")
    p_vid.add_argument("video_type", choices=["clean", "telemetry", "overlay", "progress", "collection", "timeline"], help="Tipo de vídeo ou overlay")
    p_vid.add_argument("activity_id", type=int, nargs="?", default=0, help="ID da atividade (para clean/telemetry/overlay)")
    p_vid.add_argument("--motion", choices=["simultaneous", "elapsed", "chronological", "comet"], default="chronological", help="Cinemática da coleção; elapsed alinha as largadas e preserva a duração real de cada rota")
    p_vid.add_argument("--style", choices=["orange", "density", "monochrome", "monthly", "heart_rate", "temperature", "altitude", "speed", "grade"], default="orange", help="Paleta aplicada somente aos traçados")
    p_vid.add_argument("--basemap", choices=["plain", *TILE_PROVIDERS], default="plain", help="Fundo georreferenciado para vídeos de coleção ou atividade")
    p_vid.add_argument("--map-detail", choices=["standard", "high"], default="standard", help="Tiles padrão ou uma camada extra de resolução antes do downsample")
    p_vid.add_argument("--preview", action="store_true", help="Renderiza versão curta/preview rápido")
    p_vid.add_argument("--no-keyframes", action="store_true", help="Não extrai frames de inspeção 0/50/100")
    p_vid.add_argument("--clean", action="store_true", help="Renderiza coleção sem painel de telemetria")
    p_vid.add_argument("--aspect", choices=["16:9", "9:16", "4k"], default="16:9", help="Canvas do vídeo: paisagem, vertical ou UHD 3840x2160")
    p_vid.add_argument("--engine", choices=["auto", "remotion"], default="auto", help="Motor visual para atividades e overlays")
    p_vid.add_argument("--locale", choices=["en", "pt-BR"], help="Idioma do conteúdo visual")
    p_vid.add_argument("--theme", choices=["midnight", "frost"], help="Tema visual compartilhado")
    p_vid.add_argument("--title", help="Override the title of an individual activity (an empty string hides the title)")
    p_vid.add_argument("--background-image", type=str, help="Imagem JPEG/PNG/WebP usada atrás da atividade (incompatível com --basemap)")
    p_vid.add_argument("--background-blur", type=float, default=0.0, help="Desfoque do fundo em pixels (0–100)")
    p_vid.add_argument("--background-dim", type=float, default=0.35, help="Escurecimento do fundo (0–1)")
    p_vid.add_argument(
        "--progress-bar",
        action=argparse.BooleanOptionalAction,
        dest="show_progress_bar",
        default=False,
        help="Show the optional progress percentage and bar in activity and collection videos",
    )
    p_vid.add_argument(
        "--background-tracks",
        action=argparse.BooleanOptionalAction,
        dest="background_tracks",
        default=None,
        help="Show faint background/inactive routes before they are ridden",
    )
    p_vid.add_argument("--overlay-format", choices=["png", "webm", "mov"], default="png", help="PNG estático, WebM alpha ou ProRes 4444 MOV")
    p_vid.add_argument("--config", type=str, help="Caminho para config/config.toml")
    add_selection_arguments(p_vid)
    p_vid.set_defaults(func=cmd_video)

    # report
    p_rep = subparsers.add_parser("report", help="Gera relatórios consolidados e dashboards")
    p_rep.add_argument("report_type", choices=["progress", "dashboard", "timeline"], help="Tipo de relatório")
    p_rep.add_argument("--config", type=str, help="Caminho para config/config.toml")
    p_rep.add_argument("--locale", choices=["en", "pt-BR"], help="Idioma do conteúdo visual")
    p_rep.add_argument("--theme", choices=["midnight", "frost"], help="Tema editorial compartilhado")
    add_selection_arguments(p_rep)
    p_rep.set_defaults(func=cmd_report)

    # validate
    p_val = subparsers.add_parser("validate", help="Valida arquivos de vídeo e mídia")
    p_val.add_argument("target_dir", type=str, nargs="?", help="Diretório alvo")
    p_val.add_argument("--config", type=str, help="Caminho para config/config.toml")
    p_val.add_argument("--final-set", action="store_true", help="Valida somente as seis saídas canônicas do recorte")
    p_val.add_argument("--motion", choices=["simultaneous", "elapsed", "chronological", "comet"], default="chronological")
    p_val.add_argument("--style", choices=["orange", "density", "monochrome", "monthly", "heart_rate", "temperature", "altitude", "speed", "grade"], default="heart_rate")
    p_val.add_argument("--basemap", choices=["plain", *TILE_PROVIDERS], default="dark")
    add_selection_arguments(p_val)
    p_val.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
