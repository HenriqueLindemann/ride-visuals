import json
import shutil
from pathlib import Path
from typing import Callable

from ride_visuals.ingest.fit_reader import FITReader
from ride_visuals.video.progress_movie import ProgressMovieRenderer
from ride_visuals.video.spec import ActivityRenderSpec


def test_reference_fit_preserves_the_showcase_activity(reference_activity_dir: Path) -> None:
    points, metadata = FITReader.read_fit(reference_activity_dir / "activity.fit.gz")

    assert len(points) == 19_579
    assert metadata["has_hr"]
    assert metadata["has_speed"]
    assert metadata["has_temp"]
    assert not metadata["has_power"]
    assert points[0].distance_m == 0.0
    assert points[-1].distance_m == 138_714.12


def test_reference_render_spec_remains_stable(reference_activity_dir: Path) -> None:
    spec = ActivityRenderSpec.from_parquet(
        reference_activity_dir / "activity.parquet",
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


def test_reference_season_metrics_remain_stable(
    tmp_path: Path,
    reference_activity_dir: Path,
    reference_catalog_factory: Callable[[Path], Path],
) -> None:
    streams = tmp_path / "streams"
    streams.mkdir()
    shutil.copy(
        reference_activity_dir / "activity.parquet",
        streams / "19666115840.parquet",
    )
    renderer = ProgressMovieRenderer(
        reference_catalog_factory(tmp_path / "activities.duckdb"),
        streams,
        tmp_path / "outputs",
    )

    actual = renderer.extract_summary_metrics()
    expected = json.loads(
        (reference_activity_dir / "expected_metrics.json").read_text(encoding="utf-8")
    )

    assert actual == expected
