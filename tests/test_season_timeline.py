from pathlib import Path

import duckdb

from ride_visuals.analytics.season_timeline import SeasonTimelineGenerator


def test_season_timeline_uses_one_ordered_calendar(tmp_path: Path):
    database = tmp_path / "activities.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE activities ("
            "id BIGINT, start_date TIMESTAMP, distance_m DOUBLE, elevation_gain_m DOUBLE, "
            "moving_time_s BIGINT, avg_speed_mps DOUBLE, avg_heart_rate DOUBLE, "
            "temperature_avg DOUBLE, point_count BIGINT, has_hr_stream BOOLEAN, has_temp_stream BOOLEAN)"
        )
        connection.execute(
            "INSERT INTO activities VALUES "
            "(2, '2024-05-02', 20000, 200, 3600, 6, 140, 20, 2000, true, true), "
            "(1, '2024-04-02', 10000, 100, 1800, 5, 130, NULL, 1000, true, false)"
        )

    frame = SeasonTimelineGenerator(database, tmp_path).load_frame()

    assert list(frame["id"]) == [1, 2]
    assert list(frame["cumulative_km"]) == [10.0, 30.0]
    assert list(frame["average_speed_kmh"]) == [18.0, 21.6]
