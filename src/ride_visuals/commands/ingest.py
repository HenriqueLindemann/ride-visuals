"""Activity ingestion command."""

from __future__ import annotations

import argparse

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments, print_ingest_stats
from ride_visuals.selection import ActivitySelection


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("ingest", help="Ingestão lossless de atividades")
    add_selection_arguments(parser)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ingere todas as atividades do arquivo ignorando filtros temporais",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Limpa o catálogo DuckDB e streams antes de iniciar a ingestão",
    )
    parser.add_argument(
        "--activity-type",
        action="append",
        help="Activity type to ingest; repeat to select several",
    )
    parser.add_argument("--bulk-dir", type=str, help="Caminho para o diretório bulk_download")
    parser.add_argument("--catalog-db", type=str, help="Caminho para o DuckDB de catálogo")
    parser.add_argument("--streams-dir", type=str, help="Caminho para pasta de Parquet streams")
    parser.add_argument("--config", type=str, help="Caminho para config/config.toml")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Executa a ingestão lossless de dados para DuckDB + Parquet."""
    from ride_visuals.ingest.pipeline import IngestPipeline

    runtime = RuntimeConfig.from_args(args)
    selection = ActivitySelection() if args.all else runtime.selection

    print(f"[Ingestão] Seleção: {selection.describe()}")
    print(f"  Fonte: {runtime.bulk_dir}")
    print(f"  Catálogo DuckDB: {runtime.catalog_db}")
    print(f"  Streams Parquet: {runtime.streams_dir}")
    if args.clean:
        print("  Modo: Limpeza total e reconstrução (--clean)")

    pipeline = IngestPipeline(
        bulk_dir=runtime.bulk_dir,
        catalog_db_path=runtime.catalog_db,
        streams_dir=runtime.streams_dir,
        selection=selection,
        activity_types=runtime.activity_types,
        clean=args.clean,
    )
    stats = pipeline.run_ingest()
    print_ingest_stats(stats)
