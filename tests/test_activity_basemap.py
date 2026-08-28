import math

from PIL import Image
import pytest

from ride_visuals.video.activity_basemap import (
    canvas_basemap_bounds,
    render_activity_basemap,
    route_basemap_bounds,
)


def _mercator(lon: float, lat: float) -> tuple[float, float]:
    return math.radians(lon), math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def test_activity_basemap_bounds_match_route_map_viewbox():
    points = [
        {"lon": 7.0, "lat": 49.0},
        {"lon": 7.6, "lat": 49.1},
        {"lon": 8.2, "lat": 49.4},
    ]

    min_lon, min_lat, max_lon, max_lat = route_basemap_bounds(points)
    view_min_x, view_min_y = _mercator(min_lon, min_lat)
    view_max_x, view_max_y = _mercator(max_lon, max_lat)
    route_xy = [_mercator(point["lon"], point["lat"]) for point in points]
    route_px = [
        (
            (x - view_min_x) / (view_max_x - view_min_x) * 1000,
            1000 - (y - view_min_y) / (view_max_y - view_min_y) * 1000,
        )
        for x, y in route_xy
    ]

    assert all(60 - 1e-6 <= x <= 940 + 1e-6 and 60 - 1e-6 <= y <= 940 + 1e-6 for x, y in route_px)
    assert any(abs(value - edge) < 1e-6 for x, y in route_px for value in (x, y) for edge in (60, 940))


def test_activity_basemap_uses_requested_provider_and_detail(tmp_path):
    class FakeTileManager:
        call = None

        def render_basemap_layer(self, *args, **kwargs):
            self.call = (args, kwargs)
            return Image.new("RGB", (args[4], args[5]), "#405060")

    manager = FakeTileManager()
    output = render_activity_basemap(
        [{"lon": 7.0, "lat": 49.0}, {"lon": 8.0, "lat": 50.0}],
        tmp_path / "activity-topo.png",
        provider="topo",
        width=1280,
        height=720,
        layout="telemetry",
        map_detail="high",
        tile_manager=manager,  # type: ignore[arg-type]
    )

    assert output.is_file()
    assert Image.open(output).size == (1280, 720)
    assert manager.call is not None
    args, kwargs = manager.call
    assert args[4:] == (1280, 720)
    assert kwargs["provider"] == "topo"
    assert kwargs["detail_scale"] == 2


@pytest.mark.parametrize(
    ("width", "height", "view_w", "view_h", "padding"),
    [
        (1920, 1080, 1344, 1080, 64),
        (1080, 1920, 1080, 960, 56),
    ],
)
def test_full_canvas_basemap_keeps_route_aligned_in_telemetry_panel(
    width, height, view_w, view_h, padding
):
    points = [
        {"lon": 7.0, "lat": 49.0},
        {"lon": 7.6, "lat": 49.1},
        {"lon": 8.2, "lat": 49.4},
    ]
    bounds = canvas_basemap_bounds(points, width=width, height=height, layout="telemetry")
    canvas_min_x, canvas_min_y = _mercator(bounds[0], bounds[1])
    canvas_max_x, canvas_max_y = _mercator(bounds[2], bounds[3])

    projected = [_mercator(p["lon"], p["lat"]) for p in points]
    xs = [x for x, _ in projected]
    ys = [y for _, y in projected]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    data_w = max_x - min_x
    data_h = max_y - min_y

    top_pad = bottom_pad = side_pad = padding
    usable_w = view_w - 2 * side_pad
    usable_h = view_h - top_pad - bottom_pad
    scale = min(usable_w / data_w, usable_h / data_h)
    offset_x = side_pad + (usable_w - data_w * scale) / 2.0
    offset_y = top_pad + (usable_h - data_h * scale) / 2.0

    for point in points:
        x, y = _mercator(point["lon"], point["lat"])
        background_x = (x - canvas_min_x) / (canvas_max_x - canvas_min_x) * width
        background_y = (canvas_max_y - y) / (canvas_max_y - canvas_min_y) * height
        route_x = offset_x + (x - min_x) * scale
        route_y = offset_y + (max_y - y) * scale
        assert abs(background_x - route_x) < 1e-6
        assert abs(background_y - route_y) < 1e-6


def test_clean_basemap_accounts_for_optional_progress_bar():
    points = [{"lon": 7.0, "lat": 49.0}, {"lon": 8.0, "lat": 50.0}]
    without_bar = canvas_basemap_bounds(
        points, width=1920, height=1080, layout="clean", show_progress_bar=False
    )
    with_bar = canvas_basemap_bounds(
        points, width=1920, height=1080, layout="clean", show_progress_bar=True
    )

    assert with_bar != without_bar
