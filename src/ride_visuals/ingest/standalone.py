"""Importação de arquivos FIT avulsos (fora do export Strava) para a coleção.

Cada arquivo é copiado para a pasta ``activities/`` do export e registrado
como uma nova linha no ``activities.csv``, seguindo o mesmo fluxo das
atividades originais do export. O ID é derivado do horário de início (epoch
em milissegundos), garantindo unicidade sem colidir com IDs da Strava.
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
from ride_visuals.ingest.pipeline import find_export_root

# Esporte do FIT -> rótulo de tipo usado no export pt-BR.
SPORT_TYPE_MAP = {
    "cycling": "Pedalada",
    "running": "Corrida",
    "walking": "Caminhada",
    "hiking": "Caminhada",
    "swimming": "Natação",
}

# Tolerância para considerar duas atividades como a mesma (mesmo treino
# registrado por dispositivos diferentes pode diferir por alguns segundos).
DUPLICATE_WINDOW_S = 120

STATUS_IMPORTED = "imported"
STATUS_DUPLICATE = "duplicate"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class ImportResult:
    """Resultado da tentativa de importação de um arquivo FIT avulso."""

    source: Path
    status: str
    activity_id: Optional[int] = None
    name: Optional[str] = None
    activity_type: Optional[str] = None
    start_date: Optional[datetime] = None
    message: str = ""


class StandaloneFitImporter:
    """Copia FITs avulsos para o export e registra as atividades no activities.csv."""

    def __init__(
        self,
        bulk_dir: Path,
        name: Optional[str] = None,
        activity_type: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.bulk_dir = Path(bulk_dir)
        self.csv_file, self.activities_dir = find_export_root(self.bulk_dir)
        self.name = name
        self.activity_type = activity_type
        self.dry_run = dry_run
        self.reader = CSVActivityReader(self.csv_file)
        self.existing: List[Dict[str, Any]] = self.reader.read_activities()

    def import_files(self, files: List[Path]) -> List[ImportResult]:
        """Importa cada arquivo, devolvendo um resultado por arquivo."""
        return [self._import_one(Path(f)) for f in files]

    def _import_one(self, source: Path) -> ImportResult:
        try:
            session = FITReader.read_session_metadata(source)
        except Exception as exc:  # arquivo corrompido ou não-FIT
            return ImportResult(source, STATUS_ERROR, message=f"falha ao ler FIT: {exc}")

        start_time = session.get("start_time")
        if not isinstance(start_time, datetime):
            return ImportResult(source, STATUS_ERROR, message="session.start_time ausente no FIT")
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
                    f"já existe a atividade {duplicate['id']} “{duplicate['name']}” "
                    f"iniciando em {duplicate['start_date']:%Y-%m-%d %H:%M:%S} UTC"
                ),
            )

        act_id = int(start_time.timestamp() * 1000)
        if any(r["id"] == act_id for r in self.existing):
            return ImportResult(
                source,
                STATUS_DUPLICATE,
                activity_id=act_id,
                message=f"ID derivado {act_id} já presente no activities.csv",
            )

        sport = str(session.get("sport") or "").lower()
        activity_type = self.activity_type or SPORT_TYPE_MAP.get(sport, sport.capitalize() or "Other")
        name = self.name or _name_from_file(source)

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
        """Procura atividade existente começando dentro da janela de tolerância."""
        for record in self.existing:
            other = record["start_date"]
            if other.tzinfo is None:
                other = other.replace(tzinfo=timezone.utc)
            if abs((other - start_time).total_seconds()) <= DUPLICATE_WINDOW_S:
                return record
        return None

    def _copy_file(self, source: Path, act_id: int) -> Path:
        suffix = ".fit.gz" if source.name.lower().endswith(".fit.gz") else ".fit"
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
        """Monta a linha do activities.csv usando as colunas resolvidas do export."""
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
    """Nome padrão da atividade derivado do nome do arquivo."""
    stem = source.stem
    if stem.lower().endswith(".fit"):
        stem = stem[:-4]
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
        hr_part = f" · FC {int(session['avg_heart_rate'])}/{int(session.get('max_heart_rate') or 0)}"
    return (
        f"“{name}” ({activity_type}) id {act_id} · "
        f"{distance_km:.1f} km · +{ascent} m · {hours}h{minutes:02d}{hr_part}"
    )
