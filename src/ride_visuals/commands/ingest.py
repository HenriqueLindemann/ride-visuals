"""Activity ingestion command."""

from __future__ import annotations

import argparse

from ride_visuals.commands.common import RuntimeConfig, add_selection_arguments, print_ingest_stats
from ride_visuals.selection import ActivitySelection


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("ingest", help="Lossless ingestion of activities")
    add_selection_arguments(parser)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ingest every activity in the export, ignoring time filters",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Wipe the DuckDB catalog and streams before ingesting",
    )
    parser.add_argument(
        "--activity-type",
        action="append",
        help="Activity type to ingest; repeat to select several",
    )
    parser.add_argument("--bulk-dir", type=str, help="Path to the bulk_download directory")
    parser.add_argument("--catalog-db", type=str, help="Path to the catalog DuckDB")
    parser.add_argument("--streams-dir", type=str, help="Path to the Parquet streams directory")
    parser.add_argument("--config", type=str, help="Path to config/config.toml")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Run lossless ingestion into DuckDB + Parquet."""
    from ride_visuals.ingest.pipeline import IngestPipeline

    runtime = RuntimeConfig.from_args(args)
    selection = ActivitySelection() if args.all else runtime.selection

    print(f"[Ingest] Selection: {selection.describe()}")
    print(f"  Source: {runtime.bulk_dir}")
    print(f"  DuckDB catalog: {runtime.catalog_db}")
    print(f"  Parquet streams: {runtime.streams_dir}")
    if args.clean:
        print("  Mode: full wipe and rebuild (--clean)")

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
