"""Shared argument, configuration, and runtime helpers for CLI commands."""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ride_visuals.selection import ActivitySelection

DEFAULT_CONFIG_PATH = Path("config/config.toml")


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load local configuration, preserving the CLI's empty-config fallback."""
    resolved_path = config_path or DEFAULT_CONFIG_PATH
    if not resolved_path.exists():
        return {}
    with resolved_path.open("rb") as config_file:
        return tomllib.load(config_file)


def activity_selection(args: argparse.Namespace, config: dict[str, Any]) -> ActivitySelection:
    """Build the shared temporal selection from CLI overrides and local config."""
    configured = config.get("selection", {})
    years = getattr(args, "year", None)
    months = getattr(args, "month", None)
    return ActivitySelection.from_values(
        start_date=getattr(args, "start_date", None) or configured.get("start_date"),
        end_date=getattr(args, "end_date", None) or configured.get("end_date"),
        years=years if years is not None else configured.get("years", []),
        months=months if months is not None else configured.get("months", []),
    )


def add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start-date", help="Inclusive ISO date/time, for example 2024-02-01")
    parser.add_argument("--end-date", help="Inclusive ISO date/time, for example 2024-12-31")
    parser.add_argument("--year", type=int, action="append", help="Calendar year; repeat to select several")
    parser.add_argument(
        "--month",
        type=int,
        choices=range(1, 13),
        action="append",
        help="Calendar month (1-12); repeat to select several",
    )


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved configuration shared by command orchestration."""

    raw: dict[str, Any]
    bulk_dir: Path
    catalog_db: Path
    streams_dir: Path
    outputs_dir: Path
    renderer_dir: Path | None
    locale: str
    theme: str
    selection: ActivitySelection
    activity_types: list[str]

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> RuntimeConfig:
        config_arg = getattr(args, "config", None)
        raw = load_config(Path(config_arg) if config_arg else None)
        paths = raw.get("paths", {})
        configured_selection = raw.get("selection", {})
        renderer_dir = paths.get("renderer_dir")
        activity_types = getattr(args, "activity_type", None)
        return cls(
            raw=raw,
            bulk_dir=Path(getattr(args, "bulk_dir", None) or paths.get("bulk_dir", "bulk_download")),
            catalog_db=Path(
                getattr(args, "catalog_db", None)
                or paths.get("catalog_db", "data/catalog/activities.duckdb")
            ),
            streams_dir=Path(
                getattr(args, "streams_dir", None) or paths.get("streams_dir", "data/streams")
            ),
            outputs_dir=Path(getattr(args, "outputs_dir", None) or paths.get("outputs_dir", "outputs")),
            renderer_dir=Path(renderer_dir) if renderer_dir else None,
            locale=getattr(args, "locale", None) or raw.get("app", {}).get("locale", "pt-BR"),
            theme=getattr(args, "theme", None) or raw.get("video", {}).get("theme", "midnight"),
            selection=activity_selection(args, raw),
            activity_types=(
                activity_types
                if activity_types is not None
                else configured_selection.get("activity_types", ["Ride", "Pedalada"])
            ),
        )
