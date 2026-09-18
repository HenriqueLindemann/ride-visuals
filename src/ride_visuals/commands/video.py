"""Video command registration and dispatch."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments
from ride_visuals.commands.options import (
    COLLECTION_MOTIONS,
    COLLECTION_STYLES,
    LOCALES,
    MAP_DETAILS,
    OVERLAY_FORMATS,
    THEMES,
    VIDEO_ASPECTS,
    VIDEO_TYPES,
)
from ride_visuals.selection import ActivitySelection


@dataclass(frozen=True)
class VideoCommandContext:
    """Resolved inputs shared by the video render branches."""

    args: argparse.Namespace
    runtime: RuntimeConfig
    outputs_dir: Path
    selection: ActivitySelection
    selection_tag: str
    write_keyframes: bool

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> VideoCommandContext:
        runtime = RuntimeConfig.from_args(args)
        return cls(
            args=args,
            runtime=runtime,
            outputs_dir=runtime.outputs_dir / "videos",
            selection=runtime.selection,
            selection_tag=runtime.selection.slug(),
            write_keyframes=not args.no_keyframes,
        )


def register(subparsers: argparse._SubParsersAction) -> None:
    from ride_visuals.maps.tiles import TILE_PROVIDERS

    parser = subparsers.add_parser("video", help="Render route, progress, and collection videos")
    parser.add_argument(
        "video_type",
        choices=VIDEO_TYPES,
        help="Video or overlay type",
    )
    parser.add_argument(
        "activity_id",
        type=int,
        nargs="?",
        default=0,
        help="Activity ID (for clean/telemetry/overlay)",
    )
    parser.add_argument(
        "--motion",
        choices=COLLECTION_MOTIONS,
        default="chronological",
        help=(
            "Collection kinematics; simultaneous/elapsed align start times and preserve the real "
            "duration of each ride"
        ),
    )
    parser.add_argument(
        "--style",
        choices=COLLECTION_STYLES,
        default="orange",
        help="Palette applied only to the route traces",
    )
    parser.add_argument(
        "--basemap",
        choices=["plain", *TILE_PROVIDERS],
        default="plain",
        help="Georeferenced basemap for collection or activity videos",
    )
    parser.add_argument(
        "--map-detail",
        choices=MAP_DETAILS,
        default="standard",
        help="Standard tiles or an extra resolution layer before downsampling",
    )
    parser.add_argument(
        "--preview", action="store_true", help="Render a short preview version"
    )
    parser.add_argument(
        "--no-keyframes",
        action="store_true",
        help="Do not extract 0/50/100 inspection frames",
    )
    layout_group = parser.add_mutually_exclusive_group()
    layout_group.add_argument(
        "--clean", action="store_true", help="Render the collection without the telemetry panel"
    )
    layout_group.add_argument(
        "--minimal",
        action="store_true",
        default=False,
        help="Minimal layout: collection with distance; activity with speed and distance",
    )
    for option in ("cursors", "legend"):
        parser.add_argument(
            f"--{option}", action=argparse.BooleanOptionalAction, default=None,
            help=f"Show collection {option} (hidden by default in minimal mode)",
        )
    parser.add_argument(
        "--aspect",
        choices=VIDEO_ASPECTS,
        default="16:9",
        help=(
            "Video canvas: landscape, vertical, horizontal Instagram Story "
            "(rotate the phone) or UHD 3840x2160"
        ),
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "remotion"],
        default="auto",
        help="Visual engine for activities and overlays",
    )
    parser.add_argument("--locale", choices=LOCALES, help="Visual language: en or pt-BR (default: en; configurable in [app].locale)")
    parser.add_argument("--theme", choices=THEMES, help="Shared visual theme")
    parser.add_argument(
        "--title",
        help="Override the title of an individual activity (an empty string hides the title)",
    )
    background_group = parser.add_mutually_exclusive_group()
    background_group.add_argument(
        "--background-image",
        type=str,
        help="JPEG/PNG/WebP image used behind the activity (incompatible with --basemap)",
    )
    background_group.add_argument(
        "--background-video",
        type=str,
        help=(
            "Video rendered behind the activity UI, with its own audio in the "
            "final MP4 (clean/telemetry; incompatible with --basemap and --background-image)"
        ),
    )
    parser.add_argument(
        "--background-video-audio",
        action=argparse.BooleanOptionalAction,
        dest="background_video_audio",
        default=True,
        help="Keep the original audio from --background-video in the delivered video",
    )
    parser.add_argument(
        "--background-blur",
        type=float,
        default=0.0,
        help="Background blur in pixels (0–100)",
    )
    parser.add_argument(
        "--background-dim",
        type=float,
        default=0.35,
        help="Background dimming (0–1)",
    )
    parser.add_argument(
        "--progress-bar",
        action=argparse.BooleanOptionalAction,
        dest="show_progress_bar",
        default=False,
        help="Show the optional progress percentage and bar in activity and collection videos",
    )
    parser.add_argument(
        "--background-tracks",
        action=argparse.BooleanOptionalAction,
        dest="background_tracks",
        default=None,
        help="Show faint background/inactive routes before they are ridden",
    )
    parser.add_argument(
        "--overlay-format",
        choices=OVERLAY_FORMATS,
        default=None,
        help="Static PNG, alpha WebM, or ProRes 4444 MOV (new overlays: WebM; overlay: PNG)",
    )
    parser.add_argument("--config", type=str, help="Path to config/config.toml")
    add_selection_arguments(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Render videos with or without telemetry, progress movies, and full collections."""
    if getattr(args, "minimal", False) and args.video_type == "telemetry":
        args.video_type = "minimal"
    context = VideoCommandContext.from_args(args)
    if args.video_type == "timeline":
        from ride_visuals.commands.video_collection import render_timeline

        return render_timeline(context)
    if args.video_type == "collection":
        from ride_visuals.commands.video_collection import render_collection

        return render_collection(context)
    if args.video_type == "progress":
        from ride_visuals.commands.video_collection import render_progress

        return render_progress(context)

    from ride_visuals.commands.video_activity import render_activity

    return render_activity(context)
