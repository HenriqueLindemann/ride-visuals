import json
from pathlib import Path
import shutil

import duckdb

from ride_visuals.ingest.fit_reader import FITReader
from ride_visuals.video.progress_movie import ProgressMovieRenderer
from ride_visuals.video.spec import ActivityRenderSpec


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reference_activity"



def _reference_catalog(path: Path) -> Path:
    activity = json.loads((FIXTURE_DIR / "activity.json").read_text(encoding="utf-8"))
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE activities (
                id BIGINT, name VARCHAR, start_date TIMESTAMPTZ, activity_type VARCHAR,
                distance_m DOUBLE, elevation_gain_m DOUBLE, moving_time_s BIGINT,
                elapsed_time_s BIGINT, avg_speed_mps DOUBLE, max_speed_mps DOUBLE,
                avg_heart_rate DOUBLE, max_heart_rate DOUBLE, relative_effort DOUBLE,
                estimated_watts_avg DOUBLE, estimated_watts_max DOUBLE,
                temperature_avg DOUBLE, temperature_max DOUBLE, gear VARCHAR,
                source_filename VARCHAR, source_format VARCHAR, file_sha256 VARCHAR,
                point_count BIGINT, has_hr_stream BOOLEAN, has_speed_stream BOOLEAN,
                has_temp_stream BOOLEAN, has_watts_stream BOOLEAN
            )
            """
        )
        columns = list(activity)
        placeholders = ", ".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO activities ({', '.join(columns)}) VALUES ({placeholders})",
            [activity[column] for column in columns],
        )
    return path


def test_reference_fit_preserves_the_showcase_activity() -> None:
    points, metadata = FITReader.read_fit(FIXTURE_DIR / "activity.fit.gz")

    assert len(points) == 19_579
    assert metadata["has_hr"]
    assert metadata["has_speed"]
    assert metadata["has_temp"]
    assert not metadata["has_power"]
    assert points[0].distance_m == 0.0
    assert points[-1].distance_m == 138_714.12


def test_reference_render_spec_remains_stable() -> None:
    spec = ActivityRenderSpec.from_parquet(
        FIXTURE_DIR / "activity.parquet",
        activity_id=19666115840,
        title="Kaiserslautern -> Koblenz",
        activity_date="2026-08-09",
        max_points=6_000,
    )

    assert spec.summary == {
        "distanceKm": 138.714,
        "elevationGainM": 587.0,
        "sourceDurationSeconds": 23_384.0,
        "sourcePointCount": 19_579.0,
        "renderPointCount": 6_000.0,
        "speedWindowSeconds": 1_200.0,
        "maximumGradePct": 9.7,
    }
    assert len(spec.points) == 6_000
    assert spec.points[0]["powerWatts"] is None


def test_reference_season_metrics_remain_stable(tmp_path: Path) -> None:
    streams = tmp_path / "streams"
    streams.mkdir()
    shutil.copy(FIXTURE_DIR / "activity.parquet", streams / "19666115840.parquet")
    renderer = ProgressMovieRenderer(
        _reference_catalog(tmp_path / "activities.duckdb"),
        streams,
        tmp_path / "outputs",
    )

    actual = renderer.extract_summary_metrics()
    expected = json.loads(
        (FIXTURE_DIR / "expected_metrics.json").read_text(encoding="utf-8")
    )

    assert actual == expected
