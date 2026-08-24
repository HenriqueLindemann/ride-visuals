import numpy as np
import pandas as pd

from ride_visuals.video.telemetry import TelemetryTimeline, adaptive_speed_window_seconds


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2024-01-01T00:00:00Z", "2024-01-01T00:00:10Z", "2024-01-01T00:01:40Z"]
            ),
            "lat": [10.0, 10.1, 10.2],
            "lon": [20.0, 20.1, 20.2],
            "distance_m": [0.0, 100.0, 1000.0],
            "speed_mps": [2.0, 4.0, 8.0],
            "heart_rate_bpm": [100.0, 120.0, 160.0],
            "altitude": [100.0, 101.0, 110.0],
        }
    )


def test_progress_uses_elapsed_time_instead_of_point_count():
    timeline = TelemetryTimeline.from_frame(_frame())
    assert timeline.index_at(0.5) == 2
    assert timeline.duration_s == 100.0


def test_three_minute_speed_uses_real_time_window():
    timeline = TelemetryTimeline.from_frame(_frame(), speed_window_seconds=180)
    assert np.allclose(timeline.speed_3min_kmh, [7.2, 10.8, 16.8])
    assert timeline.total_distance_km == 1.0
    assert not timeline.available(timeline.power_watts)


def test_adaptive_speed_window_responds_to_render_compression():
    preview_window = adaptive_speed_window_seconds(18_000, 4.0, fps=30)
    final_window = adaptive_speed_window_seconds(18_000, 13.0, fps=30)
    assert preview_window > final_window
    assert 30 <= final_window <= 1200
