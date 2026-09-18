"""Import standalone FIT files into the collection."""

from __future__ import annotations

import argparse
from pathlib import Path

from ride_visuals.commands.common import RuntimeConfig, print_ingest_stats


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "ingest-fit",
        help="Import standalone FIT files into the collection",
        description=(
            "Copy standalone .fit/.fit.gz files into the export and record them "
            "in activities.csv, then ingest only the new activities. "
            "Useful for activities recorded outside Strava or downloaded "
            "individually."
        ),
    )
    parser.add_argument("files", nargs="+", help="One or more .fit or .fit.gz files to import")
    parser.add_argument(
        "--name",
        help="Activity name (default: file name); valid for a single file",
    )
    parser.add_argument(
        "--type",
        help="Activity type (default: mapped from the FIT sport field)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without changing any files",
    )
    parser.add_argument("--bulk-dir", type=str, help="Path to the bulk_download directory")
    parser.add_argument("--catalog-db", type=str, help="Path to the catalog DuckDB")
    parser.add_argument("--streams-dir", type=str, help="Path to the Parquet streams directory")
    parser.add_argument("--config", type=str, help="Path to config/config.toml")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Import standalone FIT files and ingest the new activities into the catalog."""
    from ride_visuals.ingest.pipeline import IngestPipeline
    from ride_visuals.ingest.standalone import (
        STATUS_IMPORTED,
        StandaloneFitImporter,
    )

    if args.name and len(args.files) > 1:
        raise SystemExit("--name can only be used with a single file")

    runtime = RuntimeConfig.from_args(args)
    importer = StandaloneFitImporter(
        bulk_dir=runtime.bulk_dir,
        name=args.name,
        activity_type=args.type,
        dry_run=args.dry_run,
    )

    print("[FIT import] File source: user")
    print(f"  Export: {importer.csv_file}")
    print(f"  Activities directory: {importer.activities_dir}")

    labels = {"imported": "Imported", "duplicate": "Duplicate", "error": "Error"}
    results = importer.import_files([Path(f) for f in args.files])
    for result in results:
        print(f"  [{labels[result.status]}] {result.source.name}: {result.message}")

    imported = [r for r in results if r.status == STATUS_IMPORTED]
    if not imported:
        print("\nNothing to ingest; catalog unchanged.")
        return
    if args.dry_run:
        print(f"\n[dry-run] {len(imported)} activity(ies) would be imported. Nothing was changed.")
        return

    # Ensure the newly imported type passes the ingestion filter even
    # outside the configured activity_types.
    imported_types = {r.activity_type for r in imported if r.activity_type}
    activity_types = sorted(set(runtime.activity_types) | imported_types)
    if imported_types - set(runtime.activity_types):
        extra = ", ".join(sorted(imported_types - set(runtime.activity_types)))
        print(f"  Type filter extended to include: {extra}")

    for result in imported:
        if not runtime.selection.matches(result.start_date):
            print(
                f"  [Warning] {result.name} ({result.start_date:%Y-%m-%d}) outside the selected "
                "time range; it will be imported into activities.csv but not into the catalog."
            )

    pipeline = IngestPipeline(
        bulk_dir=runtime.bulk_dir,
        catalog_db_path=runtime.catalog_db,
        streams_dir=runtime.streams_dir,
        selection=runtime.selection,
        activity_types=activity_types,
        only_ids={r.activity_id for r in imported if r.activity_id},
    )
    stats = pipeline.run_ingest()
    print_ingest_stats(stats)
