import math
import numpy as np
import pytest

from ride_visuals.maps.projection import (
    compute_map_viewport,
    expand_viewport_to_canvas,
    project_mercator,
    unproject_mercator,
)


@pytest.mark.parametrize(
    "lon,lat",
    [
        (20.0, 10.0),
        (-51.2287, -30.0277),
        (7.7725, 49.4401),
    ],
)
def test_map_projection_round_trip_preserves_coordinates(lon, lat):
    x, y = project_mercator(lon, lat)
    actual_lon, actual_lat = unproject_mercator(x, y)
    assert actual_lon == pytest.approx(lon, abs=1e-8)
    assert actual_lat == pytest.approx(lat, abs=1e-8)


def test_compute_map_viewport_fits_aspect_ratio_and_margins():
    x_min, x_max, y_min, y_max = compute_map_viewport(
        [0.0, 200.0], [0.0, 1000.0], axes_width=1.0, axes_height=1.0, margin_pct=0.05
    )
    assert y_max - y_min == pytest.approx(1100.0)
    assert x_max - x_min == pytest.approx(1100.0)
    assert (x_min + x_max) / 2.0 == pytest.approx(100.0)
    assert (y_min + y_max) / 2.0 == pytest.approx(500.0)


def test_compute_map_viewport_handles_nan_and_errors():
    xs = [np.nan, 10.0, 20.0, np.nan]
    ys = [100.0, np.nan, 200.0, np.nan]
    x_min, x_max, _, _ = compute_map_viewport(
        xs, ys, axes_width=1.0, axes_height=1.0, margin_pct=0.0
    )
    assert (x_max - x_min) >= 100.0

    with pytest.raises(ValueError, match="No valid coordinates"):
        compute_map_viewport([np.nan], [np.nan], axes_width=1.0, axes_height=1.0)


def test_projection_preserves_missing_coordinates_as_missing():
    assert all(math.isnan(value) for value in project_mercator(float("nan"), 49.0))


def test_content_viewport_expands_to_full_bleed_without_moving_data():
    content = (0.1, 0.2, 0.8, 0.6)
    canvas = expand_viewport_to_canvas((10.0, 90.0, 20.0, 80.0), content_rect=content)
    assert canvas == pytest.approx((0.0, 100.0, 0.0, 100.0))
