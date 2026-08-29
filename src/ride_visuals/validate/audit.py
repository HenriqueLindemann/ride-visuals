"""Auditoria e validação profunda de dados e procedência."""

from pathlib import Path
from typing import Dict, Any
import duckdb
import pyarrow.parquet as pq
from ride_visuals.selection import ActivitySelection


class ActivityAuditor:
    """Realiza auditoria de integridade, procedência e cobertura métrica."""

    def __init__(self, catalog_db_path: Path, streams_dir: Path,
                 selection: ActivitySelection | None = None):
        self.catalog_db_path = Path(catalog_db_path)
        self.streams_dir = Path(streams_dir)
        self.selection = selection or ActivitySelection()

    def run_audit(self) -> Dict[str, Any]:
        if not self.catalog_db_path.exists():
            raise FileNotFoundError(f"Catálogo DuckDB não encontrado: {self.catalog_db_path}")

        where, parameters = self.selection.sql()
        con = duckdb.connect(str(self.catalog_db_path), read_only=True)
        df_activities = con.execute(
            f"SELECT * FROM activities{where} ORDER BY start_date", parameters
        ).fetchdf()
        con.close()

        if df_activities.empty:
            raise ValueError("No activities match the selected period")

        total_activities = len(df_activities)
        total_distance_km = df_activities["distance_m"].sum() / 1000.0
        total_elevation_m = df_activities["elevation_gain_m"].sum()
        min_date = df_activities["start_date"].min()
        max_date = df_activities["start_date"].max()

        fmt_counts = df_activities["source_format"].value_counts().to_dict()

        hr_summary_count = df_activities["avg_heart_rate"].notna().sum()
        hr_stream_count = df_activities["has_hr_stream"].sum()
        speed_stream_count = df_activities["has_speed_stream"].sum()
        temp_stream_count = df_activities["has_temp_stream"].sum()
        watts_stream_count = df_activities["has_watts_stream"].sum()

        # Auditoria detalhada por stream em Parquet
        stream_audits = []
        for _, row in df_activities.iterrows():
            act_id = row["id"]
            p_file = self.streams_dir / f"{act_id}.parquet"
            if not p_file.exists():
                stream_audits.append({
                    "id": act_id,
                    "status": "missing_stream",
                    "points": 0,
                })
                continue

            stream_df = pq.read_table(p_file).to_pandas()
            stream_audits.append({
                "id": act_id,
                "status": "ok",
                "points": len(stream_df),
                "has_hr": bool(stream_df["heart_rate_bpm"].notna().any()),
                "has_speed_explicit": bool((stream_df["provenance_speed"] == "measured").any()),
                "has_temp": bool(stream_df["temperature_c"].notna().any()),
                "has_watts": bool(stream_df["power_watts"].notna().any()),
            })

        return {
            "total_activities": total_activities,
            "period_min": min_date,
            "period_max": max_date,
            "total_distance_km": round(total_distance_km, 1),
            "total_elevation_m": round(total_elevation_m, 0),
            "format_counts": fmt_counts,
            "hr_summary_count": int(hr_summary_count),
            "hr_stream_count": int(hr_stream_count),
            "speed_stream_count": int(speed_stream_count),
            "temp_stream_count": int(temp_stream_count),
            "watts_stream_count": int(watts_stream_count),
            "streams_audited": len(stream_audits),
        }
