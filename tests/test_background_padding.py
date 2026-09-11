from pathlib import Path
from types import SimpleNamespace

from ride_visuals.commands.video_activity import _ensure_background_video_duration


def test_padding_cache_tracks_content_and_exact_duration(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    first = tmp_path / "a" / "clip.mp4"
    second = tmp_path / "b" / "clip.mp4"
    for source, content in [(first, b"first"), (second, b"other")]:
        source.parent.mkdir()
        source.write_bytes(content)
    calls = []

    def render(command, **kwargs):
        calls.append(command)
        Path(command[-1]).write_bytes(Path(command[command.index("-i") + 1]).read_bytes())

    monkeypatch.setattr("subprocess.run", render)
    monkeypatch.setattr(
        "ride_visuals.video.spec.probe_video",
        lambda path: SimpleNamespace(
            duration_seconds=20 if outputs in path.parents else 1, has_audio=False
        ),
    )
    cached = _ensure_background_video_duration(first, 15.0, outputs)
    assert _ensure_background_video_duration(first, 15.0, outputs) == cached
    assert len(calls) == 1
    other = _ensure_background_video_duration(second, 15.0, outputs)
    assert other != cached
    assert other.read_bytes() == b"other"
    first.write_bytes(b"updated")
    updated = _ensure_background_video_duration(first, 15.0, outputs)
    assert updated != cached
    assert updated.read_bytes() == b"updated"
    assert _ensure_background_video_duration(first, 15.5, outputs) != updated


def test_long_background_is_reused_without_encoding(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    monkeypatch.setattr(
        "ride_visuals.video.spec.probe_video",
        lambda path: SimpleNamespace(duration_seconds=20, has_audio=False),
    )
    assert _ensure_background_video_duration(source, 15, tmp_path) == source
