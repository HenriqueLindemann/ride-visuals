"""Map rendering command."""

from __future__ import annotations

import argparse

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments
from ride_visuals.commands.options import LOCALES, MAP_DETAILS, MAP_ROUTE_STYLES, THEMES


def register(subparsers: argparse._SubParsersAction) -> None:
    from ride_visuals.maps.tiles import TILE_PROVIDERS

    parser = subparsers.add_parser("map", help="Gera mapas cartográficos e heatmaps")
    parser.add_argument("map_type", choices=["overview", "heatmap", "effort"], help="Tipo de mapa")
    add_selection_arguments(parser)
    parser.add_argument(
        "--basemap",
        choices=["plain", *TILE_PROVIDERS],
        default="dark",
        help="Provedor de mapa base",
    )
    parser.add_argument("--dpi", type=int, default=300, help="Resolução DPI da imagem")
    parser.add_argument(
        "--map-detail",
        choices=MAP_DETAILS,
        default="standard",
        help="Tiles padrão ou uma camada extra de resolução antes do downsample",
    )
    parser.add_argument(
        "--route-style",
        choices=MAP_ROUTE_STYLES,
        default="orange",
        help="Paleta aplicada somente aos traçados",
    )
    parser.add_argument("--locale", choices=LOCALES, help="Idioma do conteúdo visual")
    parser.add_argument("--theme", choices=THEMES, help="Tema editorial compartilhado")
    parser.add_argument("--catalog-db", type=str, help="Caminho para o DuckDB de catálogo")
    parser.add_argument("--streams-dir", type=str, help="Caminho para pasta de Parquet streams")
    parser.add_argument("--outputs-dir", type=str, help="Caminho para pasta de saídas")
    parser.add_argument("--config", type=str, help="Caminho para config/config.toml")
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
            f"[Mapa] Visão geral ({runtime.selection.describe()}, {args.dpi} DPI, "
            f"basemap: {args.basemap})..."
        )
        output = generator.render_overview(
            dpi=args.dpi,
            basemap=args.basemap,
            route_style=args.route_style,
            map_detail=args.map_detail,
        )
    elif args.map_type == "heatmap":
        print(f"[Mapa] Densidade ({runtime.selection.describe()}, basemap: {args.basemap})...")
        output = generator.render_heatmap(
            dpi=args.dpi,
            basemap=args.basemap,
            route_style=args.route_style,
            map_detail=args.map_detail,
        )
    else:
        print(f"[Mapa] Gerando mapa do espectro cardiovascular (Z1 a Z5, basemap: {args.basemap})...")
        output = generator.render_effort_map(
            dpi=args.dpi,
            basemap=args.basemap,
            map_detail=args.map_detail,
        )
    print(f"[Mapa] Salvo com sucesso em: {output}")
