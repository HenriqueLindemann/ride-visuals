import math

from ride_visuals.video.activity_basemap import (
    canvas_basemap_bounds,
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


def test_clean_basemap_accounts_for_optional_progress_bar():
    points = [{"lon": 7.0, "lat": 49.0}, {"lon": 8.0, "lat": 50.0}]
    without_bar = canvas_basemap_bounds(
        points, width=1920, height=1080, layout="clean", show_progress_bar=False
    )
    with_bar = canvas_basemap_bounds(
        points, width=1920, height=1080, layout="clean", show_progress_bar=True
    )

    assert with_bar != without_bar
