"""Catalog and stream audit command."""

from __future__ import annotations

import argparse

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("audit", help="Audit data and telemetry coverage")
    parser.add_argument("--catalog-db", type=str, help="Path to the catalog DuckDB")
    parser.add_argument("--streams-dir", type=str, help="Path to the Parquet streams directory")
    parser.add_argument("--config", type=str, help="Path to config/config.toml")
    add_selection_arguments(parser)
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Audit metric coverage, divergences, and hashes."""
    from ride_visuals.validate.audit import ActivityAuditor

    runtime = RuntimeConfig.from_args(args)
    auditor = ActivityAuditor(runtime.catalog_db, runtime.streams_dir, selection=runtime.selection)
    result = auditor.run_audit()

    print("==================================================")
    print(f" Ride Visuals — Data audit ({runtime.selection.describe()})")
    print("==================================================")
    print(f"  Total rides:                  {result['total_activities']}")
    print(f"  Period analyzed:              {result['period_min']} to {result['period_max']}")
    print(f"  Total distance:               {result['total_distance_km']:.1f} km")
    print(f"  Total elevation gain:         {result['total_elevation_m']:.0f} m")
    print(f"  Original files in catalog:    {result['format_counts']}")
    print(f"  HR in CSV summary:            {result['hr_summary_count']}/{result['total_activities']}")
    print(f"  Point-by-point HR in Parquet: {result['hr_stream_count']}/{result['total_activities']}")
    print(f"  Explicit measured speed:      {result['speed_stream_count']}/{result['total_activities']}")
    print(f"  Sensor temperature:           {result['temp_stream_count']}/{result['total_activities']}")
    print(f"  Watts in streams:             {result['watts_stream_count']}/{result['total_activities']}")
    print("==================================================")
