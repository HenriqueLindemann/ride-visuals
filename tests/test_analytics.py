"""Testes unitários para cálculos de analytics esportivo."""

import unittest
import numpy as np
import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ride_visuals.analytics.zones import HRZoneProfile
from ride_visuals.analytics.trimp import TRIMPAnalyzer
from ride_visuals.analytics.drift import DriftAnalyzer
from ride_visuals.analytics.climbs import ClimbAnalyzer


class TestAnalytics(unittest.TestCase):
    def test_hr_zones_distribution(self):
        profile = HRZoneProfile(resting_hr=50, max_hr=190)
        # 100 segundos em Z2 (140 bpm) e 100 segundos em Z4 (170 bpm)
        hrs = np.array([140.0] * 100 + [170.0] * 100)
        dist = profile.calculate_time_in_zones(hrs, dt_seconds=1.0)

        self.assertEqual(dist["z2_aerobic_s"], 100.0)
        self.assertEqual(dist["z4_threshold_s"], 100.0)
        self.assertEqual(dist["z1_recovery_s"], 0.0)
        self.assertAlmostEqual(dist["z2_pct"], 50.0)
        self.assertAlmostEqual(dist["z4_pct"], 50.0)

    def test_hr_zones_use_real_sample_durations(self):
        profile = HRZoneProfile()
        hrs = np.array([140.0, 170.0])
        durations = np.array([9.0, 1.0])

        dist = profile.calculate_time_in_zones(hrs, dt_seconds=durations)

        self.assertAlmostEqual(dist["z2_pct"], 90.0)
        self.assertAlmostEqual(dist["z4_pct"], 10.0)

    def test_trimp_calculation(self):
        analyzer = TRIMPAnalyzer(resting_hr=50, max_hr=190, gender="male")
        # 60 minutos em 150 bpm (delta_hr = (150-50)/(190-50) = 100/140 = 0.714)
        hrs = np.array([150.0] * 60)
        trimp = analyzer.calculate_activity_trimp(hrs, duration_min=60.0)

        self.assertGreater(trimp, 50.0)
        self.assertLess(trimp, 180.0)

    def test_aerobic_drift(self):
        # 1a metade: 8 m/s a 140 bpm (eff = 8/140 = 0.0571)
        # 2a metade: 7 m/s a 145 bpm (eff = 7/145 = 0.0482) -> drift positivo
        speed = np.array([8.0] * 500 + [7.0] * 500)
        hr = np.array([140.0] * 500 + [145.0] * 500)

        res = DriftAnalyzer.calculate_aerobic_drift(speed, hr, min_points=500)
        self.assertTrue(res["valid"])
        self.assertGreater(res["drift_pct"], 5.0)  # Houve desacoplamento

    def test_climb_vam(self):
        # Subida de 100m em 600s (10 min) -> VAM = (100 / 600) * 3600 = 600 m/h
        alts = np.linspace(200, 300, 60)
        times = np.linspace(0, 600, 60)

        climbs = ClimbAnalyzer.calculate_climb_vam(alts, times, min_gain_m=50.0)
        self.assertEqual(len(climbs), 1)
        self.assertAlmostEqual(climbs[0]["vam_mh"], 600.0, delta=15.0)

if __name__ == "__main__":
    unittest.main()


def test_empty_sensor_streams_are_reported_as_unavailable(tmp_path):
    from ride_visuals.analytics.progress import SeasonAnalytics

    database = tmp_path / "activities.duckdb"
    streams = tmp_path / "streams"
    streams.mkdir()
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            CREATE TABLE activities AS SELECT
                1::BIGINT AS id, 'Sensorless ride'::VARCHAR AS name,
                TIMESTAMPTZ '2024-05-01 08:00:00+00' AS start_date,
                'Ride'::VARCHAR AS activity_type, 10000.0::DOUBLE AS distance_m,
                100.0::DOUBLE AS elevation_gain_m, 1800::BIGINT AS moving_time_s,
                1900::BIGINT AS elapsed_time_s, 5.0::DOUBLE AS avg_speed_mps,
                NULL::DOUBLE AS max_speed_mps, NULL::DOUBLE AS avg_heart_rate,
                NULL::DOUBLE AS max_heart_rate, NULL::DOUBLE AS relative_effort,
                NULL::DOUBLE AS estimated_watts_avg, NULL::DOUBLE AS estimated_watts_max,
                NULL::DOUBLE AS temperature_avg, NULL::DOUBLE AS temperature_max,
                NULL::VARCHAR AS gear, ''::VARCHAR AS source_filename,
                'gpx'::VARCHAR AS source_format, ''::VARCHAR AS file_sha256,
                3::BIGINT AS point_count, false AS has_hr_stream,
                false AS has_speed_stream, false AS has_temp_stream,
                false AS has_watts_stream
            """
        )
    stream = pd.DataFrame({
        "timestamp": pd.date_range("2024-05-01T08:00:00Z", periods=3, freq="1s"),
        "heart_rate_bpm": [np.nan, np.nan, np.nan],
        "speed_mps": [np.nan, np.nan, np.nan],
        "temperature_c": [np.nan, np.nan, np.nan],
        "altitude": [100.0, 101.0, 102.0],
        "quality_flags": ["ok", "ok", "ok"],
    })
    pq.write_table(pa.Table.from_pandas(stream), streams / "1.parquet")

    result = SeasonAnalytics(database, streams).extract()

    assert result["sample_counts"]["temperature"] == 0
    assert result["temperature_stats"] == {
        "p10": None, "p90": None, "min": None, "max": None,
    }
    assert result["records"]["highest_effort"] is None
    assert result["records"]["peak_hr"] is None
    assert result["zones_pct"] == {f"Z{index}": 0.0 for index in range(1, 6)}
