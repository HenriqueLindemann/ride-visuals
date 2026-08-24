from pathlib import Path

from ride_visuals.cli import final_video_paths
from ride_visuals.selection import ActivitySelection


def test_final_video_paths_are_scoped_and_ignore_unrelated_media() -> None:
    outputs = Path("custom-outputs")
    selection = ActivitySelection.from_values(years=[2024], months=[2])

    paths = final_video_paths(
        outputs,
        selection,
        motion="chronological",
        style="heart_rate",
        basemap="dark",
    )

    assert len(paths) == 6
    assert paths[0] == outputs / "videos/collection/collection_years-2024_months-02_chronological_heart_rate_dark_16_9.mp4"
    assert paths[-1] == outputs / "videos/timeline/timeline_years-2024_months-02_9_16.mp4"
