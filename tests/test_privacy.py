import pandas as pd
import pytest

from ride_visuals.privacy import load_privacy_zones


def test_neutral_privacy_zone_csv(tmp_path):
    path = tmp_path / "privacy.csv"
    pd.DataFrame([
        {"latitude": 10.0, "longitude": 20.0, "radius_km": 0.35},
    ]).to_csv(path, index=False)

    assert load_privacy_zones(path) == [
        {"lat": 10.0, "lon": 20.0, "radius_m": 350.0},
    ]


def test_configured_privacy_zone_file_fails_closed_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="Privacy-zone file not found"):
        load_privacy_zones(tmp_path / "missing.csv")
