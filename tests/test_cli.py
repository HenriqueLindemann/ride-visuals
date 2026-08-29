from __future__ import annotations

from pathlib import Path

import pytest

from ride_visuals.cli import build_parser, load_config, main
from ride_visuals.commands.common import RuntimeConfig
from ride_visuals.commands.options import (
    COLLECTION_MOTIONS,
    COLLECTION_STYLES,
    LOCALES,
    MAP_DETAILS,
    MAP_ROUTE_STYLES,
    OVERLAY_FORMATS,
    THEMES,
    VIDEO_ASPECTS,
    VIDEO_TYPES,
)
from ride_visuals.commands.validation import discover_media
from ride_visuals.maps.tiles import TILE_PROVIDERS


def _command_parser(command: str):
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if action.dest == "command"
    )
    return subparsers.choices[command]


def _choices(command: str, destination: str) -> tuple[str, ...]:
    parser = _command_parser(command)
    action = next(action for action in parser._actions if action.dest == destination)
    return tuple(action.choices)


@pytest.mark.parametrize(
    ("arguments", "command"),
    [
        (["doctor"], "doctor"),
        (["ingest"], "ingest"),
        (["audit"], "audit"),
        (["map", "overview"], "map"),
        (["video", "collection"], "video"),
        (["report", "progress"], "report"),
        (["validate"], "validate"),
    ],
)
def test_parser_registers_every_command(arguments: list[str], command: str) -> None:
    args = build_parser().parse_args(arguments)

    assert args.command == command
    assert callable(args.func)


def test_video_parser_preserves_defaults_and_choices() -> None:
    args = build_parser().parse_args(["video", "collection"])

    assert args.activity_id == 0
    assert args.motion == "chronological"
    assert args.style == "orange"
    assert args.basemap == "plain"
    assert args.map_detail == "standard"
    assert args.aspect == "16:9"
    assert args.engine == "auto"
    assert args.overlay_format == "png"
    assert args.show_progress_bar is False
    assert args.background_tracks is None
    assert _choices("video", "video_type") == VIDEO_TYPES
    assert _choices("video", "motion") == COLLECTION_MOTIONS
    assert _choices("video", "style") == COLLECTION_STYLES
    assert _choices("video", "basemap") == ("plain", *TILE_PROVIDERS)
    assert _choices("video", "map_detail") == MAP_DETAILS
    assert _choices("video", "aspect") == VIDEO_ASPECTS
    assert _choices("video", "locale") == LOCALES
    assert _choices("video", "theme") == THEMES
    assert _choices("video", "overlay_format") == OVERLAY_FORMATS


def test_other_parser_choices_and_defaults_remain_stable() -> None:
    map_args = build_parser().parse_args(["map", "heatmap"])
    validate_args = build_parser().parse_args(["validate"])

    assert _choices("map", "map_type") == ("overview", "heatmap", "effort")
    assert _choices("map", "route_style") == MAP_ROUTE_STYLES
    assert map_args.basemap == "dark"
    assert map_args.dpi == 300
    assert validate_args.motion == "chronological"
    assert validate_args.style == "heart_rate"
    assert validate_args.basemap == "dark"


def test_parser_still_requires_a_command() -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args([])

    assert error.value.code == 2


def test_runtime_config_preserves_config_and_cli_precedence(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.toml"
    config_path.write_text(
        """
[app]
locale = "en"

[video]
theme = "frost"

[selection]
start_date = "2024-02-01"
years = [2024]
months = [4]
activity_types = ["Ride"]

[paths]
bulk_dir = "configured-bulk"
catalog_db = "configured.duckdb"
streams_dir = "configured-streams"
outputs_dir = "configured-outputs"
renderer_dir = "configured-renderer"
""".strip(),
        encoding="utf-8",
    )
    args = build_parser().parse_args(
        [
            "map",
            "overview",
            "--config",
            str(config_path),
            "--catalog-db",
            "override.duckdb",
            "--locale",
            "pt-BR",
            "--year",
            "2025",
        ]
    )

    runtime = RuntimeConfig.from_args(args)

    assert runtime.bulk_dir == Path("configured-bulk")
    assert runtime.catalog_db == Path("override.duckdb")
    assert runtime.streams_dir == Path("configured-streams")
    assert runtime.outputs_dir == Path("configured-outputs")
    assert runtime.renderer_dir == Path("configured-renderer")
    assert runtime.locale == "pt-BR"
    assert runtime.theme == "frost"
    assert runtime.selection.start_date is not None
    assert runtime.selection.start_date.date().isoformat() == "2024-02-01"
    assert runtime.selection.years == (2025,)
    assert runtime.selection.months == (4,)
    assert runtime.activity_types == ["Ride"]


def test_missing_config_path_still_returns_empty_config(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.toml") == {}


def test_media_discovery_preserves_file_classification(tmp_path: Path) -> None:
    (tmp_path / "movie.mp4").touch()
    (tmp_path / "alpha.webm").touch()
    (tmp_path / "alpha.mov").touch()
    (tmp_path / "ordinary.png").touch()
    overlay_dir = tmp_path / "overlay"
    overlay_dir.mkdir()
    (overlay_dir / "still.png").touch()

    media = discover_media(tmp_path)

    assert media.mp4 == (tmp_path / "movie.mp4",)
    assert media.alpha_videos == (tmp_path / "alpha.webm", tmp_path / "alpha.mov")
    assert media.alpha_stills == (overlay_dir / "still.png",)


def test_collection_dispatch_preserves_output_and_keyframe_options(
    reference_cli_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeCollectionRenderer:
        def __init__(self, catalog_db, streams_dir, output_dir, **kwargs):
            captured["init"] = (catalog_db, streams_dir, output_dir, kwargs)

        def render_collection(self, **kwargs):
            captured["render"] = kwargs
            return kwargs["output_mp4_path"], []

    monkeypatch.setattr(
        "ride_visuals.video.collection.CollectionVideoRenderer",
        FakeCollectionRenderer,
    )

    main(
        [
            "video",
            "collection",
            "--preview",
            "--no-keyframes",
            "--aspect",
            "9:16",
            "--style",
            "grade",
            "--basemap",
            "dark",
            "--config",
            str(reference_cli_workspace.config_path),
        ]
    )

    render = captured["render"]
    assert render["output_mp4_path"] == (
        reference_cli_workspace.outputs_dir
        / "videos/collection/collection_all_chronological_grade_dark_9_16_preview.mp4"
    )
    assert render["keyframes_dir"] is None
    assert render["width"] == 1080
    assert render["height"] == 1920
    assert render["show_progress_bar"] is False
    assert render["show_background_tracks"] is None
