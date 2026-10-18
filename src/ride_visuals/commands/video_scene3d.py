"""3D cartographic and terrain video orchestration (flyover, stretch, strata)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ride_visuals.commands.video import VideoCommandContext
    from ride_visuals.scene3d.flyover import FlyoverMetadata
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
    locale_tag = context.runtime.locale.lower().replace("-", "_")
    look_tag = f"_{args.look}"
    aspect_tag = args.aspect.replace(":", "_")
    preview_tag = "_preview" if args.preview else ""
    if args.video_type == "flyover":
        stem = f"flyover_{args.activity_id}{look_tag}_{aspect_tag}_{locale_tag}"
    elif args.video_type == "strata":
        period_tag = "" if args.period == "auto" else f"_{args.period}"
        stem = f"strata_{context.selection_tag}{period_tag}{look_tag}_{aspect_tag}_{locale_tag}"
    else:
        stem = f"stretch_{context.selection_tag}{look_tag}_{aspect_tag}_{locale_tag}"

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
    from ride_visuals.scene3d.strata import HOME_REGION_RADIUS_M, build_strata_spec
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
            sampler=DemSampler(cache, zoom=12),
            **common,
        )

    rides = _load_collection_rides(context)
    if args.video_type == "stretch":
        return build_stretch_spec(rides, toward=args.toward, **common)

    result = build_strata_spec(rides, period=args.period, **common)
    if result.excluded_rides > 0:
        print(
            f"[Strata] Home region: {result.kept_rides} rides kept, "
            f"{result.excluded_rides} outside {HOME_REGION_RADIUS_M / 1000:.0f} km skipped."
        )
    return result.spec


def render_scene3d(context: VideoCommandContext) -> None:
    """Build the 3D scene spec, start the local tile server, and render via Remotion."""
    from ride_visuals.credits import write_credits
    from ride_visuals.scene3d.tiles import TileCache, TileServer
    from ride_visuals.video.engines.remotion import RemotionVideoEngine

    args = context.args
    width, height, scale = _resolve_canvas(args.aspect, preview=args.preview)
    fps = 30 if args.preview else 60
    paths = _scene_paths(context)
    cache = TileCache()

    print(
        f"[Scene3D] Preparing {args.video_type} "
        f"(look: {args.look}, aspect: {args.aspect}, locale: {context.runtime.locale}, preview: {args.preview})..."
    )
    try:
        spec = _build_scene_spec(context, width, height, fps, cache)
    except ValueError as error:
        print(f"[Error] {error}")
        raise SystemExit(1) from error
    serialized = spec.write(paths.spec_path).resolve()

    engine = RemotionVideoEngine(renderer_dir=context.runtime.renderer_dir)
    with TileServer(cache) as server:
        spec_url = server.publish("scene.json", serialized)
        output, keyframes = engine.render_scene3d(
            spec,
            paths.output_file,
            spec_url=spec_url,
            scale=scale,
            keyframes_dir=paths.keyframes_dir,
        )
        failures = server.failures

    if failures > 0:
        print(f"[Warning] {failures} map tile request(s) failed during render.")
    print(f"[Video] 3D {args.video_type} generated: {output}")
    if paths.keyframes_dir:
        print(f"[Keyframes] {len(keyframes)} frames at: {paths.keyframes_dir}")
    credits = write_credits(output, spec.sources)
    if credits:
        print(f"[Credits] {credits}")
