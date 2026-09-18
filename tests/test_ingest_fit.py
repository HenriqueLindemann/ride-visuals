"""Testes unitários para ingestão de arquivos FIT."""

import gzip
import unittest
from pathlib import Path

from ride_visuals.ingest.fit_reader import (
    _positions_are_semicircles,
    _semicircles_to_degrees,
)


class TestFITIngest(unittest.TestCase):
    def test_semicircle_conversion(self):
        # 2^31 is 180 degrees
        val = 2147483648 / 2  # 90 degrees
        deg = _semicircles_to_degrees(val)
        self.assertAlmostEqual(deg, 90.0, places=4)

        # Already in degrees
        self.assertEqual(_semicircles_to_degrees(10.0), 10.0)

    def test_explicit_encoding_decodes_near_zero_semicircles(self):
        # A ride crossing the equator stores tiny semicircle values that the
        # context-free heuristic would mistake for degrees.
        self.assertAlmostEqual(
            _semicircles_to_degrees(10.0, semicircles=True),
            10.0 * 180.0 / (2**31),
            places=12,
        )
        self.assertEqual(_semicircles_to_degrees(10.0, semicircles=False), 10.0)
        self.assertIsNone(_semicircles_to_degrees(None, semicircles=True))


def test_reference_fit_is_decided_as_semicircles(reference_activity_dir: Path) -> None:
    raw = gzip.decompress((reference_activity_dir / "activity.fit.gz").read_bytes())

    assert _positions_are_semicircles(raw) is True


if __name__ == "__main__":
    unittest.main()
