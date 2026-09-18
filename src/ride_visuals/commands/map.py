"""Map rendering command."""

from __future__ import annotations

import argparse

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments
from ride_visuals.commands.options import LOCALES, MAP_DETAILS, MAP_ROUTE_STYLES, THEMES


def register(subparsers: argparse._SubParsersAction) -> None:
    from ride_visuals.maps.tiles import TILE_PROVIDERS

    parser = subparsers.add_parser("map", help="Render cartographic maps and heatmaps")
    parser.add_argument("map_type", choices=["overview", "heatmap", "effort"], help="Map type")
    add_selection_arguments(parser)
    parser.add_argument(
        "--basemap",
        choices=["plain", *TILE_PROVIDERS],
        default="dark",
        help="Basemap provider",
    )
    parser.add_argument("--dpi", type=int, default=300, help="Image resolution in DPI")
    parser.add_argument(
        "--map-detail",
        choices=MAP_DETAILS,
        default="standard",
        help="Standard tiles or an extra resolution layer before downsampling",
    )
    parser.add_argument(
        "--route-style",
        choices=MAP_ROUTE_STYLES,
        default="orange",
        help="Palette applied only to the route traces",
    )
    parser.add_argument("--locale", choices=LOCALES, help="Visual language for generated media")
    parser.add_argument("--theme", choices=THEMES, help="Shared editorial theme")
    parser.add_argument("--catalog-db", type=str, help="Path to the catalog DuckDB")
    parser.add_argument("--streams-dir", type=str, help="Path to the Parquet streams directory")
    parser.add_argument("--outputs-dir", type=str, help="Path to the outputs directory")
    parser.add_argument("--config", type=str, help="Path to config/config.toml")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Render maps for the selected activities."""
    from ride_visuals.maps.generator import MapGenerator

    runtime = RuntimeConfig.from_args(args)
    generator = MapGenerator(
        catalog_db_path=runtime.catalog_db,
        streams_dir=runtime.streams_dir,
        outputs_dir=runtime.outputs_dir / "maps",
        locale=runtime.locale,
        theme=runtime.theme,
        selection=runtime.selection,
    )

    if args.map_type == "overview":
        print(
            f"[Map] Overview ({runtime.selection.describe()}, {args.dpi} DPI, "
            f"basemap: {args.basemap})..."
        )
        output = generator.render_overview(
            dpi=args.dpi,
            basemap=args.basemap,
            route_style=args.route_style,
            map_detail=args.map_detail,
        )
    elif args.map_type == "heatmap":
        print(f"[Map] Density ({runtime.selection.describe()}, basemap: {args.basemap})...")
        output = generator.render_heatmap(
            dpi=args.dpi,
            basemap=args.basemap,
            route_style=args.route_style,
            map_detail=args.map_detail,
        )
    else:
        print(f"[Map] Rendering heart-rate effort map (Z1 to Z5, basemap: {args.basemap})...")
        output = generator.render_effort_map(
            dpi=args.dpi,
            basemap=args.basemap,
            map_detail=args.map_detail,
        )
    print(f"[Map] Saved successfully to: {output}")
