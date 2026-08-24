from datetime import datetime, timezone

import duckdb
import pytest

from ride_visuals.selection import ActivitySelection


def test_selection_combines_inclusive_range_years_and_months():
    selection = ActivitySelection.from_values(
        start_date="2024-02-01",
        end_date="2024-03-31",
        years=[2024],
        months=[2, 3],
    )

    assert selection.matches(datetime(2024, 2, 1, tzinfo=timezone.utc))
    assert selection.matches(datetime(2024, 3, 31, 23, 59, tzinfo=timezone.utc))
    assert not selection.matches(datetime(2024, 4, 1, tzinfo=timezone.utc))


def test_selection_sql_matches_duckdb_catalog_rows():
    selection = ActivitySelection.from_values(years=[2023, 2024], months=[2])
    where, parameters = selection.sql()
    connection = duckdb.connect()
    connection.execute("CREATE TABLE activities(start_date TIMESTAMPTZ)")
    connection.execute(
        "INSERT INTO activities VALUES (?), (?), (?)",
        ["2023-02-10", "2024-02-10", "2024-03-10"],
    )

    count = connection.execute(
        f"SELECT count(*) FROM activities{where}", parameters
    ).fetchone()[0]

    assert count == 2


def test_selection_rejects_invalid_month():
    with pytest.raises(ValueError, match="Months"):
        ActivitySelection.from_values(months=[13])
