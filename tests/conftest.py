from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import duckdb
import pytest

REFERENCE_ACTIVITY_ID = 19666115840


@dataclass(frozen=True)
class ReferenceCliWorkspace:
    fixture_dir: Path
    catalog_db: Path
    streams_dir: Path
    outputs_dir: Path
    config_path: Path


@pytest.fixture(scope="session")
def reference_activity_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "reference_activity"


@pytest.fixture
def reference_catalog_factory(
    reference_activity_dir: Path,
) -> Callable[[Path], Path]:
    def create_catalog(path: Path) -> Path:
        activity = json.loads(
            (reference_activity_dir / "activity.json").read_text(encoding="utf-8")
        )
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

    return create_catalog


@pytest.fixture
def reference_cli_workspace(
    tmp_path: Path,
    reference_activity_dir: Path,
    reference_catalog_factory: Callable[[Path], Path],
) -> ReferenceCliWorkspace:
    streams_dir = tmp_path / "streams"
    streams_dir.mkdir()
    shutil.copy(
        reference_activity_dir / "activity.parquet",
        streams_dir / f"{REFERENCE_ACTIVITY_ID}.parquet",
    )
    catalog_db = reference_catalog_factory(tmp_path / "activities.duckdb")
    outputs_dir = tmp_path / "outputs"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[app]",
                'locale = "en"',
                "",
                "[video]",
                'theme = "frost"',
                "",
                "[paths]",
                f'catalog_db = "{catalog_db.as_posix()}"',
                f'streams_dir = "{streams_dir.as_posix()}"',
                f'outputs_dir = "{outputs_dir.as_posix()}"',
                f'renderer_dir = "{(tmp_path / "renderer").as_posix()}"',
            ]
        ),
        encoding="utf-8",
    )
    return ReferenceCliWorkspace(
        fixture_dir=reference_activity_dir,
        catalog_db=catalog_db,
        streams_dir=streams_dir,
        outputs_dir=outputs_dir,
        config_path=config_path,
    )
