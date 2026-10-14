"""Central lossless ingestion pipeline for DuckDB and Parquet."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ride_visuals.model.activity import ActivitySummary
from ride_visuals.model.trackpoint import TrackPoint, STREAM_ARROW_SCHEMA
from ride_visuals.ingest.csv_reader import CSVActivityReader
from ride_visuals.ingest.fit_reader import FITReader
from ride_visuals.ingest.tcx_reader import TCXReader
from ride_visuals.ingest.gpx_reader import GPXReader
from ride_visuals.ingest.metrics import enrich_trackpoints
from ride_visuals.selection import DEFAULT_ACTIVITY_TYPES, ActivitySelection, expand_activity_types

ACTIVITY_EXTENSIONS = (".fit.gz", ".tcx.gz", ".gpx.gz", ".fit", ".tcx", ".gpx")



ACTIVITIES_TABLE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS activities (
    id BIGINT PRIMARY KEY,
    name VARCHAR,
    start_date TIMESTAMPTZ,
    activity_type VARCHAR,
    distance_m DOUBLE,
    elevation_gain_m DOUBLE,
    moving_time_s BIGINT,
    elapsed_time_s BIGINT,
    avg_speed_mps DOUBLE,
    max_speed_mps DOUBLE,
    avg_heart_rate DOUBLE,
    max_heart_rate DOUBLE,
    relative_effort DOUBLE,
    estimated_watts_avg DOUBLE,
    estimated_watts_max DOUBLE,
    temperature_avg DOUBLE,
    temperature_max DOUBLE,
    gear VARCHAR,
    source_filename VARCHAR,
    source_format VARCHAR,
    file_sha256 VARCHAR,
    point_count BIGINT,
    has_hr_stream BOOLEAN,
    has_speed_stream BOOLEAN,
    has_temp_stream BOOLEAN,
    has_watts_stream BOOLEAN
)
"""


def compute_file_sha256(path: Path) -> str:
    """Compute the SHA256 hash of a file on disk."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def find_export_root(bulk_dir: Path) -> Tuple[Path, Path]:
    """Locate activities.csv and the activities/ directory in the bulk download."""
    bulk_dir = Path(bulk_dir)
    candidates = list(bulk_dir.glob("export_*")) + [bulk_dir]
    for c in candidates:
        csv_cand = c / "activities.csv"
        act_cand = c / "activities"
        if csv_cand.exists() and act_cand.exists():
            return csv_cand, act_cand

    # Recursive search
    for csv_cand in bulk_dir.rglob("activities.csv"):
        act_cand = csv_cand.parent / "activities"
        if act_cand.exists():
            return csv_cand, act_cand

    raise FileNotFoundError(f"Activity export not found in {bulk_dir}")


def discover_activity_files(bulk_dir: Path) -> List[Path]:
    """Find standalone .fit, .tcx, and .gpx files when no activities.csv exists."""
    bulk_dir = Path(bulk_dir)
    if not bulk_dir.exists():
        return []
    found = [
        p
        for p in bulk_dir.rglob("*")
        if p.is_file()
        and not p.name.startswith(".")
        and p.name.lower().endswith(ACTIVITY_EXTENSIONS)
    ]
    return sorted(found)


def _strip_activity_suffix(filename: str) -> str:
    lower = filename.lower()
    for ext in ACTIVITY_EXTENSIONS:
        if lower.endswith(ext):
            return filename[: len(filename) - len(ext)]
    return Path(filename).stem


def _normalize_sport(raw_sport: Any) -> str:
    sport = str(raw_sport or "").strip().lower()
    if not sport or any(k in sport for k in ("cycl", "bik", "ride", "velo", "vélo", "rad", "pedal", "fiets")):
        return "Ride"
    if "run" in sport or "corr" in sport or "lauf" in sport:
        return "Run"
    if "walk" in sport or "caminh" in sport:
        return "Walk"
    if "hik" in sport or "wand" in sport or "randonn" in sport:
        return "Hike"
    if "swim" in sport or "nata" in sport or "schwimm" in sport:
        return "Swim"
    return sport.capitalize()


def summarize_activity_stream(
    source: Path,
    points: List[TrackPoint],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    """Derive activity summary metadata directly from enriched trackpoints and file metadata."""
    session = meta.get("session", {})
    start_dt = session.get("start_time")
    if not isinstance(start_dt, datetime):
        start_dt = points[0].timestamp
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    else:
        start_dt = start_dt.astimezone(timezone.utc)

    stem = _strip_activity_suffix(source.name)
    act_id = int(stem) if stem.isdigit() else int(start_dt.timestamp() * 1000)

    default_name = stem.replace("_", " ").replace("-", " ").strip() or source.name
    name = str(meta.get("name") or default_name).strip()
    activity_type = _normalize_sport(session.get("sport") or meta.get("sport"))

    dist_m = (
        points[-1].distance_m
        if points and points[-1].distance_m is not None
        else float(session.get("total_distance") or 0.0)
    )

    if session.get("total_ascent") is not None:
        elev_m = float(session["total_ascent"])
    else:
        alts = [p.altitude for p in points if p.altitude is not None]
        elev_m = round(sum(max(0.0, b - a) for a, b in zip(alts, alts[1:])), 1) if len(alts) > 1 else 0.0

    if session.get("total_elapsed_time") is not None:
        elapsed_s = int(round(float(session["total_elapsed_time"])))
    else:
        elapsed_s = max(0, int(round((points[-1].timestamp - points[0].timestamp).total_seconds())))

    if session.get("total_timer_time") is not None:
        moving_s = int(round(float(session["total_timer_time"])))
    else:
        moving_acc = 0.0
        for prev_pt, curr_pt in zip(points, points[1:]):
            dt = (curr_pt.timestamp - prev_pt.timestamp).total_seconds()
            if 0.0 < dt <= 30.0 and (curr_pt.speed_mps or 0.0) >= 0.5:
                moving_acc += dt
        moving_s = int(round(moving_acc)) if moving_acc > 0 else elapsed_s

    speeds = [p.speed_mps for p in points if p.speed_mps is not None and p.quality_flags == "ok"]
    avg_speed = (
        float(session["avg_speed"])
        if session.get("avg_speed") is not None
        else (round(dist_m / moving_s, 3) if moving_s > 0 else None)
    )
    max_speed = (
        float(session["max_speed"])
        if session.get("max_speed") is not None
        else (round(max(speeds), 3) if speeds else None)
    )

    hrs = [p.heart_rate_bpm for p in points if p.heart_rate_bpm is not None]
    avg_hr = (
        float(session["avg_heart_rate"])
        if session.get("avg_heart_rate") is not None
        else (round(sum(hrs) / len(hrs), 1) if hrs else None)
    )
    max_hr = (
        float(session["max_heart_rate"])
        if session.get("max_heart_rate") is not None
        else (round(max(hrs), 1) if hrs else None)
    )

    watts = [p.power_watts for p in points if p.power_watts is not None]
    avg_watts = (
        float(session["avg_power"])
        if session.get("avg_power") is not None
        else (round(sum(watts) / len(watts), 1) if watts else None)
    )
    max_watts = (
        float(session["max_power"])
        if session.get("max_power") is not None
        else (round(max(watts), 1) if watts else None)
    )

    temps = [p.temperature_c for p in points if p.temperature_c is not None]
    avg_temp = (
        float(session["avg_temperature"])
        if session.get("avg_temperature") is not None
        else (round(sum(temps) / len(temps), 1) if temps else None)
    )
    max_temp = (
        float(session["max_temperature"])
        if session.get("max_temperature") is not None
        else (round(max(temps), 1) if temps else None)
    )

    return {
        "id": act_id,
        "name": name,
        "start_date": start_dt,
        "activity_type": activity_type,
        "distance_m": dist_m,
        "elevation_gain_m": elev_m,
        "elapsed_time_s": elapsed_s,
        "moving_time_s": moving_s,
        "avg_speed_mps": avg_speed,
        "max_speed_mps": max_speed,
        "avg_heart_rate": avg_hr,
        "max_heart_rate": max_hr,
        "relative_effort": None,
        "estimated_watts_avg": avg_watts,
        "estimated_watts_max": max_watts,
        "temperature_avg": avg_temp,
        "temperature_max": max_temp,
        "gear": None,
    }


class IngestPipeline:
    """Lossless ingestion orchestrator."""

    def __init__(self,
                 bulk_dir: Path,
                 catalog_db_path: Path,
                 streams_dir: Path,
                 selection: Optional[ActivitySelection] = None,
                 activity_types: Optional[List[str]] = None,
                 clean: bool = False,
                 only_ids: Optional[set[int]] = None):
        self.bulk_dir = Path(bulk_dir)
        self.catalog_db_path = Path(catalog_db_path)
        self.streams_dir = Path(streams_dir)
        self.selection = selection or ActivitySelection()
        self.activity_types = expand_activity_types(activity_types or DEFAULT_ACTIVITY_TYPES)
        self.clean = clean
        self.only_ids = only_ids

        self.catalog_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.streams_dir.mkdir(parents=True, exist_ok=True)

    def _find_export_root(self) -> Tuple[Path, Path]:
        """Locate activities.csv and the activities/ directory in the bulk download."""
        return find_export_root(self.bulk_dir)

    def _wipe_previous_data(self) -> None:
        for stream_file in self.streams_dir.glob("*.parquet"):
            stream_file.unlink()
        if self.catalog_db_path.exists():
            con = duckdb.connect(str(self.catalog_db_path))
            con.execute("DROP TABLE IF EXISTS activities")
            con.close()

    @staticmethod
    def _read_track_file(target_file: Path, stats: Dict[str, Any]) -> Tuple[List[TrackPoint], Dict[str, Any], str]:
        fname_lower = target_file.name.lower()
        if ".fit" in fname_lower:
            points, meta = FITReader.read_fit(target_file)
            stats["fit_count"] += 1
            return points, meta, "fit"
        if ".tcx" in fname_lower:
            points, meta = TCXReader.read_tcx(target_file)
            meta = {**meta, **TCXReader.read_activity_metadata(target_file)}
            stats["tcx_count"] += 1
            return points, meta, "tcx"
        if ".gpx" in fname_lower:
            points, meta = GPXReader.read_gpx(target_file)
            meta = {**meta, **GPXReader.read_activity_metadata(target_file)}
            stats["gpx_count"] += 1
            return points, meta, "gpx"
        return [], {}, "unknown"

    @staticmethod
    def _empty_stats(total_scoped: int = 0) -> Dict[str, Any]:
        return {
            "total_scoped": total_scoped,
            "ingested_activities": 0,
            "total_points": 0,
            "fit_count": 0,
            "tcx_count": 0,
            "gpx_count": 0,
            "with_hr_stream": 0,
            "with_speed_stream": 0,
            "with_temp_stream": 0,
            "with_watts_stream": 0,
            "total_distance_m": 0.0,
            "total_elevation_m": 0.0,
        }

    def _record_activity(
        self,
        act_id: int,
        summary: Dict[str, Any],
        target_file: Path,
        source_fmt: str,
        enriched_pts: List[TrackPoint],
        stats: Dict[str, Any],
    ) -> ActivitySummary:
        self._write_stream_parquet(enriched_pts, self.streams_dir / f"{act_id}.parquet")
        has_hr = any(p.heart_rate_bpm is not None for p in enriched_pts)
        has_spd = any(p.speed_mps is not None for p in enriched_pts)
        has_tmp = any(p.temperature_c is not None for p in enriched_pts)
        has_pwr = any(p.power_watts is not None for p in enriched_pts)

        stats["with_hr_stream"] += int(has_hr)
        stats["with_speed_stream"] += int(has_spd)
        stats["with_temp_stream"] += int(has_tmp)
        stats["with_watts_stream"] += int(has_pwr)
        stats["total_distance_m"] += summary["distance_m"]
        stats["total_elevation_m"] += summary["elevation_gain_m"]
        stats["total_points"] += len(enriched_pts)
        stats["ingested_activities"] += 1

        return ActivitySummary(
            id=act_id,
            name=summary["name"],
            start_date=summary["start_date"],
            activity_type=summary["activity_type"],
            distance_m=summary["distance_m"],
            elevation_gain_m=summary["elevation_gain_m"],
            moving_time_s=summary["moving_time_s"],
            elapsed_time_s=summary["elapsed_time_s"],
            avg_speed_mps=summary["avg_speed_mps"],
            max_speed_mps=summary["max_speed_mps"],
            avg_heart_rate=summary["avg_heart_rate"],
            max_heart_rate=summary["max_heart_rate"],
            relative_effort=summary["relative_effort"],
            estimated_watts_avg=summary["estimated_watts_avg"],
            estimated_watts_max=summary["estimated_watts_max"],
            temperature_avg=summary["temperature_avg"],
            temperature_max=summary["temperature_max"],
            gear=summary["gear"],
            source_filename=target_file.name,
            source_format=source_fmt,
            file_sha256=compute_file_sha256(target_file),
            point_count=len(enriched_pts),
            has_hr_stream=has_hr,
            has_speed_stream=has_spd,
            has_temp_stream=has_tmp,
            has_watts_stream=has_pwr,
        )

    def _run_directory_ingest(self, activity_files: List[Path]) -> Dict[str, Any]:
        """Ingest .fit, .tcx, and .gpx files directly without an activities.csv export."""
        if self.clean:
            self._wipe_previous_data()

        activities: List[ActivitySummary] = []
        seen_ids: set[int] = set()
        stats = self._empty_stats()

        for target_file in activity_files:
            points, meta, source_fmt = self._read_track_file(target_file, stats)
            if not points:
                print(f"[Warning] No GPS points extracted from {target_file.name}")
                continue

            enriched_pts = enrich_trackpoints(points)
            summary = summarize_activity_stream(target_file, enriched_pts, meta)
            if not (
                self.selection.matches(summary["start_date"])
                and summary["activity_type"] in self.activity_types
            ):
                continue

            stats["total_scoped"] += 1
            act_id = summary["id"]
            while act_id in seen_ids:
                act_id += 1
            if self.only_ids is not None and act_id not in self.only_ids:
                continue
            seen_ids.add(act_id)

            activities.append(
                self._record_activity(act_id, summary, target_file, source_fmt, enriched_pts, stats)
            )

        self._write_catalog_duckdb(activities)
        return stats

    def run_ingest(self) -> Dict[str, Any]:
        """Run the full ingestion with auditing and provenance."""
        # Resolve and parse the source before removing any prior outputs. A
        # missing or malformed export must never turn --clean into data loss.
        try:
            csv_file, act_dir = self._find_export_root()
        except FileNotFoundError:
            activity_files = discover_activity_files(self.bulk_dir)
            if not activity_files:
                raise
            return self._run_directory_ingest(activity_files)

        reader = CSVActivityReader(csv_file)
        all_csv_records = reader.read_activities()

        scoped_records = [
            r
            for r in all_csv_records
            if self.selection.matches(r["start_date"]) and r["activity_type"] in self.activity_types
        ]

        if self.clean:
            self._wipe_previous_data()

        file_map = {f.name: f for f in act_dir.glob("*") if f.is_file() and not f.name.startswith(".")}
        activities: List[ActivitySummary] = []
        stats = self._empty_stats(total_scoped=len(scoped_records))

        for record in scoped_records:
            act_id = record["id"]
            if self.only_ids is not None and act_id not in self.only_ids:
                continue
            raw_filename = record["filename"]
            base_fname = Path(raw_filename).name if raw_filename else f"{act_id}.tcx.gz"

            target_file = file_map.get(base_fname)
            if target_file is None:
                for k, v in file_map.items():
                    if str(act_id) in k:
                        target_file = v
                        break

            if not target_file or not target_file.exists():
                print(f"[Warning] Activity file not found for ID {act_id}: {base_fname}")
                continue

            points, _meta, source_fmt = self._read_track_file(target_file, stats)
            if not points:
                print(f"[Warning] No GPS points extracted from {target_file.name}")
                continue

            enriched_pts = enrich_trackpoints(points)
            summary = {
                **record,
                "distance_m": (
                    enriched_pts[-1].distance_m if enriched_pts else record["distance_raw"] * 1000.0
                ),
                "avg_speed_mps": record["avg_speed_raw"],
                "max_speed_mps": record["max_speed_raw"],
            }
            activities.append(
                self._record_activity(act_id, summary, target_file, source_fmt, enriched_pts, stats)
            )

        self._write_catalog_duckdb(activities)
        return stats

    def _write_stream_parquet(self, points: List[TrackPoint], path: Path):
        """Write one activity's point series to a high-performance Parquet file."""
        records = {
            "timestamp": [int(p.timestamp.timestamp() * 1000) for p in points],
            "lat": [p.lat for p in points],
            "lon": [p.lon for p in points],
            "altitude": [p.altitude if p.altitude is not None else np.nan for p in points],
            "distance_m": [p.distance_m if p.distance_m is not None else np.nan for p in points],
            "speed_mps": [p.speed_mps if p.speed_mps is not None else np.nan for p in points],
            "heart_rate_bpm": [p.heart_rate_bpm if p.heart_rate_bpm is not None else np.nan for p in points],
            "power_watts": [p.power_watts if p.power_watts is not None else np.nan for p in points],
            "cadence_rpm": [p.cadence_rpm if p.cadence_rpm is not None else np.nan for p in points],
            "temperature_c": [p.temperature_c if p.temperature_c is not None else np.nan for p in points],
            "grade_pct": [p.grade_pct if p.grade_pct is not None else np.nan for p in points],
            "bearing_deg": [p.bearing_deg if p.bearing_deg is not None else np.nan for p in points],
            "provenance_speed": [p.provenance_speed for p in points],
            "provenance_power": [p.provenance_power for p in points],
            "provenance_temp": [p.provenance_temp for p in points],
            "quality_flags": [p.quality_flags for p in points],
        }
        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        table = pa.Table.from_pandas(df, schema=STREAM_ARROW_SCHEMA)
        pq.write_table(table, path, compression="zstd")

    def _write_catalog_duckdb(self, activities: List[ActivitySummary]):
        """Persist the activity catalog table to DuckDB incrementally."""
        con = duckdb.connect(str(self.catalog_db_path))
        con.execute(ACTIVITIES_TABLE_SCHEMA_SQL)
        if activities:
            dicts = [a.to_dict() for a in activities]
            df = pd.DataFrame(dicts)
            df["start_date"] = pd.to_datetime(df["start_date"], utc=True)
            # Upsert via DELETE + INSERT: works for catalogs created with a
            # PRIMARY KEY and for legacy catalogs without the constraint
            # (INSERT OR REPLACE requires UNIQUE/PRIMARY KEY on the table).
            con.execute("BEGIN TRANSACTION")
            con.execute("DELETE FROM activities WHERE id IN (SELECT id FROM df)")
            con.execute("INSERT INTO activities BY NAME SELECT * FROM df")
            con.execute("COMMIT")
        con.close()
