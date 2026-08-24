"""GPX ingestion tests."""

from pathlib import Path

from ride_visuals.ingest.gpx_reader import GPXReader


def test_gpx_reader_preserves_trackpoint_extensions(tmp_path: Path) -> None:
    gpx_path = tmp_path / "activity.gpx"
    gpx_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1"
     creator="Ride Visuals test"
     xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
  <trk><name>Synthetic activity</name><trkseg>
    <trkpt lat="10.0000" lon="20.0000">
      <ele>100.0</ele><time>2024-01-01T12:00:00Z</time>
      <extensions><gpxtpx:TrackPointExtension>
        <gpxtpx:atemp>21.0</gpxtpx:atemp>
        <gpxtpx:hr>140</gpxtpx:hr>
        <gpxtpx:cad>82</gpxtpx:cad>
        <gpxtpx:speed>4.5</gpxtpx:speed>
        <gpxtpx:power>175</gpxtpx:power>
      </gpxtpx:TrackPointExtension></extensions>
    </trkpt>
    <trkpt lat="10.0005" lon="20.0005">
      <ele>102.0</ele><time>2024-01-01T12:00:10Z</time>
    </trkpt>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )

    points, metadata = GPXReader.read_gpx(gpx_path)

    assert len(points) == 2
    assert metadata == {
        "has_hr": True,
        "has_speed": True,
        "has_temp": True,
        "has_power": True,
        "has_cadence": True,
    }
    first = points[0]
    assert first.lat == 10.0
    assert first.lon == 20.0
    assert first.altitude == 100.0
    assert first.heart_rate_bpm == 140.0
    assert first.speed_mps == 4.5
    assert first.temperature_c == 21.0
    assert first.cadence_rpm == 82.0
    assert first.power_watts == 175.0
