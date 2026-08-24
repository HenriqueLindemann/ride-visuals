"""Pipeline central de ingestão lossless para DuckDB e Parquet."""

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
from ride_visuals.selection import ActivitySelection


def compute_file_sha256(path: Path) -> str:
    """Calcula o hash SHA256 de um arquivo em disco."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class IngestPipeline:
    """Orquestrador de ingestão lossless."""

    def __init__(self,
                 bulk_dir: Path,
                 catalog_db_path: Path,
                 streams_dir: Path,
                 selection: Optional[ActivitySelection] = None,
                 activity_types: Optional[List[str]] = None):
        self.bulk_dir = Path(bulk_dir)
        self.catalog_db_path = Path(catalog_db_path)
        self.streams_dir = Path(streams_dir)
        self.selection = selection or ActivitySelection()
        self.activity_types = set(activity_types or ["Ride", "Pedalada"])

        self.catalog_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.streams_dir.mkdir(parents=True, exist_ok=True)

    def _find_export_root(self) -> Tuple[Path, Path]:
        """Localiza o activities.csv e a pasta activities/ no bulk download."""
        candidates = list(self.bulk_dir.glob("export_*")) + [self.bulk_dir]
        for c in candidates:
            csv_cand = c / "activities.csv"
            act_cand = c / "activities"
            if csv_cand.exists() and act_cand.exists():
                return csv_cand, act_cand

        # Busca recursiva
        for csv_cand in self.bulk_dir.rglob("activities.csv"):
            act_cand = csv_cand.parent / "activities"
            if act_cand.exists():
                return csv_cand, act_cand

        raise FileNotFoundError(f"Activity export not found in {self.bulk_dir}")

    def run_ingest(self) -> Dict[str, Any]:
        """Executa a ingestão completa com auditoria e procedência."""
        csv_file, act_dir = self._find_export_root()
        reader = CSVActivityReader(csv_file)
        all_csv_records = reader.read_activities()

        scoped_records = []
        for r in all_csv_records:
            dt = r["start_date"]
            if self.selection.matches(dt) and r["activity_type"] in self.activity_types:
                scoped_records.append(r)

        # Mapear arquivos da pasta activities
        file_map = {f.name: f for f in act_dir.glob("*") if f.is_file() and not f.name.startswith(".")}

        activities: List[ActivitySummary] = []
        stats = {
            "total_scoped": len(scoped_records),
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

        for record in scoped_records:
            act_id = record["id"]
            raw_filename = record["filename"]
            base_fname = Path(raw_filename).name if raw_filename else f"{act_id}.tcx.gz"

            target_file = None
            if base_fname in file_map:
                target_file = file_map[base_fname]
            else:
                # Tentar encontrar por ID
                for k, v in file_map.items():
                    if str(act_id) in k:
                        target_file = v
                        break

            if not target_file or not target_file.exists():
                print(f"[Aviso] Arquivo de atividade não encontrado para ID {act_id}: {base_fname}")
                continue

            file_hash = compute_file_sha256(target_file)
            fname_lower = target_file.name.lower()

            points: List[TrackPoint] = []
            meta: Dict[str, Any] = {}
            source_fmt = "unknown"

            if ".fit" in fname_lower:
                source_fmt = "fit"
                points, meta = FITReader.read_fit(target_file)
                stats["fit_count"] += 1
            elif ".tcx" in fname_lower:
                source_fmt = "tcx"
                points, meta = TCXReader.read_tcx(target_file)
                stats["tcx_count"] += 1
            elif ".gpx" in fname_lower:
                source_fmt = "gpx"
                points, meta = GPXReader.read_gpx(target_file)
                stats["gpx_count"] += 1

            if not points:
                print(f"[Aviso] Nenhum ponto GPS extraído de {target_file.name}")
                continue

            # Enriquecer métricas de telemetria
            enriched_pts = enrich_trackpoints(points)

            # Gravar stream Parquet
            parquet_path = self.streams_dir / f"{act_id}.parquet"
            self._write_stream_parquet(enriched_pts, parquet_path)

            # Verificar streams disponíveis
            has_hr = any(p.heart_rate_bpm is not None for p in enriched_pts)
            has_spd = any(p.speed_mps is not None for p in enriched_pts)
            has_tmp = any(p.temperature_c is not None for p in enriched_pts)
            has_pwr = any(p.power_watts is not None for p in enriched_pts)

            if has_hr:
                stats["with_hr_stream"] += 1
            if has_spd:
                stats["with_speed_stream"] += 1
            if has_tmp:
                stats["with_temp_stream"] += 1
            if has_pwr:
                stats["with_watts_stream"] += 1

            act_dist = enriched_pts[-1].distance_m if enriched_pts else record["distance_raw"] * 1000.0
            stats["total_distance_m"] += act_dist
            stats["total_elevation_m"] += record["elevation_gain_m"]
            stats["total_points"] += len(enriched_pts)
            stats["ingested_activities"] += 1

            activity_summary = ActivitySummary(
                id=act_id,
                name=record["name"],
                start_date=record["start_date"],
                activity_type=record["activity_type"],
                distance_m=act_dist,
                elevation_gain_m=record["elevation_gain_m"],
                moving_time_s=record["moving_time_s"],
                elapsed_time_s=record["elapsed_time_s"],
                avg_speed_mps=record["avg_speed_raw"],
                max_speed_mps=record["max_speed_raw"],
                avg_heart_rate=record["avg_heart_rate"],
                max_heart_rate=record["max_heart_rate"],
                relative_effort=record["relative_effort"],
                estimated_watts_avg=record["estimated_watts_avg"],
                estimated_watts_max=record["estimated_watts_max"],
                temperature_avg=record["temperature_avg"],
                temperature_max=record["temperature_max"],
                gear=record["gear"],
                source_filename=target_file.name,
                source_format=source_fmt,
                file_sha256=file_hash,
                point_count=len(enriched_pts),
                has_hr_stream=has_hr,
                has_speed_stream=has_spd,
                has_temp_stream=has_tmp,
                has_watts_stream=has_pwr,
            )
            activities.append(activity_summary)

        # Salvar catálogo consolidado no DuckDB
        self._write_catalog_duckdb(activities)

        return stats

    def _write_stream_parquet(self, points: List[TrackPoint], path: Path):
        """Salva a série de pontos de uma atividade em Parquet de alta performance."""
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
        """Persiste a tabela de catálogo de atividades no DuckDB."""
        if not activities:
            return

        dicts = [a.to_dict() for a in activities]
        df = pd.DataFrame(dicts)
        df["start_date"] = pd.to_datetime(df["start_date"], utc=True)

        con = duckdb.connect(str(self.catalog_db_path))
        con.execute("CREATE OR REPLACE TABLE activities AS SELECT * FROM df")
        con.close()
