"""Activity ingestion command."""

from __future__ import annotations

import argparse

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments
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

    print("\n==================================================")
    print(" Ingestão Concluída com Sucesso!")
    print("==================================================")
    print(f"  Atividades no recorte:        {stats['total_scoped']}")
    print(f"  Atividades salvas:            {stats['ingested_activities']}")
    print(f"  Total de pontos de telemetria:{stats['total_points']:,}")
    print(
        "  Arquivos originais:           "
        f"{stats['fit_count']} FIT · {stats['tcx_count']} TCX · {stats['gpx_count']} GPX"
    )
    print(f"  Streams com Frequência Card.: {stats['with_hr_stream']}/{stats['ingested_activities']}")
    print(f"  Streams com Velocidade expl.: {stats['with_speed_stream']}/{stats['ingested_activities']}")
    print(f"  Streams com Temperatura:      {stats['with_temp_stream']}/{stats['ingested_activities']}")
    print(f"  Streams com Watts estimados:  {stats['with_watts_stream']}/{stats['ingested_activities']}")
    print(f"  Distância total acumulada:    {stats['total_distance_m'] / 1000.0:.1f} km")
    print(f"  Altimetria acumulada:         {stats['total_elevation_m']:.0f} m")
    print("==================================================")
