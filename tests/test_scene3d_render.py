from __future__ import annotations

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
    # Vector tiles are 512 px and floored; DEM tiles are 128 px (two levels up),
    # floored for the mesh and rounded for the hillshade.
    assert _tile_of(LON, LAT, 12) in tiles["vector"]
    assert _tile_of(LON, LAT, 14) in tiles["dem"]
    assert max(z for z, _, _ in tiles["vector"]) == 12
    # z14.3 is within SPLIT_MARGIN of the rounded hillshade going to z15.
    assert max(z for z, _, _ in tiles["dem"]) == 15
    # MapLibre's placeholder ancestors (prefetchZoomDelta) come along.
    assert _tile_of(LON, LAT, 8) in tiles["vector"] and _tile_of(LON, LAT, 7) not in tiles["vector"]
    # Neither contours nor imagery are on: no contour DEM level, no satellite source.
    assert "satellite" not in tiles


def test_pitched_relief_view_coarsens_tiles_with_distance() -> None:
    flat = scene_tiles(_spec(pitch=0.0, terrain=1.5).to_json())
    pitched = scene_tiles(_spec(pitch=75.0, terrain=1.5).to_json())
    levels = {z for z, _, _ in pitched["vector"]}
    # The foreground is closer than the centre and gets a finer level; the
    # horizon coarser ones (MapLibre's calculateTileZoom).
    assert max(levels) >= 12 and min(levels) < 11
    assert len(pitched["vector"]) > len(flat["vector"])


def test_contours_and_satellite_add_their_own_tiles() -> None:
    spec = _spec(look="satellite", contours=1.0, satellite=1.0).to_json()
    tiles = scene_tiles(spec)
    # Contour tiles take the DEM tile of their own level (capped at the relief lock).
    contour_level = max(10, min(spec["tiles"]["demMaxZoom"] - 2, 14))
    assert _tile_of(LON, LAT, min(12, contour_level)) in tiles["dem"]
    # Imagery is 256 px and rounded: z12.3 asks for z13.
    assert _tile_of(LON, LAT, 13) in tiles["satellite"]


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
