"""Top-level CLI parser construction."""

from __future__ import annotations

import argparse

from ride_visuals.commands import audit, doctor, ingest, ingest_fit, map, report, validation, video


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ride Visuals CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (doctor, ingest, ingest_fit, audit, map, video, report, validation):
        command.register(subparsers)
    return parser
