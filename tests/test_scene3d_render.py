from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ride_visuals.scene3d.camera import CameraTrack
from ride_visuals.scene3d.prefetch import prefetch_tiles, scene_tiles
from ride_visuals.scene3d.spec import SceneSpec
from ride_visuals.scene3d.tiles import TILE_SOURCES, TileCache
from ride_visuals.video.engines.remotion import RemotionVideoEngine, scene3d_chunks

LON, LAT = 7.77, 49.44


def _tile_of(lon: float, lat: float, z: int) -> tuple[int, int, int]:
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return z, x, y


def _spec(frames: int = 4, *, zoom: float = 12.3, pitch: float = 0.0, look: str = "carbon", **channels: float) -> SceneSpec:
    cam = CameraTrack(frames)
    cam.lon[:] = LON
    cam.lat[:] = LAT
    cam.zoom[:] = zoom
    cam.pitch[:] = pitch
    cam.terrain[:] = channels.get("terrain", 0.0)
    cam.contours[:] = channels.get("contours", 0.0)
    cam.satellite[:] = channels.get("satellite", 0.0)
    return SceneSpec(kind="flyover", locale="en", look=look, width=1920, height=1080, fps=30, camera=cam)


def test_top_down_scene_asks_for_the_centre_tile_of_each_source_at_its_own_level() -> None:
    tiles = scene_tiles(_spec().to_json())
    # Vector tiles are 512 px and floored; DEM tiles are 128 px (two levels up) and rounded.
    assert _tile_of(LON, LAT, 12) in tiles["vector"]
    assert _tile_of(LON, LAT, 14) in tiles["dem"]
    # A flat view is all of one level, and only what the frustum sees (no ancestors).
    assert {z for z, _, _ in tiles["vector"]} == {12}
    assert {z for z, _, _ in tiles["dem"]} == {14}
    # Neither contours nor imagery are on: no contour DEM level, no satellite source.
    assert "satellite" not in tiles


def test_pitched_relief_view_coarsens_tiles_with_distance() -> None:
    flat = scene_tiles(_spec(pitch=0.0, terrain=1.5).to_json())
    pitched = scene_tiles(_spec(pitch=75.0, terrain=1.5).to_json())
    # Relief tiles: the foreground finer than the horizon (MapLibre's
    # calculateTileZoom), over a few levels only (TILE_LOD.raster).
    dem = {z for z, _, _ in pitched["dem"]} - {z for z, _, _ in flat["dem"]}
    assert dem and min(dem) < 12
    # Vector tiles are all of one level, and more of them are in view.
    assert len({z for z, _, _ in pitched["vector"]}) == 1
    assert len(pitched["vector"]) > len(flat["vector"])


def test_terrain_loads_its_parents_and_root_level() -> None:
    tiles = scene_tiles(_spec(pitch=0.0, terrain=1.5).to_json())["dem"]
    # The terrain's own tiles are 256 px and floored (z13 here), and TerrainTileManager
    # also loads each one's parent and the root level the visibility starts from.
    assert _tile_of(LON, LAT, 13) in tiles
    assert _tile_of(LON, LAT, 12) in tiles
    assert _tile_of(LON, LAT, 5) in tiles
    assert _tile_of(LON, LAT, 6) not in tiles


def test_contours_and_satellite_add_their_own_tiles() -> None:
    spec = _spec(look="satellite", contours=1.0, satellite=1.0).to_json()
    tiles = scene_tiles(spec)
    # Contour tiles take the DEM tile of their own level (capped at the land lock)
    # and the eight around it, which maplibre-contour reads for the borders.
    z, x, y = _tile_of(LON, LAT, min(12, spec["tiles"]["landMaxZoom"]))
    around = {(z, x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    assert around <= tiles["dem"]
    # Imagery is 256 px and rounded: z12.3 asks for z13.
    assert _tile_of(LON, LAT, 13) in tiles["satellite"]


def test_a_map_below_zoom_12_first_asks_on_the_globe() -> None:
    # The style's globe (11 to 12) sees to the horizon: a fresh map at a steep pitch asks for
    # more than the mercator view the frame is then drawn with.
    low = _spec(zoom=11.5, pitch=70.0)
    high = _spec(zoom=12.5, pitch=70.0)
    assert len(scene_tiles(low.to_json())["vector"]) > len(scene_tiles(high.to_json())["vector"])


def _renderer_frames() -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / "prefetch" / "renderer_frames.json").read_text())


@pytest.mark.parametrize("frame", [480, 1950, 1995])
def test_estimate_matches_the_tiles_the_renderer_requested(frame: int) -> None:
    # Single frames of a real flyover (low zoom and steep pitch included), as the tile server saw them.
    recorded = _renderer_frames()
    case = next(item for item in recorded["frames"] if item["frame"] == frame)
    spec = {
        "profile": {**recorded["profile"], "durationInFrames": 1},
        "tiles": recorded["tiles"],
        "look": "carbon",
        "camera": {key: [value] for key, value in case["camera"].items()},
    }
    tiles = scene_tiles(spec)
    for source, listed in case["requested"].items():
        requested = {tuple(int(v) for v in item.split("/")) for item in listed.split()}
        missed = len(requested - tiles[source])
        assert missed <= max(1, 0.01 * len(requested)), (source, missed, len(requested))
        assert len(tiles[source]) <= 1.05 * len(requested), (source, len(tiles[source]), len(requested))


def test_prefetch_reports_cached_downloaded_empty_and_failed(tmp_path: Path) -> None:
    class FakeCache(TileCache):
        def get(self, source, z, x, y):
            if x == 0:
                return None
            data = b"" if x == 1 else b"tile"
            target = self.path(source, z, x, y)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return data

    cache = FakeCache(tmp_path)
    dem = TILE_SOURCES["dem"]
    cache.path(dem, 3, 3, 3).parent.mkdir(parents=True, exist_ok=True)
    cache.path(dem, 3, 3, 3).write_bytes(b"cached")
    seen: list[int] = []
    report = prefetch_tiles(
        cache,
        {"dem": {(3, 0, 0), (3, 1, 0), (3, 2, 0), (3, 3, 3)}},
        progress=lambda done, total: seen.append(done),
    )
    assert (report.cached, report.downloaded, report.empty) == (1, 1, 1)
    assert report.failed == [("dem", (3, 0, 0))]
    assert report.total == 4 and sorted(seen) == [1, 2, 3, 4]


@pytest.mark.parametrize(("frames", "chunk"), [(1, 900), (899, 900), (901, 900), (2370, 900), (5400, 900), (3, 1)])
def test_scene3d_chunks_cover_every_frame_once_without_a_short_tail(frames: int, chunk: int) -> None:
    ranges = scene3d_chunks(frames, chunk)
    covered = [f for first, last in ranges for f in range(first, last + 1)]
    assert covered == list(range(frames))
    sizes = [last - first + 1 for first, last in ranges]
    assert max(sizes) <= max(chunk * 1.5, 1)
    if len(sizes) > 1:
        assert min(sizes) >= chunk / 2


def test_scene3d_render_resumes_from_the_chunks_already_rendered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = RemotionVideoEngine(renderer_dir=tmp_path)
    monkeypatch.setattr(engine, "doctor", lambda: [])
    monkeypatch.setattr("ride_visuals.scene3d.tiles.stage_scene3d_assets", lambda renderer_dir: None)
    monkeypatch.setattr(
        "ride_visuals.video.engines.remotion.MediaValidator.validate_video",
        lambda path, expected_duration_s=None: {"valid": True, "has_faststart": True},
    )
    spec = _spec(frames=90)  # 3 s at 30 fps -> three 1 s chunks
    rendered: list[str] = []
    fail_on: set[str] = {"--frames=60-89"}

    def fake_run(command: list[str], operation: str, *, retries: int = 0) -> None:
        if "bundle" in command:
            Path(command[command.index("--out-dir") + 1]).mkdir(parents=True)
            return
        if "-f" in command:  # the ffmpeg join
            listed = Path(command[command.index("-i") + 1]).read_text(encoding="utf-8")
            Path(command[-1]).write_text(listed, encoding="utf-8")
            return
        frames = next(arg for arg in command if arg.startswith("--frames="))
        if frames in fail_on:
            raise RuntimeError(f"{operation} failed")
        rendered.append(frames)
        Path(command[5]).write_bytes(b"chunk")

    monkeypatch.setattr(engine, "_run", fake_run)
    output = tmp_path / "out" / "scene.mp4"
    with pytest.raises(RuntimeError):
        engine.render_scene3d(spec, output, spec_url="http://127.0.0.1:1/files/scene.json", chunk_seconds=1.0)
    assert rendered == ["--frames=0-29", "--frames=30-59"]
    assert not output.exists()

    # Same spec on a new server port: the two finished chunks are reused.
    fail_on.clear()
    engine.render_scene3d(spec, output, spec_url="http://127.0.0.1:2/files/scene.json", chunk_seconds=1.0)
    assert rendered == ["--frames=0-29", "--frames=30-59", "--frames=60-89"]
    assert output.read_text(encoding="utf-8").splitlines() == [
        "file 'chunk_0000.mp4'",
        "file 'chunk_0001.mp4'",
        "file 'chunk_0002.mp4'",
    ]
    # A valid video clears its chunks.
    assert not any(output.parent.glob(".scene.parts"))

    # A changed spec never reuses another spec's chunks.
    other = _spec(frames=90, zoom=11.0)
    with pytest.raises(RuntimeError):
        fail_on.add("--frames=30-59")
        engine.render_scene3d(other, output, spec_url="http://127.0.0.1:3/files/scene.json", chunk_seconds=1.0)
    assert rendered[-1] == "--frames=0-29" and len(rendered) == 4
