"""3D cartographic and terrain video orchestration (flyover, stretch, strata, territory, ascent)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ride_visuals.commands.options import SCENE3D_TYPES

if TYPE_CHECKING:
    from ride_visuals.commands.video import VideoCommandContext
    from ride_visuals.scene3d.flyover import FlyoverMetadata
    from ride_visuals.scene3d.highlights import Highlight
    from ride_visuals.scene3d.spec import SceneSpec
    from ride_visuals.scene3d.stretch import SceneRide


@dataclass(frozen=True)
class Scene3DRenderPaths:
    output_file: Path
    spec_path: Path
    keyframes_dir: Path | None


def _resolve_canvas(aspect: str, *, preview: bool) -> tuple[int, int, int]:
    if aspect == "16:9":
        return 1920, 1080, 1
    if aspect == "9:16":
        return 1080, 1920, 1
    if aspect == "4k":
        return 1920, 1080, (1 if preview else 2)
    raise ValueError("3D scenes support --aspect 16:9, 9:16, or 4k")


def _scene_paths(context: VideoCommandContext) -> Scene3DRenderPaths:
    args = context.args
    if args.video_type not in SCENE3D_TYPES:
        raise ValueError(f"Unsupported 3D scene type: {args.video_type!r}")
    locale_tag = context.runtime.locale.lower().replace("-", "_")
    look_tag = f"_{args.look}"
    aspect_tag = args.aspect.replace(":", "_")
    preview_tag = "_preview" if args.preview else ""
    if args.video_type == "flyover":
        stem = f"flyover_{args.activity_id}{look_tag}_{aspect_tag}_{locale_tag}"
    elif args.video_type in ("strata", "ascent"):
        period_tag = "" if args.period == "auto" else f"_{args.period}"
        stem = f"{args.video_type}_{context.selection_tag}{period_tag}{look_tag}_{aspect_tag}_{locale_tag}"
    else:
        stem = f"{args.video_type}_{context.selection_tag}{look_tag}_{aspect_tag}_{locale_tag}"

    output_file = context.outputs_dir / args.video_type / f"{stem}{preview_tag}.mp4"
    spec_path = context.outputs_dir.parent / "render-specs" / f"{stem}{preview_tag}.json"
    keyframes_dir = context.outputs_dir / "keyframes" / stem if context.write_keyframes else None
    return Scene3DRenderPaths(output_file=output_file, spec_path=spec_path, keyframes_dir=keyframes_dir)


def _load_flyover_metadata(catalog_db: Path, activity_id: int) -> FlyoverMetadata:
    from ride_visuals.scene3d.flyover import FlyoverMetadata

    if not catalog_db.exists():
        return FlyoverMetadata(activity_id=activity_id)
    import duckdb

    with duckdb.connect(str(catalog_db), read_only=True) as connection:
        row: tuple[Any, ...] | None = connection.execute(
            """
            SELECT name, start_date, distance_m, elevation_gain_m, moving_time_s
            FROM activities WHERE id = ?
            """,
            [activity_id],
        ).fetchone()
    if row is None:
        return FlyoverMetadata(activity_id=activity_id)
    return FlyoverMetadata(
        activity_id=activity_id,
        name=row[0],
        start_date=row[1],
        distance_m=float(row[2]) if row[2] is not None else None,
        elevation_gain_m=float(row[3]) if row[3] is not None else None,
        moving_time_s=float(row[4]) if row[4] is not None else None,
    )


def _load_highlight(catalog_db: Path, activity_id: int, locale: str) -> Highlight | None:
    """Where the ride stands among every ride of the same type in the catalog (None if unremarkable)."""
    if not catalog_db.exists():
        return None
    import duckdb

    from ride_visuals.i18n import Translator
    from ride_visuals.scene3d.highlights import RideRecord, ride_highlight

    with duckdb.connect(str(catalog_db), read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT id, start_date, distance_m, elevation_gain_m FROM activities
            WHERE activity_type IS NOT DISTINCT FROM
                (SELECT activity_type FROM activities WHERE id = ?)
            """,
            [activity_id],
        ).fetchall()
    archive = [RideRecord(int(row[0]), row[1], float(row[2] or 0.0), float(row[3] or 0.0)) for row in rows]
    ride = next((record for record in archive if record.activity_id == activity_id), None)
    return ride_highlight(ride, archive, Translator(locale)) if ride else None


def _load_collection_rides(context: VideoCommandContext) -> list[SceneRide]:
    import duckdb

    from ride_visuals.scene3d.stretch import SceneRide
    from ride_visuals.scene3d.track import RideTrack

    catalog_db = context.runtime.catalog_db
    if not catalog_db.exists():
        raise ValueError(f"Catalog database not found at {catalog_db}")
    where, params = context.selection.sql()
    query = (
        "SELECT id, start_date, distance_m, elevation_gain_m, moving_time_s "
        f"FROM activities{where} ORDER BY start_date"
    )
    with duckdb.connect(str(catalog_db), read_only=True) as connection:
        rows = connection.execute(query, params).fetchall()

    rides: list[SceneRide] = []
    for act_id, start_date, distance_m, elevation_gain_m, moving_time_s in rows:
        parquet_path = context.runtime.streams_dir / f"{act_id}.parquet"
        if not parquet_path.exists():
            continue
        track = RideTrack.from_parquet(parquet_path)
        if len(track.lon) < 2 or track.length_m < 100.0:
            continue
        rides.append(
            SceneRide(
                activity_id=int(act_id),
                start_date=start_date,
                track=track,
                distance_m=float(distance_m or track.length_m),
                elevation_gain_m=float(elevation_gain_m or 0.0),
                moving_time_s=float(moving_time_s or 0.0),
            )
        )
    if not rides:
        raise ValueError("No valid rides found for the selected scope")
    return rides


def _build_scene_spec(
    context: VideoCommandContext,
    width: int,
    height: int,
    fps: int,
    cache: Any,
) -> SceneSpec:
    from ride_visuals.scene3d.flyover import build_flyover_spec
    from ride_visuals.scene3d.places import HOME_REGION_RADIUS_M
    from ride_visuals.scene3d.strata import build_strata_spec
    from ride_visuals.scene3d.stretch import build_stretch_spec
    from ride_visuals.scene3d.terrain import DemSampler
    from ride_visuals.scene3d.track import RideTrack

    args = context.args
    common: dict[str, Any] = {
        "locale": context.runtime.locale,
        "look": args.look,
        "width": width,
        "height": height,
        "fps": fps,
        "title_override": args.title,
        "credits_on_screen": args.credits_on_screen,
    }
    if args.video_type == "flyover":
        if not args.activity_id:
            raise ValueError("Activity ID is required for video flyover.")
        parquet_path = context.runtime.streams_dir / f"{args.activity_id}.parquet"
        if not parquet_path.exists():
            raise ValueError(f"Parquet stream for activity {args.activity_id} not found at {parquet_path}")
        return build_flyover_spec(
            RideTrack.from_parquet(parquet_path),
            metadata=_load_flyover_metadata(context.runtime.catalog_db, args.activity_id),
            highlight=(
                _load_highlight(context.runtime.catalog_db, args.activity_id, context.runtime.locale)
                if getattr(args, "highlight", False)
                else None
            ),
            sampler=DemSampler(cache, zoom=12),
            **common,
        )

    rides = _load_collection_rides(context)
    if args.home:
        from ride_visuals.scene3d.places import resolve_home

        # A place settles on the most common start near it; the ascent counts climbing, not rides.
        starts = [(float(r.track.lon[0]), float(r.track.lat[0])) for r in rides]
        weights = [r.elevation_gain_m for r in rides] if args.video_type == "ascent" else None
        common["home"] = resolve_home(args.home, starts, weights, offline=bool(getattr(args, "offline", False)))
    if args.video_type == "stretch":
        return build_stretch_spec(rides, toward=args.toward, **common)
    if args.video_type == "strata":
        result = build_strata_spec(rides, period=args.period, **common)
        if result.excluded_rides > 0:
            print(
                f"[Strata] Home region: {result.kept_rides} rides kept, "
                f"{result.excluded_rides} outside {HOME_REGION_RADIUS_M / 1000:.0f} km skipped."
            )
        return result.spec
    if args.video_type == "territory":
        from ride_visuals.scene3d.territory import build_territory_spec

        territory = build_territory_spec(rides, **common)
        print(
            f"[Territory] {territory.kept_rides} rides, {territory.distinct_km:,.0f} km of different roads"
            + (f"; {territory.excluded_rides} outside the home region skipped." if territory.excluded_rides else ".")
        )
        return territory.spec
    if args.video_type == "ascent":
        from ride_visuals.scene3d.ascent import build_ascent_spec

        return build_ascent_spec(rides, period=args.period, **common)
    raise ValueError(f"Unsupported 3D scene type: {args.video_type!r}")


def _prefetch(cache: Any, spec_file: Path, *, preview: bool) -> None:
    """Fetch the scene's tiles before rendering; a final render does not start with gaps."""
    from ride_visuals.scene3d.prefetch import prefetch_tiles, scene_tiles

    tiles = scene_tiles(json.loads(spec_file.read_text(encoding="utf-8")))
    total = sum(len(keys) for keys in tiles.values())
    print(f"[Tiles] Prefetching {total} tiles ({', '.join(f'{k}: {len(v)}' for k, v in tiles.items())})...")
    step = max(1, total // 20)

    def progress(done: int, count: int) -> None:
        if done % step == 0 or done == count:
            print(f"\r[Tiles] {done}/{count}", end="", flush=True)

    report = prefetch_tiles(cache, tiles, progress=progress)
    print(f"\n[Tiles] {report.cached} cached, {report.downloaded} downloaded, {report.empty} empty upstream.")
    if report.failed:
        sample = ", ".join(f"{source} {z}/{x}/{y}" for source, (z, x, y) in report.failed[:5])
        message = f"{len(report.failed)} tile(s) could not be fetched (e.g. {sample})"
        if not preview:
            raise RuntimeError(f"{message}. Retry when the tile services respond, or render with --offline.")
        print(f"[Warning] {message}; the preview may show gaps.")


def parse_stills(raw: str) -> list[float]:
    """Times (s) from a comma-separated ``--stills`` value; an empty or negative entry is an error."""
    try:
        seconds = [float(part) for part in raw.split(",") if part.strip()]
    except ValueError as error:
        raise ValueError(f"--stills takes comma-separated seconds, got {raw!r}") from error
    if not seconds or any(value < 0 for value in seconds):
        raise ValueError(f"--stills takes comma-separated seconds, got {raw!r}")
    return seconds


def _render_stills(
    context: VideoCommandContext,
    engine: Any,
    cache: Any,
    spec: SceneSpec,
    serialized: Path,
) -> None:
    """``--stills``: PNG frames at the asked times instead of the video, into outputs/stills/<scene>/."""
    from ride_visuals.scene3d.tiles import TileServer

    try:
        seconds = parse_stills(context.args.stills)
    except ValueError as error:
        print(f"[Error] {error}")
        raise SystemExit(1) from error
    _, _, scale = _resolve_canvas(context.args.aspect, preview=context.args.preview)
    stills_dir = context.outputs_dir.parent / "stills" / _scene_paths(context).output_file.stem
    with TileServer(cache) as server:
        spec_url = server.publish("scene.json", serialized)
        written = engine.render_scene3d_stills(spec, stills_dir, spec_url=spec_url, seconds=seconds, scale=scale)
    print(f"[Stills] {len(written)} frame(s) of {spec.frames / spec.fps:.1f} s at: {stills_dir}")


def render_scene3d(context: VideoCommandContext) -> None:
    """Build the 3D scene spec, prefetch its tiles, and render it via Remotion behind a local tile server."""
    from ride_visuals.credits import write_credits
    from ride_visuals.scene3d.tiles import TileCache, TileServer
    from ride_visuals.video.engines.remotion import RemotionVideoEngine

    args = context.args
    offline = bool(getattr(args, "offline", False))
    cache = TileCache(offline=offline)
    # 3D scenes render WebGL terrain frame by frame; the default of 4 workers
    # exhausted a 16 GB / integrated-GPU machine, so default to a safe 2 and
    # let --concurrency raise it where there is headroom.
    concurrency = max(1, getattr(args, "concurrency", None) or 2)

    print(
        f"[Scene3D] Preparing {args.video_type} "
        f"(look: {args.look}, aspect: {args.aspect}, locale: {context.runtime.locale}, preview: {args.preview})..."
    )
    try:
        width, height, scale = _resolve_canvas(args.aspect, preview=args.preview)
        fps = 30 if args.preview else 60
        paths = _scene_paths(context)
        spec = _build_scene_spec(context, width, height, fps, cache)
        serialized = spec.write(paths.spec_path).resolve()
        if not offline:
            _prefetch(cache, serialized, preview=args.preview)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        print(f"[Error] {error}")
        raise SystemExit(1) from error

    engine = RemotionVideoEngine(renderer_dir=context.runtime.renderer_dir)
    if getattr(args, "stills", None):
        _render_stills(context, engine, cache, spec, serialized)
        return

    with TileServer(cache) as server:
        spec_url = server.publish("scene.json", serialized)
        output, keyframes = engine.render_scene3d(
            spec,
            paths.output_file,
            spec_url=spec_url,
            scale=scale,
            keyframes_dir=paths.keyframes_dir,
            concurrency=concurrency,
        )
        failures = server.failures
        late = sum(len(tiles) for tiles in server.downloaded.values())
        unsettled = server.unsettled_frames

    if late > 0:
        print(f"[Tiles] {late} tile(s) were not prefetched and were downloaded during the render.")
    if failures > 0:
        print(f"[Warning] {failures} map tile request(s) failed during render.")
    print(f"[Video] 3D {args.video_type} generated: {output}")
    if paths.keyframes_dir:
        print(f"[Keyframes] {len(keyframes)} frames at: {paths.keyframes_dir}")
    credits = write_credits(output, spec.sources)
    if credits:
        print(f"[Credits] {credits}")
    if unsettled:
        shown = ", ".join(str(frame) for frame in unsettled[:12]) + (" ..." if len(unsettled) > 12 else "")
        print(f"[{'Warning' if args.preview else 'Error'}] {len(unsettled)} frame(s) painted before their map tiles loaded: {shown}")
        if not args.preview:
            raise SystemExit(1)
