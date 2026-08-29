from __future__ import annotations

import json
from pathlib import Path

import pytest

from ride_visuals.cli import main

REFERENCE_ACTIVITY_ID = 19666115840


@pytest.mark.parametrize(
    ("video_type", "expected_method", "extension"),
    [
        ("telemetry", "activity", "mp4"),
        ("overlay", "overlay_still", "png"),
    ],
)
def test_reference_ride_reaches_visual_engine_with_stable_spec_and_paths(
    reference_cli_workspace,
    monkeypatch: pytest.MonkeyPatch,
    video_type: str,
    expected_method: str,
    extension: str,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeRemotionVideoEngine:
        def __init__(self, renderer_dir=None):
            calls.append({"method": "init", "renderer_dir": renderer_dir})

        def render_activity(self, spec, output_path, **kwargs):
            calls.append(
                {
                    "method": "activity",
                    "spec": spec,
                    "output_path": output_path,
                    **kwargs,
                }
            )
            return output_path, [Path("frame.png")]

        def render_overlay_still(self, spec, output_path, **kwargs):
            calls.append(
                {
                    "method": "overlay_still",
                    "spec": spec,
                    "output_path": output_path,
                    **kwargs,
                }
            )
            return output_path

    monkeypatch.setattr(
        "ride_visuals.video.engines.remotion.RemotionVideoEngine",
        FakeRemotionVideoEngine,
    )

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

    render_call = next(call for call in calls if call["method"] == expected_method)
    spec = render_call["spec"]
    assert spec.activity.id == str(REFERENCE_ACTIVITY_ID)
    assert spec.activity.title == "Kaiserslautern → Koblenz"
    assert spec.locale == "en"
    assert spec.theme == "frost"
    assert spec.profile.duration_seconds == 4.0
    assert len(spec.points) == 6_000
    assert render_call["output_path"] == (
        reference_cli_workspace.outputs_dir
        / "videos"
        / video_type
        / (
            f"activity_{REFERENCE_ACTIVITY_ID}_{video_type}_frost_en_16_9_preview."
            f"{extension}"
        )
    )
    assert render_call["spec_path"] == (
        reference_cli_workspace.outputs_dir
        / "render-specs"
        / f"activity_{REFERENCE_ACTIVITY_ID}_{video_type}_frost_en_16_9.json"
    )
    assert calls[0]["renderer_dir"] == reference_cli_workspace.config_path.parent / "renderer"
    if video_type == "telemetry":
        assert render_call["composition"] == "ActivityTelemetry"
        assert render_call["keyframes_dir"] == (
            reference_cli_workspace.outputs_dir
            / "videos/keyframes"
            / f"activity_{REFERENCE_ACTIVITY_ID}_frost_en_16_9"
        )


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
        (
            reference_cli_workspace.outputs_dir
            / "reports/progress_metrics_all.json"
        ).read_text(encoding="utf-8")
    )
    expected = json.loads(
        (reference_cli_workspace.fixture_dir / "expected_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    assert actual == expected
