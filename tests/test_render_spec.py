import json

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ride_visuals.video.spec import ActivityRenderSpec, RenderProfile


def test_render_profile_rejects_odd_video_dimensions():
    with pytest.raises(ValueError, match="even"):
        RenderProfile(width=1919)


def test_render_spec_is_versioned_and_json_safe(tmp_path):
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-08-23T08:00:00Z", periods=4, freq="1s"),
            "lat": [10.0, 10.001, 10.002, 10.003],
            "lon": [20.0, 20.001, 20.002, 20.003],
            "altitude": [250.0, 251.0, 252.0, 253.0],
            "distance_m": [0.0, 100.0, 200.0, 300.0],
            "speed_mps": [5.0, 6.0, 7.0, 8.0],
            "heart_rate_bpm": [120.0, 125.0, 130.0, 135.0],
            "power_watts": [None, None, None, None],
        }
    )
    parquet = tmp_path / "activity.parquet"
    pq.write_table(pa.Table.from_pandas(frame), parquet)

    spec = ActivityRenderSpec.from_parquet(
        parquet,
        activity_id=42,
        title="Morning Ride",
        locale="pt-BR",
        max_points=3,
    )
    output = spec.write(tmp_path / "render.json")
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schemaVersion"] == "1.0"
    assert payload["kind"] == "activity-telemetry"
    assert payload["locale"] == "pt-BR"
    assert payload["activity"]["id"] == "42"
    assert payload["background"] is None
    assert payload["summary"]["speedWindowSeconds"] >= 30
    assert payload["show_progress_bar"] is False
    assert payload["presentation"] == "standard"
    assert len(payload["points"]) == 3
    assert payload["points"][0]["powerWatts"] is None
    assert "cumulativeElevationGainM" in payload["points"][0]


def test_render_spec_can_enable_progress_bar(tmp_path):
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-08-23T08:00:00Z", periods=2, freq="1s"),
            "lat": [10.0, 10.001],
            "lon": [20.0, 20.001],
            "distance_m": [0.0, 100.0],
        }
    )
    parquet = tmp_path / "activity.parquet"
    pq.write_table(pa.Table.from_pandas(frame), parquet)

    spec = ActivityRenderSpec.from_parquet(
        parquet,
        activity_id=42,
        title="Morning Ride",
        show_progress_bar=True,
    )

    assert spec.show_progress_bar is True



def test_render_spec_embeds_portable_background(tmp_path):
    from PIL import Image

    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-08-23T08:00:00Z", periods=2, freq="1s"),
            "lat": [10.0, 10.001],
            "lon": [20.0, 20.001],
            "distance_m": [0.0, 100.0],
        }
    )
    parquet = tmp_path / "activity.parquet"
    pq.write_table(pa.Table.from_pandas(frame), parquet)
    background = tmp_path / "background.png"
    Image.new("RGB", (4, 4), "navy").save(background)

    spec = ActivityRenderSpec.from_parquet(
        parquet,
        activity_id=42,
        title="Morning Ride",
        background_image=background,
        background_blur_px=12,
        background_dim=0.45,
    )

    assert spec.background is not None
    assert spec.background.src.startswith("data:image/png;base64,")
    assert spec.background.blur_px == 12
    assert spec.background.dim == 0.45
    assert spec.background.attribution is None
    assert spec.background.attribution_bottom_px == 6.0
