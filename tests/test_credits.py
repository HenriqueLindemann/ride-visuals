"""Tests for data-source credits sidecars and optional on-screen attributions."""

from __future__ import annotations

from pathlib import Path

import pytest

from ride_visuals.cli import build_parser
from ride_visuals.credits import SOURCES, credits_path, on_screen_line, write_credits
from ride_visuals.maps.generator import MapGenerator
from ride_visuals.maps.tiles import basemap_sources


def test_write_credits_writes_sidecar_and_removes_stale_when_empty(tmp_path: Path) -> None:
    output = tmp_path / "videos" / "ride.mp4"
    sidecar = write_credits(output, ["openfreemap", "terrain-tiles", "openfreemap"])

    assert sidecar == credits_path(output)
    assert sidecar is not None and sidecar.exists()
    text = sidecar.read_text(encoding="utf-8")
    assert "Credits for ride.mp4" in text
    assert SOURCES["openfreemap"].name in text
    assert SOURCES["terrain-tiles"].name in text
    assert text.count(SOURCES["openfreemap"].name) == 1

    # Re-rendering without third-party map sources removes the stale sidecar.
    assert write_credits(output, []) is None
    assert not sidecar.exists()


def test_write_credits_rejects_unknown_source_key(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="Unknown data source"):
        write_credits(tmp_path / "map.png", ["not-a-source"])


def test_on_screen_line_deduplicates_attributions() -> None:
    line = on_screen_line(["esri-dark-gray", "esri-light-gray", "openstreetmap"])
    assert line.count("Esri, HERE, Garmin") == 1
    assert "© OpenStreetMap contributors" in line


def test_basemap_sources_for_plain_and_providers() -> None:
    assert basemap_sources("plain") == ()
    assert basemap_sources("satellite") == ("esri-world-imagery",)
    assert basemap_sources("dark") == ("esri-dark-gray",)


def test_cli_parses_credits_on_screen_flag_for_map_and_video() -> None:
    parser = build_parser()
    default_map = parser.parse_args(["map", "overview"])
    opt_in_map = parser.parse_args(["map", "overview", "--credits-on-screen"])
    opt_out_video = parser.parse_args(["video", "collection", "--no-credits-on-screen"])
    opt_in_video = parser.parse_args(["video", "flyover", "42", "--credits-on-screen"])

    assert default_map.credits_on_screen is False
    assert opt_in_map.credits_on_screen is True
    assert opt_out_video.credits_on_screen is False
    assert opt_in_video.credits_on_screen is True


def test_map_generator_omits_on_screen_attribution_by_default(
    reference_cli_workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PIL import Image

    monkeypatch.setattr(
        "ride_visuals.maps.tiles.TileManager.render_basemap_layer",
        lambda self, *args, **kwargs: Image.new("RGB", (64, 64), color="#10141c"),
    )

    drawn_texts: list[str] = []
    import matplotlib.figure

    orig_text = matplotlib.figure.Figure.text

    def spy_text(self, x, y, s, *args, **kwargs):
        drawn_texts.append(str(s))
        return orig_text(self, x, y, s, *args, **kwargs)

    monkeypatch.setattr(matplotlib.figure.Figure, "text", spy_text)

    gen_clean = MapGenerator(
        catalog_db_path=reference_cli_workspace.catalog_db,
        streams_dir=reference_cli_workspace.streams_dir,
        outputs_dir=reference_cli_workspace.outputs_dir / "maps",
        credits_on_screen=False,
    )
    gen_clean.render_overview(dpi=72, basemap="dark")
    assert not any("Esri" in t for t in drawn_texts)

    drawn_texts.clear()
    gen_credited = MapGenerator(
        catalog_db_path=reference_cli_workspace.catalog_db,
        streams_dir=reference_cli_workspace.streams_dir,
        outputs_dir=reference_cli_workspace.outputs_dir / "maps",
        credits_on_screen=True,
    )
    gen_credited.render_overview(dpi=72, basemap="dark")
    assert any("Esri" in t for t in drawn_texts)
