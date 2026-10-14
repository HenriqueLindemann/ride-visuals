"""Import standalone activity files (.fit, .tcx, .gpx) into the collection.

Each file is copied into ``activities/`` and recorded as a new row in
``activities.csv`` (creating both when no Strava export is present). The ID is
derived from the start time (epoch in milliseconds), guaranteeing uniqueness
without colliding with Strava IDs.
"""

from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ride_visuals.ingest.csv_reader import CSVActivityReader
from ride_visuals.ingest.fit_reader import FITReader
from ride_visuals.ingest.gpx_reader import GPXReader
from ride_visuals.ingest.metrics import enrich_trackpoints
from ride_visuals.ingest.pipeline import (
    ACTIVITY_EXTENSIONS,
    _strip_activity_suffix,
    find_export_root,
    summarize_activity_stream,
)
from ride_visuals.ingest.tcx_reader import TCXReader

SPORT_TYPE_MAP = {
    "cycling": "Pedalada",
    "biking": "Pedalada",
    "running": "Corrida",
    "walking": "Caminhada",
    "hiking": "Caminhada",
    "swimming": "Natação",
}

SPORT_TYPE_MAP_EN = {
    "cycling": "Ride",
    "biking": "Ride",
    "running": "Run",
    "walking": "Walk",
    "hiking": "Hike",
    "swimming": "Swim",
}

DEFAULT_CSV_HEADER = [
    "Activity ID",
    "Activity Date",
    "Activity Name",
    "Activity Type",
    "Elapsed Time",
    "Distance",
    "Distance.1",
    "Elevation Gain",
    "Moving Time",
    "Max Speed",
    "Average Speed",
    "Max Heart Rate",
    "Average Heart Rate",
    "Relative Effort",
    "Max Watts",
    "Average Watts",
    "Max Temperature",
    "Average Temperature",
    "Activity Gear",
    "Filename",
]

# Tolerance for treating two activities as the same (the same workout
# recorded by different devices may differ by a few seconds).
DUPLICATE_WINDOW_S = 120

STATUS_IMPORTED = "imported"
STATUS_DUPLICATE = "duplicate"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class ImportResult:
    """Result of one standalone activity import attempt."""

    source: Path
    status: str
    activity_id: Optional[int] = None
    name: Optional[str] = None
    activity_type: Optional[str] = None
    start_date: Optional[datetime] = None
    message: str = ""


class StandaloneFitImporter:
    """Copy standalone activity files (.fit, .tcx, .gpx) into the collection."""

    def __init__(
        self,
        bulk_dir: Path,
        name: Optional[str] = None,
        activity_type: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.bulk_dir = Path(bulk_dir)
        self.name = name
        self.activity_type = activity_type
        self.dry_run = dry_run
        try:
            self.csv_file, self.activities_dir = find_export_root(self.bulk_dir)
            self.reader: Optional[CSVActivityReader] = CSVActivityReader(self.csv_file)
            self.existing: List[Dict[str, Any]] = self.reader.read_activities()
        except FileNotFoundError:
            self.csv_file = self.bulk_dir / "activities.csv"
            self.activities_dir = self.bulk_dir / "activities"
            self.existing = []
            if self.dry_run:
                self.reader = None
            else:
                self.activities_dir.mkdir(parents=True, exist_ok=True)
                with self.csv_file.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f, lineterminator="\n")
                    writer.writerow(DEFAULT_CSV_HEADER)
                self.reader = CSVActivityReader(self.csv_file)

    def _sport_label(self, sport: str) -> str:
        is_pt = self.reader is not None and "ID da atividade" in self.reader.df.columns
        mapping = SPORT_TYPE_MAP if is_pt else SPORT_TYPE_MAP_EN
        return mapping.get(sport, sport.capitalize() or ("Pedalada" if is_pt else "Ride"))

    @staticmethod
    def _read_metadata(source: Path) -> Dict[str, Any]:
        lower = source.name.lower()
        if ".fit" in lower:
            return FITReader.read_session_metadata(source)
        if ".tcx" in lower:
            points, meta = TCXReader.read_tcx(source)
            meta = {**meta, **TCXReader.read_activity_metadata(source)}
        elif ".gpx" in lower:
            points, meta = GPXReader.read_gpx(source)
            meta = {**meta, **GPXReader.read_activity_metadata(source)}
        else:
            return FITReader.read_session_metadata(source)

        if not points:
            raise ValueError("no GPS points found")
        enriched = enrich_trackpoints(points)
        summary = summarize_activity_stream(source, enriched, meta)
        return {
            "start_time": summary["start_date"],
            "sport": meta.get("sport") or "cycling",
            "name": meta.get("name"),
            "total_elapsed_time": summary["elapsed_time_s"],
            "total_timer_time": summary["moving_time_s"],
            "total_distance": summary["distance_m"],
            "total_ascent": summary["elevation_gain_m"],
            "avg_speed": summary["avg_speed_mps"],
            "max_speed": summary["max_speed_mps"],
            "avg_heart_rate": summary["avg_heart_rate"],
            "max_heart_rate": summary["max_heart_rate"],
            "avg_temperature": summary["temperature_avg"],
            "max_temperature": summary["temperature_max"],
        }

    def import_files(self, files: List[Path]) -> List[ImportResult]:
        """Import every file, returning one result per file."""
        return [self._import_one(Path(f)) for f in files]

    def _import_one(self, source: Path) -> ImportResult:
        try:
            session = self._read_metadata(source)
        except Exception as exc:
            return ImportResult(source, STATUS_ERROR, message=f"failed to read activity: {exc}")

        start_time = session.get("start_time")
        if not isinstance(start_time, datetime):
            return ImportResult(source, STATUS_ERROR, message="session.start_time missing from FIT")
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        start_time = start_time.astimezone(timezone.utc)

        duplicate = self._find_duplicate(start_time)
        if duplicate:
            return ImportResult(
                source,
                STATUS_DUPLICATE,
                activity_id=duplicate["id"],
                name=duplicate["name"],
                start_date=duplicate["start_date"],
                message=(
                    f"activity {duplicate['id']} “{duplicate['name']}” already exists "
                    f"starting at {duplicate['start_date']:%Y-%m-%d %H:%M:%S} UTC"
                ),
            )

        act_id = int(start_time.timestamp() * 1000)
        if any(r["id"] == act_id for r in self.existing):
            return ImportResult(
                source,
                STATUS_DUPLICATE,
                activity_id=act_id,
                message=f"derived ID {act_id} already present in activities.csv",
            )

        sport = str(session.get("sport") or "").lower()
        activity_type = self.activity_type or self._sport_label(sport)
        name = self.name or session.get("name") or _name_from_file(source)

        if self.dry_run:
            return ImportResult(
                source,
                STATUS_IMPORTED,
                activity_id=act_id,
                name=name,
                activity_type=activity_type,
                start_date=start_time,
                message=_describe_session(session, name, activity_type, act_id),
            )

        target = self._copy_file(source, act_id)
        row = self._build_row(session, act_id, name, activity_type, start_time, target)
        self._append_csv_row(row)
        self.existing.append(
            {
                "id": act_id,
                "name": name,
                "start_date": start_time,
                "activity_type": activity_type,
                "filename": f"activities/{target.name}",
            }
        )
        return ImportResult(
            source,
            STATUS_IMPORTED,
            activity_id=act_id,
            name=name,
            activity_type=activity_type,
            start_date=start_time,
            message=_describe_session(session, name, activity_type, act_id),
        )

    def _find_duplicate(self, start_time: datetime) -> Optional[Dict[str, Any]]:
        """Find an existing activity starting within the tolerance window."""
        for record in self.existing:
            other = record["start_date"]
            if other.tzinfo is None:
                other = other.replace(tzinfo=timezone.utc)
            if abs((other - start_time).total_seconds()) <= DUPLICATE_WINDOW_S:
                return record
        return None

    def _copy_file(self, source: Path, act_id: int) -> Path:
        lower = source.name.lower()
        suffix = ".fit"
        for ext in ACTIVITY_EXTENSIONS:
            if lower.endswith(ext):
                suffix = ext
                break
        target = self.activities_dir / f"{act_id}{suffix}"
        shutil.copyfile(source, target)
        return target

    def _build_row(
        self,
        session: Dict[str, Any],
        act_id: int,
        name: str,
        activity_type: str,
        start_time: datetime,
        target: Path,
    ) -> Dict[str, str]:
        """Build the activities.csv row using the export's resolved columns."""
        resolved = self.reader._col_mapping
        values = {
            "id": str(act_id),
            "date": start_time.strftime("%Y-%m-%d %H:%M:%S+00:00"),
            "name": name,
            "type": activity_type,
            "distance": _fmt_number(session.get("total_distance")),
            "elevation": _fmt_number(session.get("total_ascent"), integer=True),
            "elapsed_time": _fmt_number(session.get("total_elapsed_time"), integer=True),
            "moving_time": _fmt_number(session.get("total_timer_time"), integer=True),
            "max_speed": _fmt_number(session.get("max_speed")),
            "avg_speed": _fmt_number(session.get("avg_speed")),
            "max_hr": _fmt_number(session.get("max_heart_rate"), integer=True),
            "avg_hr": _fmt_number(session.get("avg_heart_rate"), integer=True),
            "avg_temp": _fmt_number(session.get("avg_temperature"), integer=True),
            "max_temp": _fmt_number(session.get("max_temperature"), integer=True),
            "gear": None,
            "filename": f"activities/{target.name}",
        }

        row = {column: "" for column in self.reader.df.columns}
        for canonical, value in values.items():
            column = resolved.get(canonical)
            if column and value is not None:
                row[column] = value
        return row

    def _append_csv_row(self, row: Dict[str, str]) -> None:
        with self.csv_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()), lineterminator="\n")
            writer.writerow(row)


def _name_from_file(source: Path) -> str:
    """Default activity name derived from the file name."""
    stem = _strip_activity_suffix(source.name)
    return stem.replace("_", " ").replace("-", " ").strip() or source.name


def _fmt_number(value: Any, integer: bool = False) -> Optional[str]:
    if value is None:
        return None
    number = float(value)
    if integer:
        return str(int(round(number)))
    return f"{number:.2f}"


def _describe_session(
    session: Dict[str, Any],
    name: str,
    activity_type: str,
    act_id: int,
) -> str:
    distance_km = (session.get("total_distance") or 0.0) / 1000.0
    ascent = int(session.get("total_ascent") or 0)
    moving = int(session.get("total_timer_time") or 0)
    hours, remainder = divmod(moving, 3600)
    minutes = remainder // 60
    hr_part = ""
    if session.get("avg_heart_rate") is not None:
        hr_part = f" · HR {int(session['avg_heart_rate'])}/{int(session.get('max_heart_rate') or 0)}"
    return (
        f"“{name}” ({activity_type}) id {act_id} · "
        f"{distance_km:.1f} km · +{ascent} m · {hours}h{minutes:02d}{hr_part}"
    )
