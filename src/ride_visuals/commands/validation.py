"""Generated media validation command and pure discovery helpers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments
from ride_visuals.commands.options import COLLECTION_MOTIONS, COLLECTION_STYLES
from ride_visuals.i18n import DEFAULT_LOCALE
from ride_visuals.selection import ActivitySelection


@dataclass(frozen=True)
class MediaFiles:
    mp4: tuple[Path, ...]
    alpha_videos: tuple[Path, ...]
    alpha_stills: tuple[Path, ...]

    @property
    def count(self) -> int:
        return len(self.mp4) + len(self.alpha_videos) + len(self.alpha_stills)


def final_video_paths(  # noqa: PLR0913 - every naming tag must stay explicit
    outputs_dir: Path,
    selection: ActivitySelection,
    *,
    motion: str,
    style: str,
    basemap: str,
    locale: str = DEFAULT_LOCALE,
) -> list[Path]:
    """Return the exact videos produced by the canonical final workflow."""
    slug = selection.slug()
    basemap_tag = "" if basemap == "plain" else f"_{basemap}"
    locale_tag = locale.lower().replace("-", "_")
    return [
        outputs_dir
        / "videos"
        / "collection"
        / f"collection_{slug}_{motion}_{style}{basemap_tag}_{aspect}_{locale_tag}.mp4"
        for aspect in ("16_9", "9_16")
    ] + [
        outputs_dir / "videos" / kind / f"{kind}_{slug}_{aspect}.mp4"
        for kind in ("progress", "timeline")
        for aspect in ("16_9", "9_16")
    ]


def discover_media(target_dir: Path) -> MediaFiles:
    """Discover generated media using the CLI's existing file rules."""
    return MediaFiles(
        mp4=tuple(target_dir.rglob("*.mp4")),
        alpha_videos=(*target_dir.rglob("*.webm"), *target_dir.rglob("*.mov")),
        alpha_stills=tuple(
            path for path in target_dir.rglob("*.png")
            if {"overlay", "route-overlay", "stats-overlay"}.intersection(path.parts)
        ),
    )


def _failure_details(result: dict[str, Any]) -> str:
    return result.get("error") or "; ".join(result.get("violations", [])) or "Invalid"


def _validate_media(media: MediaFiles, validator: Any) -> bool:
    all_valid = True
    for video in media.mp4:
        result = validator.validate_video(video)
        if result.get("valid"):
            print(
                f"  [OK] {video.name:<45} -> {result['width']}x{result['height']}, "
                f"{result['duration_s']}s, codec: {result['video_codec']}/"
                f"{result['audio_codec']}, faststart: {result['has_faststart']}"
            )
        else:
            print(f"  [FAIL] {video.name:<45} -> {_failure_details(result)}")
            all_valid = False

    for video in media.alpha_videos:
        result = validator.validate_transparent_video(video)
        if result.get("valid"):
            print(
                f"  [OK] {video.name:<45} -> {result['width']}x{result['height']}, "
                f"{result['duration_s']}s, alpha: yes"
            )
        else:
            print(f"  [FAIL] {video.name:<45} -> {_failure_details(result)}")
            all_valid = False

    for still in media.alpha_stills:
        result = validator.validate_transparent_still(still)
        if result.get("valid"):
            print(
                f"  [OK] {still.name:<45} -> {result['width']}x{result['height']}, alpha: yes"
            )
        else:
            print(f"  [FAIL] {still.name:<45} -> {_failure_details(result)}")
            all_valid = False
    return all_valid


def register(subparsers: argparse._SubParsersAction) -> None:
    from ride_visuals.maps.tiles import TILE_PROVIDERS

    parser = subparsers.add_parser("validate", help="Validate video and media files")
    parser.add_argument("target_dir", type=str, nargs="?", help="Target directory")
    parser.add_argument("--config", type=str, help="Path to config/config.toml")
    parser.add_argument(
        "--final-set",
        action="store_true",
        help="Validate only the six canonical outputs for the selection",
    )
    parser.add_argument("--motion", choices=COLLECTION_MOTIONS, default="chronological")
    parser.add_argument("--style", choices=COLLECTION_STYLES, default="heart_rate")
    parser.add_argument("--basemap", choices=["plain", *TILE_PROVIDERS], default="dark")
    add_selection_arguments(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Validate video outputs and generated files under outputs/."""
    from ride_visuals.validate.media_validator import MediaValidator

    runtime = RuntimeConfig.from_args(args)
    target_dir = Path(args.target_dir or runtime.outputs_dir)
    if not target_dir.exists():
        print(f"[Error] Directory {target_dir} not found.")
        raise SystemExit(1)

    if args.final_set:
        media = MediaFiles(
            mp4=tuple(
                final_video_paths(
                    target_dir,
                    runtime.selection,
                    motion=args.motion,
                    style=args.style,
                    basemap=args.basemap,
                    locale=runtime.locale,
                )
            ),
            alpha_videos=(),
            alpha_stills=(),
        )
    else:
        media = discover_media(target_dir)
    print(f"[Validation] Checking {media.count} final media files in {target_dir}...")

    all_valid = _validate_media(media, MediaValidator)
    print("--------------------------------------------------")
    if all_valid and media.count:
        print(" All media files were validated and match the output standards.")
    elif not media.count:
        print(" No media files found to validate.")
        raise SystemExit(1)
    else:
        print(" Warning: inconsistencies were found in the videos.")
        raise SystemExit(1)
