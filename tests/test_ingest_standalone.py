"""Testes para importação de arquivos FIT avulsos na coleção."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from ride_visuals.ingest.csv_reader import CSVActivityReader
from ride_visuals.ingest.fit_reader import FITReader
from ride_visuals.ingest.pipeline import IngestPipeline, find_export_root
from ride_visuals.ingest.standalone import StandaloneFitImporter
from ride_visuals.model.trackpoint import TrackPoint

PT_HEADER = [
    "ID da atividade",
    "Data da atividade",
    "Nome da atividade",
    "Tipo de atividade",
    "Tempo decorrido",
    "Distância",
    "Distância.1",
    "Ganho de elevação",
    "Tempo de movimentação",
    "Velocidade máx.",
    "Velocidade média",
    "Frequência cardíaca máxima",
    "Frequência cardíaca média",
    "Esforço relativo",
    "Temperatura média",
    "Temperatura máxima",
    "Equipamento da atividade",
    "Nome do arquivo",
]

SESSION = {
    "start_time": datetime(2026, 8, 29, 6, 30, 50, tzinfo=timezone.utc),
    "sport": "cycling",
    "total_elapsed_time": 26789.0,
    "total_timer_time": 23380.0,
    "total_distance": 127541.11,
    "total_ascent": 1819,
    "avg_speed": 5.455,
    "max_speed": 16.55,
    "avg_heart_rate": 137,
    "max_heart_rate": 178,
    "avg_temperature": 21,
    "max_temperature": 29,
}


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    """Export Strava mínimo (pt-BR) com uma atividade existente."""
    export = tmp_path / "bulk_download" / "export_1"
    (export / "activities").mkdir(parents=True)
    with (export / "activities.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(PT_HEADER)
        existing = {name: "" for name in PT_HEADER}
        existing.update(
            {
                "ID da atividade": "19863657204",
                "Data da atividade": "23 de ago. de 2026, 07:18:50",
                "Nome da atividade": "Pedalada matinal",
                "Tipo de atividade": "Pedalada",
                "Tempo decorrido": "16035",
                "Distância.1": "84449.8",
                "Ganho de elevação": "462.0",
                "Tempo de movimentação": "13997.0",
                "Nome do arquivo": "activities/20998564775.fit.gz",
            }
        )
        writer.writerow([existing[name] for name in PT_HEADER])
    return export


@pytest.fixture
def fit_file(tmp_path: Path) -> Path:
    path = tmp_path / "Kalmit_Weinstraße.fit"
    path.write_bytes(b"FIT-DUMMY")
    return path


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch):
    """Substitui a leitura de session por metadados fixos."""

    def _set(**overrides):
        monkeypatch.setattr(
            FITReader, "read_session_metadata", classmethod(lambda cls, path: {**SESSION, **overrides})
        )

    return _set


def test_find_export_root_prefers_export_dir(export_dir: Path, tmp_path: Path):
    csv_file, act_dir = find_export_root(tmp_path / "bulk_download")
    assert csv_file == export_dir / "activities.csv"
    assert act_dir == export_dir / "activities"


def test_import_appends_row_and_copies_file(
    export_dir: Path, fit_file: Path, fake_session
):
    fake_session()
    importer = StandaloneFitImporter(bulk_dir=export_dir.parent)
    results = importer.import_files([fit_file])

    assert len(results) == 1
    result = results[0]
    assert result.status == "imported"
    expected_id = int(SESSION["start_time"].timestamp() * 1000)
    assert result.activity_id == expected_id
    assert result.name == "Kalmit Weinstraße"
    assert result.activity_type == "Pedalada"

    copied = export_dir / "activities" / f"{expected_id}.fit"
    assert copied.exists()
    assert copied.read_bytes() == b"FIT-DUMMY"

    rows = list(csv.DictReader((export_dir / "activities.csv").open(encoding="utf-8")))
    assert len(rows) == 2
    row = rows[-1]
    assert row["ID da atividade"] == str(expected_id)
    assert row["Nome da atividade"] == "Kalmit Weinstraße"
    assert row["Tipo de atividade"] == "Pedalada"
    assert row["Distância.1"] == "127541.11"
    assert row["Ganho de elevação"] == "1819"
    assert row["Tempo de movimentação"] == "23380"
    assert row["Frequência cardíaca média"] == "137"
    assert row["Nome do arquivo"] == f"activities/{expected_id}.fit"

    # A linha nova precisa ser legível pelo CSVActivityReader do pipeline.
    records = CSVActivityReader(export_dir / "activities.csv").read_activities()
    new_records = [r for r in records if r["id"] == expected_id]
    assert len(new_records) == 1
    assert new_records[0]["start_date"].year == 2026
    assert new_records[0]["start_date"].month == 8


def test_import_detects_duplicate_start_time(
    export_dir: Path, fit_file: Path, fake_session
):
    fake_session()
    importer = StandaloneFitImporter(bulk_dir=export_dir.parent)
    assert importer.import_files([fit_file])[0].status == "imported"

    # Mesmo treino a 30s de diferença (outro dispositivo) deve ser duplicata.
    near = export_dir.parent / "Kalmit_Weinstraße.fit"
    near.write_bytes(b"FIT-DUMMY-2")
    fake_session(start_time=SESSION["start_time"] + timedelta(seconds=30))
    importer = StandaloneFitImporter(bulk_dir=export_dir.parent)
    result = importer.import_files([near])[0]
    assert result.status == "duplicate"
    assert result.activity_id == int(SESSION["start_time"].timestamp() * 1000)


def test_import_far_start_time_is_new_activity(
    export_dir: Path, fit_file: Path, fake_session
):
    fake_session(start_time=SESSION["start_time"] - timedelta(hours=72))
    importer = StandaloneFitImporter(bulk_dir=export_dir.parent)
    result = importer.import_files([fit_file])[0]
    assert result.status == "imported"


def test_dry_run_changes_nothing(export_dir: Path, fit_file: Path, fake_session):
    fake_session()
    importer = StandaloneFitImporter(bulk_dir=export_dir.parent, dry_run=True)
    result = importer.import_files([fit_file])[0]
    assert result.status == "imported"

    rows = list(csv.DictReader((export_dir / "activities.csv").open(encoding="utf-8")))
    assert len(rows) == 1
    assert not (export_dir / "activities" / f"{result.activity_id}.fit").exists()


def test_name_and_type_overrides(export_dir: Path, fit_file: Path, fake_session):
    fake_session(sport="running")
    importer = StandaloneFitImporter(
        bulk_dir=export_dir.parent, name="Kalmit via Weinstraße", activity_type="Ride"
    )
    result = importer.import_files([fit_file])[0]
    assert result.name == "Kalmit via Weinstraße"
    assert result.activity_type == "Ride"


def test_pipeline_only_ids_ingests_only_imported(
    export_dir: Path, fit_file: Path, fake_session, monkeypatch: pytest.MonkeyPatch
):
    fake_session()
    importer = StandaloneFitImporter(bulk_dir=export_dir.parent)
    result = importer.import_files([fit_file])[0]
    act_id = result.activity_id

    start = SESSION["start_time"]
    points = [
        TrackPoint(timestamp=start, lat=49.43, lon=7.75, altitude=250.0, distance_m=0.0,
                   speed_mps=5.0, heart_rate_bpm=130.0, temperature_c=21.0),
        TrackPoint(timestamp=start + timedelta(seconds=10), lat=49.431, lon=7.751,
                   altitude=252.0, distance_m=50.0, speed_mps=5.0, heart_rate_bpm=140.0,
                   temperature_c=21.0),
    ]
    monkeypatch.setattr(
        FITReader, "read_fit", classmethod(lambda cls, path: (list(points), {}))
    )

    streams_dir = export_dir.parent.parent / "streams"
    pipeline = IngestPipeline(
        bulk_dir=export_dir.parent,
        catalog_db_path=export_dir.parent.parent / "catalog.duckdb",
        streams_dir=streams_dir,
        only_ids={act_id},
    )
    stats = pipeline.run_ingest()
    assert stats["ingested_activities"] == 1
    assert stats["total_scoped"] == 2
    assert (streams_dir / f"{act_id}.parquet").exists()
    assert not (streams_dir / "19863657204.parquet").exists()

    con = duckdb.connect(str(export_dir.parent.parent / "catalog.duckdb"), read_only=True)
    ids = [row[0] for row in con.execute("SELECT id FROM activities").fetchall()]
    con.close()
    assert ids == [act_id]
