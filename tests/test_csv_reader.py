"""Date, number, and column parsing across localized Strava exports."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ride_visuals.ingest.csv_reader import CSVActivityReader, parse_flexible_date, parse_float_safe


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Aug 23, 2024, 7:18:50 PM", datetime(2024, 8, 23, 19, 18, 50, tzinfo=timezone.utc)),
        ("Aug 23, 2024, 12:05:00 AM", datetime(2024, 8, 23, 0, 5, 0, tzinfo=timezone.utc)),
        ("Aug 23, 2024, 19:18:50", datetime(2024, 8, 23, 19, 18, 50, tzinfo=timezone.utc)),
        ("23 de ago. de 2024, 19:18:50", datetime(2024, 8, 23, 19, 18, 50, tzinfo=timezone.utc)),
        ("23 ene. 2024, 7:18:50 p. m.", datetime(2024, 1, 23, 19, 18, 50, tzinfo=timezone.utc)),
        ("23 août 2024 à 07:18:50", datetime(2024, 8, 23, 7, 18, 50, tzinfo=timezone.utc)),
        ("23. Mär. 2024 um 19:18:50", datetime(2024, 3, 23, 19, 18, 50, tzinfo=timezone.utc)),
        ("05.08.2024, 07:18:50", datetime(2024, 8, 5, 7, 18, 50, tzinfo=timezone.utc)),
        ("23 mag 2024, 07:18:50", datetime(2024, 5, 23, 7, 18, 50, tzinfo=timezone.utc)),
        ("23 mrt. 2024 07:18:50", datetime(2024, 3, 23, 7, 18, 50, tzinfo=timezone.utc)),
    ],
)
def test_parse_flexible_date_honours_locale_and_clock_format(raw: str, expected: datetime) -> None:
    assert parse_flexible_date(raw) == expected


def test_parse_flexible_date_returns_none_for_empty_values() -> None:
    assert parse_flexible_date(None) is None
    assert parse_flexible_date("") is None


def test_parse_float_safe_handles_localized_separators() -> None:
    assert parse_float_safe("1.234,56") == 1234.56
    assert parse_float_safe("1,234.56") == 1234.56
    assert parse_float_safe("1\u202f234,56") == 1234.56


def test_csv_reader_parses_localized_export_row(tmp_path: Path) -> None:
    csv_path = tmp_path / "activities.csv"
    csv_path.write_text(
        "Aktivitäts-ID,Aktivitätsdatum,Name der Aktivität,Aktivitätsart,"
        "Bewegungszeit,Distanz.1,Höhenzunahme,Dateiname\n"
        '101,"23. Aug. 2024, 07:18:50",Morgenfahrt,Radfahrt,3500,"25.000,0",420,activities/101.fit\n',
        encoding="utf-8",
    )

    records = CSVActivityReader(csv_path).read_activities()
    assert len(records) == 1
    assert records[0]["id"] == 101
    assert records[0]["activity_type"] == "Radfahrt"
    assert records[0]["distance_raw"] == 25000.0
    assert records[0]["elevation_gain_m"] == 420.0
