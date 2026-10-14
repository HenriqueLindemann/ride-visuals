from datetime import datetime
from pathlib import Path
import duckdb
import pytest

from ride_visuals.ingest.pipeline import (
    ACTIVITIES_TABLE_SCHEMA_SQL,
    IngestPipeline,
)
from ride_visuals.model.activity import ActivitySummary


def _make_activity(act_id: int, name: str, start_iso: str = "2024-05-01T10:00:00Z") -> ActivitySummary:
    return ActivitySummary(
        id=act_id,
        name=name,
        start_date=datetime.fromisoformat(start_iso.replace("Z", "+00:00")),
        activity_type="Ride",
        distance_m=25000.0,
        elevation_gain_m=350.0,
        moving_time_s=3600,
        elapsed_time_s=3800,
        avg_speed_mps=6.94,
        max_speed_mps=12.5,
        avg_heart_rate=140.0,
        max_heart_rate=165.0,
        point_count=100,
        source_filename=f"{act_id}.fit",
        source_format="fit",
        file_sha256="dummy_hash",
        has_hr_stream=True,
    )


def test_write_catalog_upserts_and_preserves_existing_activities(tmp_path: Path):
    db_path = tmp_path / "catalog.duckdb"
    pipeline = IngestPipeline(
        bulk_dir=tmp_path,
        catalog_db_path=db_path,
        streams_dir=tmp_path / "streams",
    )

    pipeline._write_catalog_duckdb([
        _make_activity(1, "Ride 1", "2024-01-01T10:00:00Z"),
        _make_activity(2, "Ride 2", "2024-01-02T10:00:00Z"),
    ])
    pipeline._write_catalog_duckdb([
        _make_activity(2, "Ride 2 Updated", "2024-01-02T10:00:00Z"),
        _make_activity(3, "Ride 3", "2024-02-01T10:00:00Z"),
    ])

    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute("SELECT id, name FROM activities ORDER BY id").fetchall()
    con.close()

    assert rows == [
        (1, "Ride 1"),
        (2, "Ride 2 Updated"),
        (3, "Ride 3"),
    ]


def test_write_catalog_upserts_into_legacy_table_without_primary_key(tmp_path: Path):
    db_path = tmp_path / "catalog.duckdb"
    pipeline = IngestPipeline(
        bulk_dir=tmp_path,
        catalog_db_path=db_path,
        streams_dir=tmp_path / "streams",
    )

    con = duckdb.connect(str(db_path))
    con.execute(ACTIVITIES_TABLE_SCHEMA_SQL.replace("id BIGINT PRIMARY KEY", "id BIGINT"))
    con.execute("INSERT INTO activities (id, name) VALUES (1, 'Legacy Ride')")
    con.close()

    pipeline._write_catalog_duckdb([
        _make_activity(1, "Legacy Ride Updated", "2024-01-01T10:00:00Z"),
        _make_activity(2, "New Ride", "2024-01-02T10:00:00Z"),
    ])

    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute("SELECT id, name FROM activities ORDER BY id").fetchall()
    con.close()

    assert rows == [(1, "Legacy Ride Updated"), (2, "New Ride")]


def test_clean_mode_preserves_existing_data_when_source_is_missing(tmp_path: Path):
    db_path = tmp_path / "catalog.duckdb"
    streams_dir = tmp_path / "streams"
    streams_dir.mkdir(parents=True)
    existing_stream = streams_dir / "99.parquet"
    existing_stream.write_bytes(b"existing")

    initial = IngestPipeline(
        bulk_dir=tmp_path,
        catalog_db_path=db_path,
        streams_dir=streams_dir,
    )
    initial._write_catalog_duckdb([_make_activity(99, "Existing Ride")])

    cleaner = IngestPipeline(
        bulk_dir=tmp_path / "missing-export",
        catalog_db_path=db_path,
        streams_dir=streams_dir,
        clean=True,
    )
    with pytest.raises(FileNotFoundError):
        cleaner.run_ingest()

    assert existing_stream.read_bytes() == b"existing"
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute("SELECT id, name FROM activities").fetchall()
    con.close()
    assert rows == [(99, "Existing Ride")]


def test_ingest_directory_without_strava_csv(tmp_path: Path):
    rides_dir = tmp_path / "rides"
    rides_dir.mkdir()
    (rides_dir / "Morning_Loop.gpx").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Morning Loop</name><trkseg>
    <trkpt lat="49.4300" lon="7.7500"><ele>250.0</ele><time>2026-05-01T08:00:00Z</time></trkpt>
    <trkpt lat="49.4350" lon="7.7550"><ele>265.0</ele><time>2026-05-01T08:01:00Z</time></trkpt>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )

    db_path = tmp_path / "catalog.duckdb"
    streams_dir = tmp_path / "streams"
    pipeline = IngestPipeline(
        bulk_dir=rides_dir,
        catalog_db_path=db_path,
        streams_dir=streams_dir,
    )
    stats = pipeline.run_ingest()

    assert stats["ingested_activities"] == 1
    assert stats["gpx_count"] == 1
    con = duckdb.connect(str(db_path), read_only=True)
    row = con.execute(
        "SELECT name, activity_type, elevation_gain_m, point_count FROM activities"
    ).fetchone()
    con.close()
    assert row == ("Morning Loop", "Ride", 15.0, 2)
