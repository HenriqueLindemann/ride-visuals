"""Testes unitários para ingestão de arquivos FIT."""

import unittest
from ride_visuals.ingest.fit_reader import _semicircles_to_degrees


class TestFITIngest(unittest.TestCase):
    def test_semicircle_conversion(self):
        # 2^31 is 180 degrees
        val = 2147483648 / 2  # 90 degrees
        deg = _semicircles_to_degrees(val)
        self.assertAlmostEqual(deg, 90.0, places=4)

        # Already in degrees
        self.assertEqual(_semicircles_to_degrees(10.0), 10.0)

if __name__ == "__main__":
    unittest.main()
