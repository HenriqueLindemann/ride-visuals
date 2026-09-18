"""Date parsing for both Strava export formats."""

from datetime import datetime, timezone

import pytest

from ride_visuals.ingest.csv_reader import parse_flexible_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # English export uses a 12-hour clock; the meridiem must be applied.
        ("Aug 23, 2024, 7:18:50 PM", datetime(2024, 8, 23, 19, 18, 50, tzinfo=timezone.utc)),
        ("Aug 23, 2024, 7:18:50 AM", datetime(2024, 8, 23, 7, 18, 50, tzinfo=timezone.utc)),
        ("Aug 23, 2024, 12:05:00 AM", datetime(2024, 8, 23, 0, 5, 0, tzinfo=timezone.utc)),
        ("Aug 23, 2024, 12:05:00 PM", datetime(2024, 8, 23, 12, 5, 0, tzinfo=timezone.utc)),
        # A 24-hour English timestamp without a meridiem stays untouched.
        ("Aug 23, 2024, 19:18:50", datetime(2024, 8, 23, 19, 18, 50, tzinfo=timezone.utc)),
        # The Portuguese export keeps its 24-hour clock.
        ("23 de ago. de 2024, 19:18:50", datetime(2024, 8, 23, 19, 18, 50, tzinfo=timezone.utc)),
        ("23 de agosto de 2024, 07:18:50", datetime(2024, 8, 23, 7, 18, 50, tzinfo=timezone.utc)),
    ],
)
def test_parse_flexible_date_honours_the_clock_format(raw: str, expected: datetime) -> None:
    assert parse_flexible_date(raw) == expected


def test_parse_flexible_date_returns_none_for_empty_values() -> None:
    assert parse_flexible_date(None) is None
    assert parse_flexible_date("") is None
