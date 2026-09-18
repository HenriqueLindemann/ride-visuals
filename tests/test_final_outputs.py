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
    assert paths[0] == outputs / "videos/collection/collection_years-2024_months-02_chronological_heart_rate_dark_16_9_en.mp4"
    assert paths[-1] == outputs / "videos/timeline/timeline_years-2024_months-02_9_16.mp4"


def test_final_video_paths_follow_the_collection_locale_tag() -> None:
    outputs = Path("custom-outputs")

    portuguese = final_video_paths(
        outputs,
        ActivitySelection(),
        motion="simultaneous",
        style="density",
        basemap="plain",
        locale="pt-BR",
    )

    assert portuguese[0] == outputs / "videos/collection/collection_all_simultaneous_density_16_9_pt_br.mp4"
    assert portuguese[1] == outputs / "videos/collection/collection_all_simultaneous_density_9_16_pt_br.mp4"
