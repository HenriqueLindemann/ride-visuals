import pytest

from ride_visuals.maps.generator import project_mercator, unproject_mercator
from ride_visuals.video.collection import (
    project_mercator as video_project_mercator,
    unproject_mercator as video_unproject_mercator,
)


@pytest.mark.parametrize("lon,lat", [(20.0, 10.0), (-30.0, 15.0), (45.0, -20.0)])
def test_map_projection_round_trip_preserves_coordinates(lon, lat):
    x, y = project_mercator(lon, lat)
    actual_lon, actual_lat = unproject_mercator(x, y)
    assert actual_lon == pytest.approx(lon, abs=1e-8)
    assert actual_lat == pytest.approx(lat, abs=1e-8)


def test_collection_projection_uses_the_same_round_trip():
    x, y = video_project_mercator(20.0, 10.0)
    lon, lat = video_unproject_mercator(x, y)
    assert lon == pytest.approx(20.0, abs=1e-8)
    assert lat == pytest.approx(10.0, abs=1e-8)
