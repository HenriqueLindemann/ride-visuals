"""Ride Visuals command-line interface."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from ride_visuals.commands.common import (
    activity_selection,
    add_selection_arguments,
    load_config,
)
from ride_visuals.commands.parser import build_parser
from ride_visuals.commands.validation import final_video_paths

__all__ = [
    "activity_selection",
    "add_selection_arguments",
    "build_parser",
    "final_video_paths",
    "load_config",
    "main",
]


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args: argparse.Namespace = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
