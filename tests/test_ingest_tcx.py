"""Testes unitários para ingestão de arquivos TCX."""

import gzip
import tempfile
import unittest
from pathlib import Path
import numpy as np

from ride_visuals.ingest.tcx_reader import TCXReader


TCX_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Biking">
      <Id>2024-04-02T18:13:49.000Z</Id>
      <Lap StartTime="2024-04-02T18:13:49.000Z">
        <TotalTimeSeconds>120.0</TotalTimeSeconds>
        <DistanceMeters>500.0</DistanceMeters>
        <Track>
          <Trackpoint>
            <Time>2024-04-02T18:13:49.000Z</Time>
            <Position>
              <LatitudeDegrees>10.0000000</LatitudeDegrees>
              <LongitudeDegrees>20.0000000</LongitudeDegrees>
            </Position>
            <AltitudeMeters>230.0</AltitudeMeters>
            <DistanceMeters>0.0</DistanceMeters>
            <HeartRateBpm><Value>135</Value></HeartRateBpm>
            <Extensions>
              <TPX xmlns="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
                <Speed>5.2</Speed>
                <Watts>160</Watts>
              </TPX>
            </Extensions>
          </Trackpoint>
          <Trackpoint>
            <Time>2024-04-02T18:13:59.000Z</Time>
            <Position>
              <LatitudeDegrees>10.0005000</LatitudeDegrees>
              <LongitudeDegrees>20.0005000</LongitudeDegrees>
            </Position>
            <AltitudeMeters>231.5</AltitudeMeters>
            <DistanceMeters>55.0</DistanceMeters>
            <HeartRateBpm><Value>142</Value></HeartRateBpm>
            <Extensions>
              <TPX xmlns="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
                <Speed>5.8</Speed>
                <Watts>185</Watts>
              </TPX>
            </Extensions>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
"""


class TestTCXIngest(unittest.TestCase):
    def test_tcx_reading_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.tcx.gz"
            with gzip.open(file_path, "wt", encoding="utf-8") as f:
                f.write(TCX_SAMPLE)

            points, meta = TCXReader.read_tcx(file_path)

            self.assertEqual(len(points), 2)
            self.assertTrue(meta["has_hr"])
            self.assertTrue(meta["has_speed"])
            self.assertTrue(meta["has_power"])

            # Test point 0
            p0 = points[0]
            self.assertAlmostEqual(p0.lat, 10.0000000)
            self.assertAlmostEqual(p0.lon, 20.0000000)
            self.assertEqual(p0.altitude, 230.0)
            self.assertEqual(p0.heart_rate_bpm, 135)
            self.assertEqual(p0.speed_mps, 5.2)
            self.assertEqual(p0.provenance_speed, "measured")
            self.assertEqual(p0.power_watts, 160)
            self.assertEqual(p0.provenance_power, "provider_estimated")

            # Test point 1
            p1 = points[1]
            self.assertEqual(p1.heart_rate_bpm, 142)
            self.assertEqual(p1.speed_mps, 5.8)
            self.assertEqual(p1.power_watts, 185)


if __name__ == "__main__":
    unittest.main()
