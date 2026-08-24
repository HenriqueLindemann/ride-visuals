import math

from PIL import Image

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
    assert kwargs == {"provider": "topo", "dim_pct": 0.0, "detail_scale": 2}


def test_full_canvas_basemap_keeps_route_aligned_in_telemetry_panel():
    points = [
        {"lon": 7.0, "lat": 49.0},
        {"lon": 7.6, "lat": 49.1},
        {"lon": 8.2, "lat": 49.4},
    ]
    width, height = 1920, 1080
    bounds = canvas_basemap_bounds(points, width=width, height=height, layout="telemetry")
    canvas_min_x, canvas_min_y = _mercator(bounds[0], bounds[1])
    canvas_max_x, canvas_max_y = _mercator(bounds[2], bounds[3])
    route_view_bounds = route_basemap_bounds(points)
    route_min_x, route_min_y = _mercator(route_view_bounds[0], route_view_bounds[1])
    route_max_x, route_max_y = _mercator(route_view_bounds[2], route_view_bounds[3])

    side = 972.0
    square_x, square_y = 186.0, 54.0
    for point in points:
        x, y = _mercator(point["lon"], point["lat"])
        background_x = (x - canvas_min_x) / (canvas_max_x - canvas_min_x) * width
        background_y = height - (y - canvas_min_y) / (canvas_max_y - canvas_min_y) * height
        route_x = square_x + (x - route_min_x) / (route_max_x - route_min_x) * side
        route_y = square_y + (route_max_y - y) / (route_max_y - route_min_y) * side
        assert abs(background_x - route_x) < 1e-6
        assert abs(background_y - route_y) < 1e-6
