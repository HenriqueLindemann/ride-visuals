from datetime import datetime
from pathlib import Path
import duckdb
import pytest

from ride_visuals.ingest.pipeline import (
    ACTIVITIES_TABLE_SCHEMA_SQL,
    IngestPipeline,
)
from ride_visuals.model.activity import ActivitySummary
from ride_visuals.video.engines.remotion import RemotionVideoEngine, _resolve_renderer_dir


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


def test_write_catalog_creates_schema_for_empty_activities(tmp_path: Path):
    db_path = tmp_path / "catalog.duckdb"
    streams_dir = tmp_path / "streams"
    pipeline = IngestPipeline(
        bulk_dir=tmp_path,
        catalog_db_path=db_path,
        streams_dir=streams_dir,
    )

    # Calling with empty activities should ensure table exists with schema
    pipeline._write_catalog_duckdb([])

    con = duckdb.connect(str(db_path), read_only=True)
    count = con.execute("SELECT count(*) FROM activities").fetchone()[0]
    columns = [col[0] for col in con.execute("DESCRIBE activities").fetchall()]
    con.close()

    assert count == 0
    assert "id" in columns
    assert "start_date" in columns
    assert "distance_m" in columns


def test_write_catalog_upserts_and_preserves_existing_activities(tmp_path: Path):
    db_path = tmp_path / "catalog.duckdb"
    streams_dir = tmp_path / "streams"
    pipeline = IngestPipeline(
        bulk_dir=tmp_path,
        catalog_db_path=db_path,
        streams_dir=streams_dir,
    )

    # Initial ingest: ride 1 and ride 2
    pipeline._write_catalog_duckdb([
        _make_activity(1, "Ride 1", "2024-01-01T10:00:00Z"),
        _make_activity(2, "Ride 2", "2024-01-02T10:00:00Z"),
    ])

    # Second scoped ingest: ride 2 (updated) and ride 3
    pipeline._write_catalog_duckdb([
        _make_activity(2, "Ride 2 Updated", "2024-01-02T10:00:00Z"),
        _make_activity(3, "Ride 3", "2024-02-01T10:00:00Z"),
    ])

    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute("SELECT id, name FROM activities ORDER BY id").fetchall()
    con.close()

    # Ride 1 must still exist, Ride 2 must be updated, Ride 3 must be added
    assert len(rows) == 3
    assert rows == [
        (1, "Ride 1"),
        (2, "Ride 2 Updated"),
        (3, "Ride 3"),
    ]


def test_write_catalog_upserts_into_legacy_table_without_primary_key(tmp_path: Path):
    """Catálogos criados por versões antigas não têm PRIMARY KEY em activities."""
    db_path = tmp_path / "catalog.duckdb"
    streams_dir = tmp_path / "streams"
    pipeline = IngestPipeline(
        bulk_dir=tmp_path,
        catalog_db_path=db_path,
        streams_dir=streams_dir,
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


def test_clean_mode_removes_old_streams_and_resets_catalog(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "catalog.duckdb"
    streams_dir = tmp_path / "streams"
    streams_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy stream and catalog
    dummy_stream = streams_dir / "old_act.parquet"
    dummy_stream.write_bytes(b"dummy")

    pipeline_init = IngestPipeline(
        bulk_dir=tmp_path,
        catalog_db_path=db_path,
        streams_dir=streams_dir,
    )
    pipeline_init._write_catalog_duckdb([_make_activity(99, "Old Ride")])

    export_root = tmp_path / "export"
    activities_dir = export_root / "activities"
    activities_dir.mkdir(parents=True)
    csv_path = export_root / "activities.csv"
    csv_path.write_text("Activity ID,Activity Name\n", encoding="utf-8")

    class EmptyCSVActivityReader:
        def __init__(self, _path: Path):
            pass

        def read_activities(self):
            return []

    monkeypatch.setattr("ride_visuals.ingest.pipeline.CSVActivityReader", EmptyCSVActivityReader)

    # Exercise the real clean path rather than repeating its implementation in
    # the test. The empty source leaves a valid, empty replacement catalog.
    pipeline_clean = IngestPipeline(
        bulk_dir=export_root,
        catalog_db_path=db_path,
        streams_dir=streams_dir,
        clean=True,
    )
    stats = pipeline_clean.run_ingest()

    assert not dummy_stream.exists()
    con = duckdb.connect(str(db_path), read_only=True)
    count = con.execute("SELECT count(*) FROM activities").fetchone()[0]
    con.close()
    assert count == 0
    assert stats["ingested_activities"] == 0


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


def test_renderer_dir_resolution(tmp_path: Path, monkeypatch):
    # Explicit directory
    custom_dir = tmp_path / "custom_renderer"
    assert _resolve_renderer_dir(custom_dir) == custom_dir

    # Environment variable override
    env_dir = tmp_path / "env_renderer"
    monkeypatch.setenv("RIDE_VISUALS_RENDERER_DIR", str(env_dir))
    assert _resolve_renderer_dir() == env_dir

    # Doctor reports missing entrypoint cleanly
    engine = RemotionVideoEngine(renderer_dir=tmp_path / "nonexistent")
    errors = engine.doctor()
    assert any("Remotion entrypoint was not found" in err for err in errors)
