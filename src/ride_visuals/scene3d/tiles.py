"""World-wide map tiles for the 3D scenes: a disk cache and a local server.

Three open sources cover the whole planet:

- relief: Terrarium-encoded elevation from the Mapzen Terrain Tiles on AWS Open
  Data (~30 m globally, finer where national datasets exist), up to z15;
- cartography: OpenFreeMap vector tiles (OpenStreetMap, OpenMapTiles schema);
- imagery (optional): the same Esri World Imagery the 2D maps use.

The renderer never sees upstream URLs. During a render a small threaded HTTP
server on 127.0.0.1 answers tile requests from the cache and downloads what is
missing on first use, so a re-render is offline and every tile is fetched once.
It also serves the scene spec, which keeps large JSON out of Remotion props.
"""

from __future__ import annotations

import gzip
import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ride_visuals.maps.tiles import TILE_PROVIDERS

USER_AGENT = "RideVisuals/0.1 (+https://github.com/HenriqueLindemann/ride-visuals)"
OPENFREEMAP_TILEJSON = "https://tiles.openfreemap.org/planet"


@dataclass(frozen=True)
class TileSource:
    """An upstream tile service as the 3D scenes use it."""

    key: str
    #: URL template with {z}/{x}/{y}; None when resolved at runtime.
    url: str | None
    ext: str
    max_zoom: int
    cache_key: str
    content_type: str
    #: Credited data sources (keys of ride_visuals.credits.SOURCES).
    credits: tuple[str, ...]


TILE_SOURCES: dict[str, TileSource] = {
    "dem": TileSource(
        key="dem",
        url="https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
        ext="png",
        max_zoom=15,
        cache_key="terrarium-aws-v1",
        content_type="image/png",
        credits=("terrain-tiles",),
    ),
    "vector": TileSource(
        key="vector",
        url=None,
        ext="pbf",
        max_zoom=14,
        cache_key="openfreemap-planet-v1",
        content_type="application/x-protobuf",
        credits=("openfreemap",),
    ),
    "satellite": TileSource(
        key="satellite",
        url=TILE_PROVIDERS["satellite"]["url"],
        ext="jpg",
        max_zoom=17,
        # Shared with the 2D basemaps, so imagery is never downloaded twice.
        cache_key=TILE_PROVIDERS["satellite"]["cache_key"],
        content_type="image/jpeg",
        credits=tuple(TILE_PROVIDERS["satellite"]["sources"]),
    ),
}


class TileCache:
    """Tiles on disk under ``<root>/<cache_key>/<z>/<x>_<y>.<ext>``.

    An empty file marks a tile the upstream does not have (open ocean in a
    vector set, for example), so it is not requested again.
    """

    def __init__(self, root: Path = Path("data/cache/tiles"), *, offline: bool = False) -> None:
        self.root = Path(root)
        self.offline = offline
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        # Be polite to volunteer-run services: a handful of downloads at a time.
        self._upstream = threading.BoundedSemaphore(8)
        self._vector_template: str | None = None

    def path(self, source: TileSource, z: int, x: int, y: int) -> Path:
        return self.root / source.cache_key / str(z) / f"{x}_{y}.{source.ext}"

    def _lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def template(self, source: TileSource) -> str:
        if source.url is not None:
            return source.url
        if self._vector_template is None:
            self._vector_template = self._resolve_openfreemap()
        return self._vector_template

    def _resolve_openfreemap(self) -> str:
        """The planet build changes weekly; remember the last one for offline use."""
        remembered = self.root / TILE_SOURCES["vector"].cache_key / "template.txt"
        if not self.offline:
            try:
                request = urllib.request.Request(OPENFREEMAP_TILEJSON, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=20) as response:
                    template = json.load(response)["tiles"][0]
                remembered.parent.mkdir(parents=True, exist_ok=True)
                remembered.write_text(template, encoding="utf-8")
                return template
            except (OSError, ValueError, KeyError, IndexError):
                pass
        if remembered.exists():
            return remembered.read_text(encoding="utf-8").strip()
        raise RuntimeError("OpenFreeMap tiles are unavailable (offline and never fetched before)")

    def get(self, source: TileSource, z: int, x: int, y: int) -> bytes | None:
        """Tile bytes from the cache or upstream; b"" for a known-empty tile, None on failure."""
        if not (0 <= z <= source.max_zoom and 0 <= x < 2**z and 0 <= y < 2**z):
            return None
        target = self.path(source, z, x, y)
        if target.exists():
            return target.read_bytes()
        if self.offline:
            return None
        with self._lock(str(target)):
            if target.exists():
                return target.read_bytes()
            data = self._download(source, z, x, y)
            if data is None:
                return None
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(target.suffix + ".part")
            partial.write_bytes(data)
            partial.replace(target)
            return data

    def _download(self, source: TileSource, z: int, x: int, y: int) -> bytes | None:
        url = self.template(source).format(z=z, x=x, y=y)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(4):
            try:
                with self._upstream, urllib.request.urlopen(request, timeout=30) as response:
                    data = response.read()
                if data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                return data
            except urllib.error.HTTPError as error:
                if error.code in (HTTPStatus.NOT_FOUND, HTTPStatus.NO_CONTENT):
                    return b""
                time.sleep(1.0 * (attempt + 1))
            except OSError:
                time.sleep(1.0 * (attempt + 1))
        return None


class _Handler(BaseHTTPRequestHandler):
    server: TileServer.HTTPServer  # type: ignore[name-defined]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        return

    def _send(self, status: int, body: bytes = b"", content_type: str = "application/octet-stream") -> None:
        self.send_response(status)
        # The Remotion page is served from another local port.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "max-age=31536000")
        if body:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib naming
        self._send(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        if len(parts) == 2 and parts[0] == "files":
            path = self.server.files.get(parts[1])
            if path is None or not path.exists():
                return self._send(HTTPStatus.NOT_FOUND)
            return self._send(HTTPStatus.OK, path.read_bytes(), "application/json")
        if len(parts) == 5 and parts[0] == "tiles" and parts[1] in TILE_SOURCES:
            source = TILE_SOURCES[parts[1]]
            try:
                z, x = int(parts[2]), int(parts[3])
                y = int(parts[4].split(".", 1)[0])
            except ValueError:
                return self._send(HTTPStatus.BAD_REQUEST)
            data = self.server.cache.get(source, z, x, y)
            if data is None:
                self.server.failures += 1
                return self._send(HTTPStatus.NOT_FOUND)
            if not data:
                return self._send(HTTPStatus.NO_CONTENT)
            return self._send(HTTPStatus.OK, data, source.content_type)
        return self._send(HTTPStatus.NOT_FOUND)


class TileServer:
    """Serves cached tiles and registered files on 127.0.0.1 while a render runs."""

    class HTTPServer(ThreadingHTTPServer):
        daemon_threads = True

        def __init__(self, cache: TileCache, port: int = 0) -> None:
            super().__init__(("127.0.0.1", port), _Handler)
            self.cache = cache
            self.files: dict[str, Path] = {}
            self.failures = 0

        def handle_error(self, request: object, client_address: object) -> None:
            # MapLibre aborts tile requests it no longer needs; that is not an error.
            if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
                return
            super().handle_error(request, client_address)  # type: ignore[arg-type]

    def __init__(self, cache: TileCache, *, port: int = 0) -> None:
        """Port 0 picks a free port; `tiles serve` passes a fixed one for Remotion Studio."""
        self.cache = cache
        self._httpd = TileServer.HTTPServer(cache, port)
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def failures(self) -> int:
        """Tiles that could not be served (upstream down while not cached)."""
        return self._httpd.failures

    def tile_url(self, key: str) -> str:
        source = TILE_SOURCES[key]
        return f"{self.base_url}/tiles/{key}/{{z}}/{{x}}/{{y}}.{source.ext}"

    def publish(self, name: str, path: Path) -> str:
        """Expose a local file at /files/<name> and return its URL."""
        self._httpd.files[name] = Path(path)
        return f"{self.base_url}/files/{name}"

    def start(self) -> TileServer:
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="tile-server", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self) -> TileServer:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.stop()


def stage_scene3d_assets(renderer_dir: Path) -> None:
    """Copy the MapLibre worker and the Geist font into the renderer's public dir.

    Both ship in node_modules but cannot be imported through the bundle (the
    ESM worker resolves siblings at runtime; geist does not export its files).
    """
    modules = Path(renderer_dir) / "node_modules"
    target = Path(renderer_dir) / "public" / "scene3d"
    target.mkdir(parents=True, exist_ok=True)
    assets: dict[str, Callable[[], Path]] = {
        "maplibre-gl-worker.mjs": lambda: modules / "maplibre-gl" / "dist" / "maplibre-gl-worker.mjs",
        "maplibre-gl-shared.mjs": lambda: modules / "maplibre-gl" / "dist" / "maplibre-gl-shared.mjs",
        "Geist-Variable.woff2": lambda: modules / "geist" / "dist" / "fonts" / "geist-sans" / "Geist-Variable.woff2",
    }
    for name, source in assets.items():
        origin = source()
        if not origin.exists():
            raise FileNotFoundError(
                f"Renderer dependency missing: {origin}. Run: npm --prefix '{renderer_dir}' ci --no-bin-links"
            )
        destination = target / name
        if not destination.exists() or destination.stat().st_size != origin.stat().st_size:
            shutil.copyfile(origin, destination)
