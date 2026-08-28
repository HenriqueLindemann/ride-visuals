import pytest

from ride_visuals.maps.projection import (
    compute_map_viewport,
    expand_viewport_to_canvas,
    project_mercator,
    unproject_mercator,
)
from ride_visuals.maps.generator import project_mercator as map_project_mercator
from ride_visuals.video.collection_data import project_mercator as video_project_mercator


@pytest.mark.parametrize(
    "lon,lat",
    [
        (20.0, 10.0),
        (-30.0, 15.0),
        (45.0, -20.0),
        (-51.2287, -30.0277),  # Porto Alegre, Brazil
        (7.7725, 49.4401),     # Kaiserslautern, Germany
    ],
)
def test_map_projection_round_trip_preserves_coordinates(lon, lat):
    x, y = project_mercator(lon, lat)
    actual_lon, actual_lat = unproject_mercator(x, y)
    assert actual_lon == pytest.approx(lon, abs=1e-8)
    assert actual_lat == pytest.approx(lat, abs=1e-8)


def test_collection_projection_uses_the_same_round_trip():
    x, y = video_project_mercator(20.0, 10.0)
    lon, lat = unproject_mercator(x, y)
    assert lon == pytest.approx(20.0, abs=1e-8)
    assert lat == pytest.approx(10.0, abs=1e-8)
    assert map_project_mercator is project_mercator
    assert video_project_mercator is project_mercator


def test_compute_map_viewport_tall_bounding_box():
    # Tall route: height = 1000m, width = 200m
    xs = [0.0, 200.0]
    ys = [0.0, 1000.0]
    # Square axes (width=1, height=1)
    x_min, x_max, y_min, y_max = compute_map_viewport(
        xs, ys, axes_width=1.0, axes_height=1.0, margin_pct=0.05
    )
    # Padded height is 1000 * 1.10 = 1100. Span Y should be 1100, Span X should be 1100
    assert y_max - y_min == pytest.approx(1100.0)
    assert x_max - x_min == pytest.approx(1100.0)
    assert (x_min + x_max) / 2.0 == pytest.approx(100.0)
    assert (y_min + y_max) / 2.0 == pytest.approx(500.0)


def test_compute_map_viewport_wide_bounding_box():
    # Wide route: width = 2000m, height = 500m
    xs = [-1000.0, 1000.0]
    ys = [100.0, 600.0]
    # 2:1 aspect ratio axes
    x_min, x_max, y_min, y_max = compute_map_viewport(
        xs, ys, axes_width=2.0, axes_height=1.0, margin_pct=0.10
    )
    # Padded width is 2000 * 1.20 = 2400. Span X should be 2400, Span Y should be 1200
    assert x_max - x_min == pytest.approx(2400.0)
    assert y_max - y_min == pytest.approx(1200.0)
    assert (x_min + x_max) / 2.0 == pytest.approx(0.0)
    assert (y_min + y_max) / 2.0 == pytest.approx(350.0)


def test_compute_map_viewport_handles_nan_and_errors():
    import numpy as np

    xs = [np.nan, 10.0, 20.0, np.nan]
    ys = [100.0, np.nan, 200.0, np.nan]
    # Only index 2 has both finite
    x_min, x_max, y_min, y_max = compute_map_viewport(
        xs, ys, axes_width=1.0, axes_height=1.0, margin_pct=0.0
    )
    assert (x_max - x_min) >= 100.0  # Minimum span guarantee

    with pytest.raises(ValueError, match="No valid coordinates"):
        compute_map_viewport([np.nan], [np.nan], axes_width=1.0, axes_height=1.0)

    with pytest.raises(ValueError, match="dimensions must be positive"):
        compute_map_viewport([0.0], [0.0], axes_width=0.0, axes_height=1.0)

    with pytest.raises(ValueError, match="margin cannot be negative"):
        compute_map_viewport([0.0], [0.0], axes_width=1.0, axes_height=1.0, margin_pct=-0.1)


def test_projection_preserves_missing_coordinates_as_missing():
    import math

    assert all(math.isnan(value) for value in project_mercator(float("nan"), 49.0))


def test_content_viewport_expands_to_full_bleed_without_moving_data():
    content = (0.1, 0.2, 0.8, 0.6)
    canvas = expand_viewport_to_canvas((10.0, 90.0, 20.0, 80.0), content_rect=content)

    assert canvas == pytest.approx((0.0, 100.0, 0.0, 100.0))

    with pytest.raises(ValueError, match="fit inside"):
        expand_viewport_to_canvas((0.0, 1.0, 0.0, 1.0), content_rect=(0.5, 0.0, 0.6, 1.0))
