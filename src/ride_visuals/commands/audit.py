"""Catalog and stream audit command."""

from __future__ import annotations

import argparse

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("audit", help="Audita dados e cobertura de telemetria")
    parser.add_argument("--catalog-db", type=str, help="Caminho para o DuckDB de catálogo")
    parser.add_argument("--streams-dir", type=str, help="Caminho para pasta de Parquet streams")
    parser.add_argument("--config", type=str, help="Caminho para config/config.toml")
    add_selection_arguments(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Audita cobertura de métricas, divergências e hashes."""
    from ride_visuals.validate.audit import ActivityAuditor

    runtime = RuntimeConfig.from_args(args)
    auditor = ActivityAuditor(runtime.catalog_db, runtime.streams_dir, selection=runtime.selection)
    result = auditor.run_audit()

    print("==================================================")
    print(f" Ride Visuals — Data audit ({runtime.selection.describe()})")
    print("==================================================")
    print(f"  Total de pedaladas:           {result['total_activities']}")
    print(f"  Período analisado:            {result['period_min']} a {result['period_max']}")
    print(f"  Distância total acumulada:    {result['total_distance_km']:.1f} km")
    print(f"  Ganho de elevação total:      {result['total_elevation_m']:.0f} m")
    print(f"  Originais no catálogo:        {result['format_counts']}")
    print(f"  FC no resumo CSV:             {result['hr_summary_count']}/{result['total_activities']}")
    print(f"  FC ponto a ponto no Parquet:  {result['hr_stream_count']}/{result['total_activities']}")
    print(f"  Velocidade explícita medida:  {result['speed_stream_count']}/{result['total_activities']}")
    print(f"  Temperatura de sensor:        {result['temp_stream_count']}/{result['total_activities']}")
    print(f"  Watts nos streams:            {result['watts_stream_count']}/{result['total_activities']}")
    print("==================================================")
