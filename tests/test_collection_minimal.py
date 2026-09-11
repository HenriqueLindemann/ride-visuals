"""Distance-only collections retain motion semantics and safe framing."""
from datetime import datetime

import numpy as np
import pytest
from PIL import Image

from ride_visuals.cli import build_parser
from ride_visuals.video.collection import CollectionVideoRenderer
from ride_visuals.video.collection_data import CollectionTrack
from ride_visuals.video.collection_minimal import minimal_layout


@pytest.mark.parametrize("width,height,left,right", [
    (1920, 1080, 0, 0), (1080, 1920, 0, 0),
    (3840, 2160, 0, 0), (1920, 1080, 220, 220),
])
def test_minimal_framing_keeps_distance_clear_of_routes(width, height, left, right):
    layout = minimal_layout(width, height, safe_left=left, safe_right=right)
    assert not layout.map_rect.intersects(layout.telemetry_rect)
    assert layout.map_rect.x0 > left
    assert layout.map_rect.x1 < width - right
    assert layout.telemetry_rect.y1 < height
    assert layout.map_rect.h > height * 0.7


def test_minimal_cli_controls():
    args = build_parser().parse_args([
        "video", "collection", "--minimal", "--cursors", "--legend",
    ])
    assert args.minimal and args.cursors and args.legend
    with pytest.raises(SystemExit):
        build_parser().parse_args(["video", "collection", "--minimal", "--clean"])


@pytest.mark.parametrize("motion", ["chronological", "simultaneous"])
@pytest.mark.parametrize("details", [False, True])
@pytest.mark.parametrize("style", ["speed", "density"])
def test_minimal_render_accumulates_visible_distance(tmp_path, monkeypatch, motion, details, style):
    import ride_visuals.video.collection as collection

    samples = np.linspace(0, 1, 9)
    tracks = [CollectionTrack(
        id=i, name="Ride", date=datetime(2025, 1, i + 1), dist_km=9,
        elev_m=0, xs=samples * 1000, ys=np.sin(samples * 4 + i) * 300,
        elapsed_s=samples * (50 if i == 0 else 100), distances_m=samples ** 2 * 8000,
        ascents_m=samples * 0, altitudes=samples * 0, hrs=samples * 0,
        speeds=samples * 20, temperatures=samples * 0, grades=samples * 0,
    ) for i in range(2)]
    renderer = CollectionVideoRenderer(tmp_path / "db", tmp_path, tmp_path)
    monkeypatch.setattr(renderer, "load_all_collection_tracks", lambda: tracks)
    values, legends, frames, cursors = [], [], [], []
    original_ellipse = collection.ImageDraw.ImageDraw.ellipse

    def capture_cursor(draw, *args, **kwargs):
        cursors.append(True)
        original_ellipse(draw, *args, **kwargs)

    monkeypatch.setattr(collection.ImageDraw.ImageDraw, "ellipse", capture_cursor)
    drawn_distances = []
    original_route = renderer._draw_route

    def capture_route(draw, track, style, end_index, *args, **kwargs):
        if end_index >= 2:
            drawn_distances.append(track.point_distances_m[end_index - 1] / 1000)
        original_route(draw, track, style, end_index, *args, **kwargs)

    monkeypatch.setattr(renderer, "_draw_route", capture_route)
    original_draw = collection.draw_minimal_distance

    def capture(image, layout, distance, total, **kwargs):
        if style != "density":
            assert distance == pytest.approx(sum(drawn_distances))
        drawn_distances.clear()
        values.append(distance)
        original_draw(image, layout, distance, total, **kwargs)

    class Encoder:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def write(self, image):
            frames.append(image.copy())

    monkeypatch.setattr(collection, "RawVideoEncoder", Encoder)
    monkeypatch.setattr(collection, "draw_minimal_distance", capture)
    monkeypatch.setattr(collection, "draw_collection_panel",
                        lambda *a, **kw: pytest.fail("Minimal must not draw a telemetry panel"))
    monkeypatch.setattr(collection, "draw_map_legend", lambda *a, **kw: legends.append(True))
    renderer.render_collection(
        tmp_path / "minimal.mp4", mode="minimal", motion=motion, style=style,
        width=480, height=270, ssaa_scale=2, fps=4, duration_s=2, hold_s=0.5,
        show_cursors=details, show_legend=details,
    )
    assert values[0] == 0
    assert values[-1] == 16
    assert all(a <= b for a, b in zip(values, values[1:]))
    # Nonuniform sample distances must follow the visible route, not ride fraction.
    assert values[2] < 4
    expected = (
        [0, 0.125, 1.125, 3.125, 8, 8.125, 9.125, 11.125, 16, 16]
        if motion == "chronological" else
        [0, 0.625, 2.5, 5.625, 10, 11.125, 12.5, 14.125, 16, 16]
    )
    assert values == pytest.approx(expected)
    assert bool(cursors) == details
    assert bool(legends) == (details and style == "speed")
    assert all(isinstance(frame, Image.Image) and frame.size == (480, 270) for frame in frames)


@pytest.mark.parametrize("count,expected", [(0, 0), (1, 0), (2, 100), (3, 450), (4, 450)])
def test_distance_stays_at_drawable_endpoint(count, expected):
    from types import SimpleNamespace
    from ride_visuals.video.collection_motion import visible_distance_m

    track = SimpleNamespace(
        pixel_points=[(0, 0), (10, 10), (30, 20)],
        point_distances_m=np.array([50, 150, 500]), dist_km=0.7,
    )
    assert visible_distance_m(track, count) == expected


def test_missing_distance_fallback_counts_segments_not_points():
    from types import SimpleNamespace
    from ride_visuals.video.collection_motion import visible_distance_m

    track = SimpleNamespace(
        pixel_points=[(0, 0), (10, 10), (30, 20)],
        point_distances_m=np.full(3, np.nan), dist_km=0.7,
    )
    assert [visible_distance_m(track, k) for k in range(4)] == [0, 0, 350, 700]


@pytest.mark.parametrize("aspect", [(1920, 1080), (1080, 1920), (3840, 2160)])
@pytest.mark.parametrize("shape", ["vertical", "perimeter"])
def test_expanded_map_never_crosses_distance_counter(aspect, shape):
    from PIL import ImageDraw
    from ride_visuals.video.collection_minimal import fit_minimal_map

    width, height = aspect
    xs = np.array([0, 0, 0, 0], dtype=float) if shape == "vertical" else np.array([0, 2, 2, 0.0])
    ys = np.array([0, 1, 2, 3.0]) if shape == "vertical" else np.array([0, 0, 1, 1.0])
    samples = np.arange(4, dtype=float)
    track = CollectionTrack(
        id=1, name="Route", date=datetime(2026, 4, 2), dist_km=3, elev_m=0,
        xs=xs, ys=ys, elapsed_s=samples, distances_m=samples * 1000,
        ascents_m=samples * 0, altitudes=samples * 0, hrs=samples * 0,
        speeds=samples * 0, temperatures=samples * 0, grades=samples * 0,
    )
    scale = height / (1920 if height > width else 1080)
    initial = minimal_layout(width, height, counter_width_px=round(400 * scale))
    layout, projection = fit_minimal_map([track], initial, margin_px=round(24 * scale))
    assert layout.map_rect.h >= initial.map_rect.h
    if shape == "vertical":
        assert layout.map_rect.h > initial.map_rect.h
    mask = Image.new("1", aspect)
    ImageDraw.Draw(mask).line(projection.tracks[0].pixel_points, fill=1, width=round(10 * scale))
    counter = layout.telemetry_rect
    assert mask.crop((counter.x0, counter.y0, counter.x1, counter.y1)).getbbox() is None
