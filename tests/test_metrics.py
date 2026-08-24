"""Testes unitários para derivação de métricas de telemetria."""

import unittest
from datetime import datetime, timezone, timedelta
from ride_visuals.ingest.metrics import haversine_distance, calculate_bearing, enrich_trackpoints
from ride_visuals.model.trackpoint import TrackPoint


class TestMetrics(unittest.TestCase):
    def test_haversine_and_bearing(self):
        # Synthetic southwest segment near the equator.
        lat1, lon1 = 0.0, 0.0
        lat2, lon2 = -0.7, -0.7

        dist = haversine_distance(lat1, lon1, lat2, lon2)
        self.assertGreater(dist, 100000)
        self.assertLess(dist, 120000)

        bearing = calculate_bearing(lat1, lon1, lat2, lon2)
        # Sudoeste ~ 210 a 240 graus
        self.assertGreater(bearing, 200)
        self.assertLess(bearing, 250)

    def test_enrich_trackpoints_derives_speed_and_distance(self):
        t0 = datetime(2024, 4, 2, 12, 0, 0, tzinfo=timezone.utc)
        pts = [
            TrackPoint(
                timestamp=t0,
                lat=10.0,
                lon=20.0,
                altitude=200.0,
            ),
            TrackPoint(
                timestamp=t0 + timedelta(seconds=10),
                lat=10.0005,
                lon=20.0, # deslocamento ~55m para o norte
                altitude=202.0,
            ),
        ]

        enriched = enrich_trackpoints(pts)
        self.assertEqual(len(enriched), 2)
        self.assertEqual(enriched[0].distance_m, 0.0)
        self.assertGreater(enriched[1].distance_m, 50.0)
        self.assertGreater(enriched[1].speed_mps, 4.0)
        self.assertEqual(enriched[1].provenance_speed, "derived")
        self.assertAlmostEqual(enriched[1].bearing_deg, 0.0, delta=2.0) # Norte


if __name__ == "__main__":
    unittest.main()
