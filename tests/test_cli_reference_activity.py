from __future__ import annotations

import json
from pathlib import Path

import pytest

from ride_visuals.cli import main

REFERENCE_ACTIVITY_ID = 19666115840


@pytest.fixture
def captured_remotion_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    class FakeRemotionVideoEngine:
        def __init__(self, renderer_dir=None):
            self.renderer_dir = renderer_dir

        def render_activity(self, spec, output_path, **kwargs):
            calls.append({"method": "activity", "spec": spec, "output_path": output_path, **kwargs})
            return output_path, [Path("frame.png")]

        def render_overlay_still(self, spec, output_path, **kwargs):
            calls.append(
                {"method": "overlay_still", "spec": spec, "output_path": output_path, **kwargs}
            )
            return output_path

        def render_overlay_video(self, spec, output_path, **kwargs):
            calls.append(
                {"method": "overlay_video", "spec": spec, "output_path": output_path, **kwargs}
            )
            return output_path

    monkeypatch.setattr(
        "ride_visuals.video.engines.remotion.RemotionVideoEngine",
        FakeRemotionVideoEngine,
    )
    return calls


@pytest.mark.parametrize(
    ("video_type", "expected_method", "extension"),
    [
        ("telemetry", "activity", "mp4"),
        ("minimal", "activity", "mp4"),
        ("overlay", "overlay_still", "png"),
        ("route-overlay", "overlay_video", "webm"),
        ("stats-overlay", "overlay_video", "webm"),
    ],
)
def test_reference_ride_reaches_visual_engine_with_stable_spec_and_paths(
    reference_cli_workspace,
    captured_remotion_calls: list[dict[str, object]],
    video_type: str,
    expected_method: str,
    extension: str,
) -> None:
    main(
        [
            "video",
            video_type,
            str(REFERENCE_ACTIVITY_ID),
            "--preview",
            "--config",
            str(reference_cli_workspace.config_path),
        ]
    )

    render_call = captured_remotion_calls[0]
    spec = render_call["spec"]
    assert render_call["method"] == expected_method
    assert spec.activity.id == str(REFERENCE_ACTIVITY_ID)
    assert spec.activity.title == "Kaiserslautern → Koblenz"
    assert spec.show_background_route is (video_type != "minimal")
    assert render_call["output_path"] == (
        reference_cli_workspace.outputs_dir
        / "videos"
        / video_type
        / f"activity_{REFERENCE_ACTIVITY_ID}_{video_type}_frost_en_16_9_preview.{extension}"
    )


def test_minimal_overlay_ignores_background_media(
    reference_cli_workspace,
    captured_remotion_calls: list[dict[str, object]],
) -> None:
    main(
        [
            "video",
            "minimal",
            str(REFERENCE_ACTIVITY_ID),
            "--preview",
            "--overlay-format",
            "mov",
            "--background-image",
            "unused-media",
            "--config",
            str(reference_cli_workspace.config_path),
        ]
    )

    call = captured_remotion_calls[0]
    assert call["spec"].background is None
    assert call["output_path"].suffix == ".mov"
    assert call["composition"] == "ActivityMinimalOverlay"


def test_reference_ride_progress_report_matches_canonical_metrics(
    reference_cli_workspace,
) -> None:
    main(
        [
            "report",
            "progress",
            "--config",
            str(reference_cli_workspace.config_path),
        ]
    )

    actual = json.loads(
        (reference_cli_workspace.outputs_dir / "reports/progress_metrics_all.json").read_text(
            encoding="utf-8"
        )
    )
    expected = json.loads(
        (reference_cli_workspace.fixture_dir / "expected_metrics.json").read_text(encoding="utf-8")
    )
    assert actual == expected


def test_separate_overlays_share_timeline_across_orientations(
    reference_cli_workspace,
    captured_remotion_calls: list[dict[str, object]],
) -> None:
    for kind, aspect in [("route-overlay", "16:9"), ("stats-overlay", "9:16")]:
        main(
            [
                "video",
                kind,
                str(REFERENCE_ACTIVITY_ID),
                "--aspect",
                aspect,
                "--overlay-format",
                "mov",
                "--config",
                str(reference_cli_workspace.config_path),
            ]
        )
    route, stats = (call["spec"] for call in captured_remotion_calls)
    assert route.points == stats.points
    assert route.profile.duration_seconds == stats.profile.duration_seconds == 13
    assert (stats.profile.width, stats.profile.height) == (320, 640)
