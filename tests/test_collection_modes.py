import numpy as np
import pytest
from PIL import Image, ImageColor, ImageDraw

from ride_visuals.design import get_theme
from ride_visuals.maps.tiles import TILE_PROVIDERS, TileManager
from ride_visuals.video.collection import (
    CollectionVideoRenderer,
    elapsed_point_count,
    route_metric_color,
)


def test_elapsed_cursor_aligns_each_route_to_its_own_start():
    elapsed = np.array([0.0, 1.0, 2.0, 8.0, 9.0])
    assert elapsed_point_count(elapsed, -0.1) == 0
    assert elapsed_point_count(elapsed, 0.0) == 1
    assert elapsed_point_count(elapsed, 4.0) == 3
    assert elapsed_point_count(elapsed, 9.0) == 5


@pytest.mark.parametrize(
    "style,value,expected",
    [
        ("temperature", 14.9, "#56758A"),
        ("temperature", 15.0, "#78989A"),
        ("speed", 35.0, "#FF4D00"),
        ("grade", -6.0, "#647785"),
        ("grade", 6.0, "#FF4D00"),
    ],
)
def test_data_styles_use_fixed_explainable_intervals(style, value, expected):
    assert route_metric_color(style, value) == expected


def test_missing_sensor_sample_has_no_semantic_color():
    assert route_metric_color("temperature", np.nan) is None


def test_completed_route_without_sensor_data_is_drawn_in_neutral_color():
    renderer = CollectionVideoRenderer.__new__(CollectionVideoRenderer)
    renderer.theme = get_theme("midnight")
    image = Image.new("RGB", (30, 20), renderer.theme.canvas)
    track = {
        "pixel_points": [(5, 10), (15, 10), (25, 10)],
        "point_hrs": [np.nan, np.nan, np.nan],
    }

    renderer._draw_route(
        ImageDraw.Draw(image), track, "heart_rate", 3,
        width=3, halo_width=1,
    )

    assert image.getpixel((15, 10)) == ImageColor.getrgb(renderer.theme.data_missing)


def test_route_with_sensor_data_remains_continuous_across_sample_gaps():
    renderer = CollectionVideoRenderer.__new__(CollectionVideoRenderer)
    renderer.theme = get_theme("midnight")
    image = Image.new("RGB", (30, 20), renderer.theme.canvas)
    track = {
        "pixel_points": [(5, 10), (15, 10), (25, 10)],
        "point_hrs": [140.0, np.nan, 140.0],
    }

    renderer._draw_route(
        ImageDraw.Draw(image), track, "heart_rate", 3,
        width=3, halo_width=1,
    )

    assert image.getpixel((15, 10)) == ImageColor.getrgb("#AFC1AE")


def test_high_detail_requests_exactly_one_additional_tile_zoom():
    args = (20.0, 10.0, 21.0, 11.0, 1920, 1080)
    standard = TileManager.optimal_zoom(*args, detail_scale=1)
    high = TileManager.optimal_zoom(*args, detail_scale=2)
    assert high == standard + 1


def test_dark_tiles_accept_carto_key_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CARTO_API_KEY", "key/with spaces")
    manager = TileManager(tmp_path / "tiles")

    assert manager._tile_url("dark", 8, 10, 20).endswith(
        "/8/10/20.png?key=key%2Fwith%20spaces"
    )


def test_map_detail_rejects_unbounded_oversampling():
    with pytest.raises(ValueError, match="detail scale"):
        TileManager.optimal_zoom(20.0, 10.0, 21.0, 11.0, 1920, 1080, detail_scale=4)


def test_high_detail_falls_back_atomically_when_extra_zoom_is_unavailable(tmp_path):
    manager = TileManager(tmp_path / "tiles")
    bounds = (20.0, 10.0, 21.0, 11.0)
    standard_zoom = manager.optimal_zoom(*bounds, 320, 180, detail_scale=1)
    requested_zooms = []

    def fake_fetch(provider, zoom, x, y):
        requested_zooms.append(zoom)
        if zoom == standard_zoom:
            return Image.new("RGB", (256, 256), "#405060")
        return None

    manager.fetch_tile = fake_fetch  # type: ignore[method-assign]
    image = manager.render_basemap_layer(
        *bounds, 320, 180, provider="satellite", dim_pct=0.0, detail_scale=2
    )
    assert standard_zoom + 1 in requested_zooms
    assert standard_zoom in requested_zooms
    assert image.getpixel((160, 90)) == (64, 80, 96)


def test_every_external_tile_provider_has_visible_credit_text():
    assert set(TILE_PROVIDERS) == {"satellite", "topo", "osm", "dark"}
    assert all(provider["attribution"].strip() for provider in TILE_PROVIDERS.values())
    assert "OpenStreetMap contributors" in TILE_PROVIDERS["topo"]["attribution"]
    assert "OpenTopoMap" in TILE_PROVIDERS["topo"]["attribution"]
