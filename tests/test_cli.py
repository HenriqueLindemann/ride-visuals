from __future__ import annotations

from pathlib import Path

import pytest

from ride_visuals.cli import build_parser, load_config, main
from ride_visuals.commands.common import RuntimeConfig
from ride_visuals.commands.validation import discover_media, final_video_paths
from ride_visuals.selection import ActivitySelection


@pytest.mark.parametrize(
    ("arguments", "command"),
    [
        (["doctor"], "doctor"),
        (["ingest"], "ingest"),
        (["ingest-fit", "ride.fit"], "ingest-fit"),
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


def test_video_parser_rejects_multiple_background_sources() -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(
            [
                "video",
                "telemetry",
                "42",
                "--background-image",
                "photo.jpg",
                "--background-video",
                "clip.mp4",
            ]
        )

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


@pytest.mark.parametrize("minimal", [False, True])
def test_collection_dispatch_preserves_output_and_keyframe_options(
    minimal: bool,
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
            *(["--minimal", "--cursors", "--legend"] if minimal else []),
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
        / (
            "videos/collection/collection_all_chronological_grade_dark_9_16"
            + ("_minimal" if minimal else "")
            + "_en_preview.mp4"
        )
    )
    assert render["keyframes_dir"] is None
    assert render["mode"] == ("minimal" if minimal else "9:16")
    assert render["show_cursors"] == (True if minimal else None)
    assert render["show_legend"] == (True if minimal else None)
    if not minimal:
        expected_final = final_video_paths(
            reference_cli_workspace.outputs_dir,
            ActivitySelection(),
            motion="chronological",
            style="grade",
            basemap="dark",
            locale="en",
        )
        assert render["output_mp4_path"].name == expected_final[1].name.replace(
            ".mp4", "_preview.mp4"
        )
