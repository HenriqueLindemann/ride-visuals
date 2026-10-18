"""Local tile and scene-spec server command for Remotion Studio."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from ride_visuals.commands.common import RuntimeConfig


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "tiles",
        help="Serve cached 3D map tiles and scene specs for Remotion Studio",
    )
    tiles_sub = parser.add_subparsers(dest="tiles_command", required=True)
    serve = tiles_sub.add_parser("serve", help="Run the local 127.0.0.1 tile server")
    serve.add_argument("--port", type=int, default=8790, help="Local port (default: 8790)")
    serve.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="Optional scene spec JSON to publish at /files/latest.json",
    )
    serve.add_argument("--offline", action="store_true", help="Serve only already-cached tiles")
    serve.add_argument("--config", type=str, help="Path to config/config.toml")
    serve.set_defaults(func=run_serve)


def run_serve(args: argparse.Namespace) -> None:
    """Stage 3D renderer assets and run the tile server until interrupted."""
    from ride_visuals.scene3d.tiles import TileCache, TileServer, stage_scene3d_assets
    from ride_visuals.video.engines.remotion import _resolve_renderer_dir

    runtime = RuntimeConfig.from_args(args)
    renderer_dir = _resolve_renderer_dir(runtime.renderer_dir)
    stage_scene3d_assets(renderer_dir)
    cache = TileCache(offline=args.offline)
    with TileServer(cache, port=args.port) as server:
        if args.spec is not None:
            spec_path = Path(args.spec).resolve()
            if not spec_path.exists():
                raise FileNotFoundError(f"Scene spec not found: {spec_path}")
            url = server.publish("latest.json", spec_path)
            print(f"[Tiles] Published spec: {url}")
        print(f"[Tiles] Serving 3D tiles at {server.base_url} (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[Tiles] Stopping server.")
