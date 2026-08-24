"""Testes unitários para cálculos de analytics esportivo."""

import unittest
import numpy as np

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
