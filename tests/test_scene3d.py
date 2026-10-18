"""Tests for the 3D scene pipeline: tiles, terrain, tracks, climbs, places, and directors."""

from __future__ import annotations

import gzip
import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from ride_visuals.cli import build_parser
from ride_visuals.scene3d.camera import eye_offset
from ride_visuals.scene3d.climbs import detect_climbs, featured_climbs, hero_climb
from ride_visuals.scene3d.flyover import (
    MAX_BEARING_RATE_DEG_S,
    SIDE_ORBIT_RATE_DEG_S,
    FlyoverMetadata,
    build_flyover_spec,
)
from ride_visuals.scene3d.framing import MAX_ZOOM_RATE, project_points
from ride_visuals.scene3d.places import (
    destination_for_distance,
    home_cluster,
    nearest_place,
)
from ride_visuals.scene3d.strata import build_strata_spec
from ride_visuals.scene3d.stretch import SceneRide, build_stretch_spec
from ride_visuals.scene3d.terrain import DemSampler, decode_terrarium
from ride_visuals.scene3d.tiles import (
    TileCache,
    TileServer,
    TileSource,
    stage_scene3d_assets,
)
from ride_visuals.scene3d.track import RideTrack, from_local_xy, local_xy


def _make_terrarium_png(elevation_m: float, size: int = 16) -> bytes:
    val = elevation_m + 32768.0
    r = int(np.clip(np.floor(val / 256.0), 0, 255))
    rem = val - r * 256.0
    g = int(np.clip(np.floor(rem), 0, 255))
    b = int(np.clip(np.round((rem - g) * 256.0), 0, 255))
    arr = np.zeros((size, size, 3), dtype=np.uint8)
    arr[..., 0] = r
    arr[..., 1] = g
    arr[..., 2] = b
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def test_decode_terrarium_known_elevation() -> None:
    png = _make_terrarium_png(487.5, size=8)
    decoded = decode_terrarium(png)
    assert decoded.shape == (8, 8)
    assert np.allclose(decoded, 487.5, atol=0.02)


def test_tile_cache_and_tile_server_with_local_upstream(tmp_path: Path) -> None:
    payload_raw = b"vector-tile-bytes"
    payload_gz = gzip.compress(payload_raw)

    class UpstreamHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path.endswith("/0_0.pbf"):
                self.send_response(HTTPStatus.OK)
                self.end_headers()
                self.wfile.write(payload_gz)
            elif self.path.endswith("/0_1.pbf"):
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
            else:
                self.send_response(HTTPStatus.OK)
                self.end_headers()
                self.wfile.write(_make_terrarium_png(250.0, size=256))

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    u_host, u_port = upstream.server_address[:2]
    import threading

    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        source = TileSource(
            key="vector",
            url=f"http://{u_host}:{u_port}/{{z}}/{{x}}_{{y}}.pbf",
            ext="pbf",
            max_zoom=4,
            cache_key="test-vec",
            content_type="application/x-protobuf",
            credits=("openfreemap",),
        )
        cache = TileCache(tmp_path / "tiles")
        # Out-of-bounds zoom/coords return None without hitting upstream.
        assert cache.get(source, -1, 0, 0) is None
        assert cache.get(source, 5, 0, 0) is None
        assert cache.get(source, 1, 9, 0) is None

        # Gzipped payload is transparently decompressed and cached on disk.
        assert cache.get(source, 1, 0, 0) == payload_raw
        # 404 is cached as an empty file (b"").
        assert cache.get(source, 1, 0, 1) == b""

        # Offline cache reads existing tiles and returns None for uncached ones.
        offline_cache = TileCache(tmp_path / "tiles", offline=True)
        assert offline_cache.get(source, 1, 0, 0) == payload_raw
        assert offline_cache.get(source, 1, 0, 1) == b""
        assert offline_cache.get(source, 1, 1, 1) is None

        # TileServer serves cached tiles, 204 for empty tiles, CORS headers, and /files.
        spec_file = tmp_path / "spec.json"
        spec_file.write_text('{"ok":true}', encoding="utf-8")
        # Pre-populate a "dem" tile in the cache so TileServer can serve it offline.
        from ride_visuals.scene3d.tiles import TILE_SOURCES

        dem_path = offline_cache.path(TILE_SOURCES["dem"], 2, 1, 1)
        dem_path.parent.mkdir(parents=True, exist_ok=True)
        dem_path.write_bytes(b"png-bytes")
        empty_dem = offline_cache.path(TILE_SOURCES["dem"], 2, 1, 2)
        empty_dem.write_bytes(b"")

        with TileServer(offline_cache) as server:
            file_url = server.publish("scene.json", spec_file)
            with urllib.request.urlopen(file_url, timeout=5) as resp:
                assert resp.status == 200
                assert resp.headers.get("Access-Control-Allow-Origin") == "*"
                assert json.loads(resp.read()) == {"ok": True}

            with urllib.request.urlopen(f"{server.base_url}/tiles/dem/2/1/1.png", timeout=5) as resp:
                assert resp.status == 200
                assert resp.read() == b"png-bytes"

            with urllib.request.urlopen(f"{server.base_url}/tiles/dem/2/1/2.png", timeout=5) as resp:
                assert resp.status == 204

            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(f"{server.base_url}/tiles/dem/2/3/3.png", timeout=5)
            assert err.value.code == 404
            assert server.failures == 1
    finally:
        upstream.shutdown()
        upstream.server_close()


def test_stage_scene3d_assets_copies_worker_and_font(tmp_path: Path) -> None:
    renderer = tmp_path / "renderer"
    (renderer / "node_modules" / "maplibre-gl" / "dist").mkdir(parents=True)
    (renderer / "node_modules" / "geist" / "dist" / "fonts" / "geist-sans").mkdir(parents=True)
    (renderer / "node_modules" / "maplibre-gl" / "dist" / "maplibre-gl-worker.mjs").write_bytes(b"worker")
    (renderer / "node_modules" / "maplibre-gl" / "dist" / "maplibre-gl-shared.mjs").write_bytes(b"shared")
    (renderer / "node_modules" / "geist" / "dist" / "fonts" / "geist-sans" / "Geist-Variable.woff2").write_bytes(b"font")

    stage_scene3d_assets(renderer)

    staged = renderer / "public" / "scene3d"
    assert (staged / "maplibre-gl-worker.mjs").read_bytes() == b"worker"
    assert (staged / "maplibre-gl-shared.mjs").read_bytes() == b"shared"
    assert (staged / "Geist-Variable.woff2").read_bytes() == b"font"


def test_ride_track_cleaning_antimeridian_and_roundtrip_encoding() -> None:
    # Includes (0, 0), NaN, stationary duplicate, GPS spike, and antimeridian crossing.
    lons = np.array([0.0, np.nan, 179.99, 179.99, 179.995, -170.0, -179.995, -179.99])
    lats = np.array([0.0, 10.0, 10.0, 10.0, 10.005, 45.0, 10.001, 10.008])
    alts = np.array([0.0, 0.0, 100.0, 100.0, np.nan, 9999.0, 120.0, 130.0])

    track = RideTrack.from_arrays(lons, lats, alts).fill_altitude(None)

    assert len(track.lon) == 4
    # Unwrapped across 180 deg so longitudes are continuous.
    assert np.all(np.diff(track.lon) > 0)
    assert np.isfinite(track.alt).all()
    assert np.allclose(track.alt, [100.0, 110.0, 120.0, 130.0])

    encoded = track.encode(tolerance_m=0.1)
    dec_lon = np.cumsum(encoded["x"]) * 1e-6
    dec_lat = np.cumsum(encoded["y"]) * 1e-6
    dec_d = np.cumsum(encoded["d"]) * 0.1
    assert np.allclose(dec_lon, track.lon, atol=2e-6)
    assert np.allclose(dec_lat, track.lat, atol=2e-6)
    assert np.allclose(dec_d, track.dist, atol=0.2)


def test_climb_detection_on_synthetic_profiles() -> None:
    dist = np.linspace(0.0, 20_000.0, 2001)
    # 1. Flat profile -> no climbs.
    assert detect_climbs(dist, np.full_like(dist, 200.0)) == []

    # 2. Single steady climb of +300 m over 5 km (6%), with a small 8 m dip mid-climb (< 15 m threshold).
    alt = np.full_like(dist, 100.0)
    lead_mask = dist < 5_000.0
    alt[lead_mask] = 130.0 - 30.0 * (dist[lead_mask] / 5_000.0)
    climb_mask = (dist >= 5_000.0) & (dist <= 10_000.0)
    alt[climb_mask] = 100.0 + 300.0 * ((dist[climb_mask] - 5_000.0) / 5_000.0)
    dip_mask = (dist >= 7_000.0) & (dist <= 7_400.0)
    alt[dip_mask] -= 8.0 * np.sin(np.pi * (dist[dip_mask] - 7_000.0) / 400.0)
    alt[dist > 10_000.0] = 400.0 - 200.0 * ((dist[dist > 10_000.0] - 10_000.0) / 10_000.0)

    climbs = detect_climbs(dist, alt)
    assert len(climbs) == 1
    assert abs(climbs[0].gain_m - 300.0) < 5.0
    assert abs(climbs[0].grade_pct - 6.0) < 0.5

    # 3. Sawtooth profile with 4 climbs -> featured_climbs returns top 3 in ride order.
    saw_alt = 200.0 + 90.0 * np.sin(2.0 * np.pi * dist / 4_500.0)
    all_saw = detect_climbs(dist, saw_alt)
    top_saw = featured_climbs(all_saw, limit=3)
    assert len(top_saw) <= 3
    assert [c.start_m for c in top_saw] == sorted(c.start_m for c in top_saw)


def _profile(points: list[tuple[float, float]], step_m: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    """Piecewise-linear profile through (km, altitude) points, sampled every ``step_m``."""
    km = np.array([p[0] for p in points]) * 1000.0
    dist = np.arange(0.0, km[-1] + step_m, step_m)
    return dist, np.interp(dist, km, [p[1] for p in points])


def test_climb_continues_through_a_false_flat() -> None:
    # A mountain road with a 33 m dip two thirds of the way up (as on the Kalmit).
    dist, alt = _profile([(0, 200), (2, 200), (9.5, 510), (11, 477), (14, 666), (20, 300)])
    climbs = detect_climbs(dist, alt)
    assert len(climbs) == 1
    assert climbs[0].start_m == pytest.approx(2_000.0, abs=50.0)
    assert climbs[0].end_m == pytest.approx(14_000.0, abs=50.0)
    assert climbs[0].gain_m == pytest.approx(466.0, abs=2.0)


def test_climb_does_not_absorb_a_rolling_approach_or_a_deep_dip() -> None:
    # A 1.5% roller, a dip, then the real climb: the roller is not climbing.
    rolling = detect_climbs(*_profile([(0, 120), (3, 165), (4.5, 125), (10, 480), (14, 300)]))
    assert [round(c.start_m / 1000.0, 1) for c in rolling] == [4.5]
    # Two climbs split by a long, deep descent stay two climbs.
    deep = detect_climbs(*_profile([(0, 100), (4, 400), (7, 200), (11, 500), (15, 200)]))
    assert len(deep) == 2


def test_climb_starts_where_the_climbing_starts() -> None:
    # 16 km of gentle valley road (1%) into a 2 km wall (7%): the climb is the wall.
    climbs = detect_climbs(*_profile([(0, 200), (16, 360), (18, 500), (22, 300)]))
    assert len(climbs) == 1
    assert climbs[0].start_m == pytest.approx(16_000.0, abs=100.0)
    assert climbs[0].grade_pct == pytest.approx(7.0, abs=0.3)


def test_hero_is_the_climb_that_gains_the_most() -> None:
    # A short steep wall can outscore a long mountain road; the story is the mountain.
    climbs = detect_climbs(*_profile([(0, 200), (11, 660), (14, 300), (19.5, 630), (25, 300)]))
    mountain = max(climbs, key=lambda c: c.gain_m)
    assert hero_climb(climbs) == mountain
    assert mountain in featured_climbs(climbs, limit=1, include=mountain)
    assert hero_climb(detect_climbs(*_profile([(0, 200), (1, 260), (3, 200)]))) is None


class _FakeSampler(DemSampler):
    """Synthetic DEM with a mountain ridge for testing camera clearance without network."""

    def __init__(self, ridge_height: float = 650.0) -> None:
        self.ridge_height = ridge_height

    def sample(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        return self.ridge_height * np.exp(-(((lon - 7.80) / 0.03) ** 2 + ((lat - 49.40) / 0.03) ** 2))

    def sample_blurred(self, lon: np.ndarray, lat: np.ndarray, radius_m: float) -> np.ndarray:
        return self.sample(lon, lat) * 0.9


def _synthetic_ride(length_km: float = 45.0, max_climb_m: float = 380.0, with_nan_alt: bool = False) -> RideTrack:
    n = 900
    s = np.linspace(0.0, length_km * 1000.0, n)
    origin = (7.77, 49.44)
    angle = 2.0 * np.pi * (s / (length_km * 1000.0))
    radius = (length_km * 1000.0) / (2.0 * np.pi)
    x = radius * np.sin(angle)
    y = radius * (1.0 - np.cos(angle))
    lon, lat = from_local_xy(x, y, origin)
    if with_nan_alt:
        alt = np.full(n, np.nan)
    elif max_climb_m <= 0.0:
        alt = np.full(n, 180.0)
    else:
        alt = 180.0 + max_climb_m * np.exp(-(((s / (length_km * 1000.0)) - 0.45) / 0.12) ** 2)
    return RideTrack.from_arrays(lon, lat, alt, s / 8.0)


def test_flyover_director_invariants_and_terrain_clearance(tmp_path: Path) -> None:
    track = _synthetic_ride(length_km=60.0, max_climb_m=420.0)
    sampler = _FakeSampler(ridge_height=700.0)
    spec = build_flyover_spec(
        track,
        metadata=FlyoverMetadata(
            activity_id=1,
            start_date=datetime(2026, 8, 29, tzinfo=timezone.utc),
            distance_m=60_000.0,
            elevation_gain_m=950.0,
            moving_time_s=7_800.0,
        ),
        sampler=sampler,
        locale="pt-BR",
        look="satellite",
        width=1920,
        height=1080,
        fps=30,
        places_cache_dir=tmp_path,
        offline=True,
    )

    payload = spec.to_json()
    frames = spec.frames
    assert payload["kind"] == "flyover"
    assert payload["look"] == "satellite"
    for values in spec.channels.values():
        assert len(values) == frames
        assert np.isfinite(values).all()

    # Head distance is monotonic non-decreasing and reaches full length.
    head = spec.channels["head"]
    assert np.all(np.diff(head) >= -1e-6)
    assert abs(head[-1] - track.length_m) < 1.0
    # The distance counter lands on the catalog distance, not the GPS length.
    assert abs(spec.channels["km"][-1] - 60.0) < 1e-6
    # Relief gets exaggerated, then shading follows it; tags carry a placement.
    assert spec.camera.terrain.max() >= 1.25
    assert spec.camera.shade.max() > 1.5
    for climb in spec.story["climbs"]:
        assert climb["tagDir"] in {"up", "left", "right"}

    # Bearing rate: gentle while chasing (counters on screen), a wider but
    # bounded sweep for the orbit down to the level side view.
    bearing_step = np.abs((np.diff(spec.camera.bearing) + 540.0) % 360.0 - 180.0)
    chasing = spec.channels["counters"][1:] > 0.5
    assert float(bearing_step[chasing].max()) <= (MAX_BEARING_RATE_DEG_S / spec.fps) + 1e-3
    assert float(bearing_step.max()) <= (SIDE_ORBIT_RATE_DEG_S / spec.fps) + 1e-3
    # The ending is level (side view) and the route fully unfolds.
    assert spec.camera.pitch.max() >= 80.0
    assert spec.channels["unfold"][-1] == pytest.approx(1.0)

    # Camera never freezes completely in the middle of the film.
    cx, cy = local_xy(spec.camera.lon, spec.camera.lat, (7.77, 49.44))
    cam_motion = (
        np.hypot(np.diff(cx), np.diff(cy))
        + np.abs(np.diff(spec.camera.zoom)) * 500.0
        + bearing_step * 50.0
        + np.abs(np.diff(spec.camera.map_opacity)) * 500.0
    )
    mid_motion = cam_motion[int(frames * 0.08) : int(frames * 0.90)]
    # Rolling 10-frame window always has positive camera or stage motion.
    window_motion = np.convolve(mid_motion, np.ones(10), mode="valid")
    assert float(window_motion.min()) > 0.05

    # Eye is strictly above the terrain whenever 3D relief is active.
    active = (spec.camera.terrain > 0.05) & (spec.camera.pitch > 5.0)
    dx, dy, dz = eye_offset(
        spec.camera.zoom,
        spec.camera.pitch,
        spec.camera.bearing,
        spec.camera.lat,
        float(spec.height),
    )
    eye_lon, eye_lat = from_local_xy(cx + dx, cy + dy, (7.77, 49.44))
    eye_ground = sampler.sample(eye_lon, eye_lat) * spec.camera.terrain
    eye_z = spec.camera.elevation + dz
    assert np.all(eye_z[active] >= eye_ground[active])


@pytest.mark.parametrize(
    ("length_km", "max_climb_m", "with_nan", "width", "height"),
    [
        (25.0, 0.0, False, 1920, 1080),
        (30.0, 200.0, True, 1920, 1080),
        (300.0, 1200.0, False, 1920, 1080),
        (45.0, 350.0, False, 1080, 1920),
    ],
)
def test_flyover_edge_cases_flat_nan_long_and_portrait(
    length_km: float,
    max_climb_m: float,
    with_nan: bool,
    width: int,
    height: int,
    tmp_path: Path,
) -> None:
    track = _synthetic_ride(length_km=length_km, max_climb_m=max_climb_m, with_nan_alt=with_nan)
    spec = build_flyover_spec(
        track,
        sampler=_FakeSampler(250.0),
        width=width,
        height=height,
        fps=30,
        places_cache_dir=tmp_path,
        offline=True,
    )
    spec.validate()
    assert spec.width == width
    assert spec.height == height
    assert len(spec.story["profile"]) == 600


def test_flyover_rejects_route_shorter_than_500m() -> None:
    short = RideTrack.from_arrays(np.array([7.77, 7.771]), np.array([49.44, 49.441]), np.array([200.0, 201.0]))
    with pytest.raises(ValueError, match="too short"):
        build_flyover_spec(short, offline=True)


def test_places_gazetteer_and_stretch_over_earth_circumference(tmp_path: Path) -> None:
    gazetteer = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [7.769, 49.444]},
                "properties": {"name": "Kaiserslautern", "nameascii": "Kaiserslautern", "adm0name": "Germany", "pop_max": 100000, "scalerank": 6},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-9.139, 38.722]},
                "properties": {"name": "Lisbon", "nameascii": "Lisbon", "adm0name": "Portugal", "pop_max": 2800000, "scalerank": 2},
            },
        ],
    }
    (tmp_path / "ne_10m_populated_places_simple.geojson").write_text(
        json.dumps(gazetteer), encoding="utf-8"
    )
    near = nearest_place(7.77, 49.44, max_distance_km=30.0, cache_dir=tmp_path, offline=True)
    assert near is not None and near.place.name == "Kaiserslautern"

    by_name = destination_for_distance(7.77, 49.44, 1_800_000.0, toward="Lisbon", cache_dir=tmp_path, offline=True)
    assert by_name is not None and by_name.place.name == "Lisbon"

    by_coords = destination_for_distance(7.77, 49.44, 1_800_000.0, toward="38.72,-9.14", cache_dir=tmp_path, offline=True)
    assert by_coords is not None and by_coords.place.name == "Lisbon"

    # Total > Earth's circumference (45,000 km) uses Earth laps copy and no destination.
    ride = _synthetic_ride(length_km=100.0, max_climb_m=100.0)
    huge_rides = [
        SceneRide(
            activity_id=i,
            start_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            track=RideTrack(ride.lon, ride.lat, ride.alt, ride.dist * 225.0, ride.elapsed),
            distance_m=22_500_000.0,
        )
        for i in range(2)
    ]
    spec = build_stretch_spec(
        huge_rides,
        locale="pt-BR",
        fps=30,
        places_cache_dir=tmp_path,
        offline=True,
    )
    spec.validate()
    assert spec.story["destination"] is None
    assert "Terra" in spec.story["ending"]["text"]


def _geonames_row(name: str, lat: float, lon: float, code: str, pop: int) -> str:
    cols = ["1", name, name, "", str(lat), str(lon), "P", code, "XX", "", "", "", "", "", str(pop), "", "0", "UTC", "2026-01-01"]
    return "\t".join(cols)


def test_nearest_place_prefers_geonames_towns_over_districts(tmp_path: Path) -> None:
    rows = [
        _geonames_row("Metropolis", 0.0, 0.0, "PPLC", 5_000_000),
        _geonames_row("Old Quarter", 0.0, 0.004, "PPLX", 90_000),
        _geonames_row("Inner District", 0.0, 0.002, "PPLA3", 30_000),
        _geonames_row("Smalltown", 0.0, 0.12, "PPL", 16_000),
    ]
    (tmp_path / "cities15000.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

    centre = nearest_place(0.003, 0.0, max_distance_km=30.0, cache_dir=tmp_path, offline=True)
    assert centre is not None and centre.place.name == "Metropolis"
    assert centre.place.source == "geonames"

    town = nearest_place(0.12, 0.0, max_distance_km=30.0, cache_dir=tmp_path, offline=True)
    assert town is not None and town.place.name == "Smalltown"

    assert nearest_place(1.0, 0.0, max_distance_km=30.0, cache_dir=tmp_path, offline=True) is None


def test_strata_single_month_and_empty_selection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No valid rides"):
        build_strata_spec([], offline=True)

    ride = _synthetic_ride(length_km=35.0, max_climb_m=150.0)
    single_month = [
        SceneRide(
            activity_id=1,
            start_date=datetime(2026, 8, 10, tzinfo=timezone.utc),
            track=ride,
            distance_m=35_000.0,
            elevation_gain_m=400.0,
            moving_time_s=4_200.0,
        ),
        SceneRide(
            activity_id=2,
            start_date=datetime(2026, 8, 22, tzinfo=timezone.utc),
            track=ride,
            distance_m=35_000.0,
            elevation_gain_m=400.0,
            moving_time_s=4_200.0,
        ),
    ]
    result = build_strata_spec(
        single_month,
        locale="pt-BR",
        fps=30,
        places_cache_dir=tmp_path,
        offline=True,
    )
    result.spec.validate()
    assert len(result.spec.story["floors"]) == 1
    assert result.excluded_rides == 0


def test_home_cluster_picks_densest_region() -> None:
    starts = [(7.77, 49.44), (7.772, 49.441), (7.769, 49.439), (-51.22, -30.03)]
    lon, lat = home_cluster(starts)
    assert abs(lon - 7.77) < 0.05
    assert abs(lat - 49.44) < 0.05


def test_cli_parses_scene3d_and_tiles_commands() -> None:
    parser = build_parser()
    fly = parser.parse_args(["video", "flyover", "19949741255", "--look", "satellite"])
    assert fly.video_type == "flyover"
    assert fly.activity_id == 19949741255
    assert fly.look == "satellite"

    stretch = parser.parse_args(["video", "stretch", "--toward", "Lisbon"])
    assert stretch.video_type == "stretch"
    assert stretch.toward == "Lisbon"

    strata = parser.parse_args(["video", "strata", "--period", "month"])
    assert strata.video_type == "strata"
    assert strata.period == "month"

    tiles = parser.parse_args(["tiles", "serve", "--port", "8795"])
    assert tiles.command == "tiles"
    assert tiles.port == 8795


def test_flyover_chase_stays_close_without_accordion(tmp_path: Path) -> None:
    track = _synthetic_ride(length_km=90.0, max_climb_m=420.0)
    spec = build_flyover_spec(
        track, sampler=_FakeSampler(700.0), fps=30, places_cache_dir=tmp_path, offline=True
    )
    cam = spec.camera
    chase = spec.channels["counters"] > 0.99
    hero = spec.channels["beat"] > 0.001
    # Close enough to read the relief and the progress, never diving past z14.
    assert float(np.median(cam.zoom[chase])) >= 11.8
    assert float(cam.zoom[chase].max()) <= 14.05
    # Outside the hero orbit the chase dollies gently (no dive-in, pull-out).
    steady = chase[1:] & ~hero[1:]
    assert float(np.abs(np.diff(cam.zoom))[steady].max()) * spec.fps <= MAX_ZOOM_RATE + 0.25
    # The whole film never zooms faster than ~2 levels per second.
    assert float(np.abs(np.diff(cam.zoom)).max()) * spec.fps <= 2.0


def test_flyover_relief_scale_is_constant_while_riding_and_route_is_not_pre_drawn(tmp_path: Path) -> None:
    track = _synthetic_ride(length_km=90.0, max_climb_m=420.0)
    spec = build_flyover_spec(
        track, sampler=_FakeSampler(700.0), fps=30, places_cache_dir=tmp_path, offline=True
    )
    riding = spec.channels["counters"] > 0.99
    terrain = spec.camera.terrain[riding]
    # Mountains never stretch or shrink during the ride: only the camera moves.
    assert float(terrain.max() - terrain.min()) <= 1e-6
    assert float(terrain.min()) > 0.5
    # No channel draws the route ahead of the head; the opening has no head yet.
    assert "trace" not in spec.channels and "routeAlpha" not in spec.channels
    assert float(spec.channels["head"][0]) == 0.0


def _monthly_rides(months: int) -> list[SceneRide]:
    rides = []
    for k in range(months):
        track = _synthetic_ride(length_km=30.0 + 10.0 * k, max_climb_m=200.0)
        rides.append(
            SceneRide(
                activity_id=k + 1,
                start_date=datetime(2026, k + 1, 12, tzinfo=timezone.utc),
                track=track,
                distance_m=track.length_m,
                elevation_gain_m=300.0,
                moving_time_s=3_600.0,
            )
        )
    return rides


@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1080, 1920)])
def test_strata_stack_fills_the_frame_and_camera_only_backs_off(width: int, height: int, tmp_path: Path) -> None:
    spec = build_strata_spec(
        _monthly_rides(8), width=width, height=height, fps=30, places_cache_dir=tmp_path, offline=True
    ).spec
    cam = spec.camera
    peak = int(np.argmax(cam.zoom))
    assert np.all(np.diff(cam.zoom[peak:]) <= 1e-9)
    # The finished stack: inside the frame, clear of the totals, and filling it.
    origin = (float(cam.lon[-1]), float(cam.lat[-1]))
    corners = np.array(spec.story["corners"], dtype=float)
    kx, ky = local_xy(corners[:, 0], corners[:, 1], origin)
    top = max(float(f["targetLift"]) for f in spec.story["floors"])
    sx, sy, ok = project_points(
        0.0, 0.0, float(cam.elevation[-1]), float(cam.zoom[-1]), float(cam.pitch[-1]), float(cam.bearing[-1]),
        origin[1], width, height, np.tile(kx, 2), np.tile(ky, 2), np.repeat([0.0, top], 4),
    )
    assert ok.all()
    assert sx.min() >= 0.0 and sx.max() <= width
    assert sy.min() >= 0.04 * height and sy.max() <= 0.82 * height
    assert max((sx.max() - sx.min()) / width, (sy.max() - sy.min()) / height) > 0.55


def test_stretch_line_accelerates_smoothly_and_keeps_true_boundaries(tmp_path: Path) -> None:
    rides = _monthly_rides(12)
    spec = build_stretch_spec(rides, fps=30, places_cache_dir=tmp_path, offline=True)
    laid = spec.channels["laid"]
    assert np.all(np.diff(laid) >= -1e-6)
    assert laid[-1] == pytest.approx(spec.story["totalM"], rel=1e-3)
    moving = np.flatnonzero(np.diff(laid) > 1e-3)
    speed = np.diff(laid)[moving[0] : moving[-1]]
    # One accelerating pull: speed rises (in log space at a steady rate) up to
    # the soft landing, with no ride-by-ride stalls.
    peak = int(np.argmax(speed))
    assert peak > 0.6 * len(speed)
    rising = np.diff(np.log(speed[int(0.1 * peak) : peak]))
    assert np.all(rising > -1e-3)
    assert float(np.abs(np.diff(spec.camera.zoom)).max()) * spec.fps <= 1.5
    # Each boundary marker is a real ride length: the cumulative sums line up.
    rides_meta = spec.story["rides"]
    for prev, cur in zip(rides_meta, rides_meta[1:], strict=False):
        assert cur["beforeM"] == pytest.approx(prev["beforeM"] + prev["lengthM"], abs=0.2)


def test_stretch_draws_and_consumes_every_ride_including_far_ones(tmp_path: Path) -> None:
    rides = _monthly_rides(6)
    for k in range(3):
        base = _synthetic_ride(length_km=70.0 + 5.0 * k, max_climb_m=100.0)
        far = RideTrack.from_arrays(base.lon + 9.0 + k, base.lat + 2.0, base.alt, base.dist / 8.0)
        rides.append(
            SceneRide(
                activity_id=100 + k,
                start_date=datetime(2026, 7, 1 + k, tzinfo=timezone.utc),
                track=far,
                distance_m=far.length_m,
            )
        )
    spec = build_stretch_spec(rides, fps=30, places_cache_dir=tmp_path, offline=True)
    meta = spec.story["rides"]
    assert len(meta) == len(rides)
    assert all(m["trackIndex"] >= 0 for m in meta)
    assert len(spec.tracks) == len(rides)
    assert sum(m["lengthM"] for m in meta) == pytest.approx(spec.story["totalM"], rel=1e-3)
    assert meta[-1]["beforeM"] + meta[-1]["lengthM"] == pytest.approx(spec.story["totalM"], rel=1e-3)


def test_flyover_live_climb_readout_follows_long_climbs_only(tmp_path: Path) -> None:
    # Short enough that the hill is a real climb (~5% at its steepest).
    track = _synthetic_ride(length_km=30.0, max_climb_m=420.0)
    spec = build_flyover_spec(track, sampler=_FakeSampler(700.0), fps=30, places_cache_dir=tmp_path, offline=True)
    climbs = spec.story["climbs"]
    assert any(c["readout"] for c in climbs)
    head = spec.channels["head"]
    for k, climb in enumerate(climbs):
        assert len(climb["profile"]) > 2 and min(climb["profile"]) == 0.0 and max(climb["profile"]) == 1.0
        if not climb["readout"]:
            assert f"readout{k}" not in spec.channels
            continue
        shown = spec.channels[f"readout{k}"] > 0.5
        # On screen while the head is on the climb, never before its foot.
        assert float(head[shown].min()) >= climb["startM"] - 2_000.0
        assert float(head[shown].max()) <= climb["endM"] + 1.0
    # The readout box is the one tags keep out of, clear of the counters below it.
    layout = spec.story["layout"]
    x0, y0, x1, y1 = layout["readout"]["box"]
    assert layout["topY"] <= y0 < layout["readout"]["stripTop"] < layout["readout"]["stripBottom"] < y1
    assert x1 <= spec.width - layout["marginX"] + 0.5 and y1 < layout["bottomY"]
    # Grade is a sign's grade: bounded and smooth, never metre-by-metre noise.
    grade = spec.channels["grade"]
    assert float(np.abs(grade).max()) < 25.0
    assert float(np.abs(np.diff(grade)).max()) < 1.0


def test_hero_view_rises_above_a_ridge_that_would_hide_the_climb() -> None:
    from ride_visuals.scene3d.flyover import HERO_PITCH, HERO_PITCHES, _hero_view

    # A straight 3 km climb heading east (start left, summit right from the south).
    px = np.linspace(-1_500.0, 1_500.0, 120)
    py = np.zeros_like(px)
    pz = np.linspace(200.0, 500.0, 120)
    centre = (0.0, 0.0, 350.0)
    args = (px, py, pz, centre, 1.5)
    tail = (49.4, 1920, 1080, 3_000.0)
    flat = _hero_view(*args, lambda x, y: np.full(np.shape(x), 150.0), *tail)
    assert flat.pitch == HERO_PITCH and flat.hidden == 0.0
    # A wall just in front of the road hides it from every low, oblique view.
    def walled(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        r = np.hypot(x, y)
        return np.where((r > 2_400.0) & (r < 2_700.0), 900.0, 150.0)

    view = _hero_view(*args, walled, *tail)
    assert view.pitch < HERO_PITCH and view.pitch in HERO_PITCHES
    assert view.hidden < 0.05
    # Without relief data the default three-quarter view is kept.
    assert _hero_view(*args, None, *tail).pitch == HERO_PITCH


def test_relief_is_locked_to_one_dem_level_while_the_camera_zooms() -> None:
    from ride_visuals.scene3d.camera import CameraTrack
    from ride_visuals.scene3d.spec import relief_max_zoom
    from ride_visuals.scene3d.tiles import TILE_SOURCES

    cam = CameraTrack(100)
    cam.zoom = np.linspace(12.05, 14.0, 100)
    cam.terrain[:] = 1.5
    # DEM tiles load two levels above the map zoom: z14 serves all of 12..14.
    assert relief_max_zoom(cam) == 14
    # A brief establishing shot further out does not drag the whole film down.
    cam.zoom[:5] = 10.9
    assert relief_max_zoom(cam) == 14
    # Without relief on screen the source keeps its full depth.
    cam.terrain[:] = 0.0
    assert relief_max_zoom(cam) == TILE_SOURCES["dem"].max_zoom
