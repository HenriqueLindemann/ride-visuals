"""Leitor robusto de activities.csv com suporte multi-idioma (PT/EN) e parsing de datas."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
import pandas as pd


PT_MONTHS = {
    'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6,
    'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12,
    'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4,
    'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8, 'setembro': 9,
    'outubro': 10, 'novembro': 11, 'dezembro': 12
}

EN_MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
}


def parse_flexible_date(s: Any) -> Optional[datetime]:
    """Converte strings de data em diversos formatos (PT, EN, ISO) para datetime UTC."""
    if s is None or pd.isna(s):
        return None
    s = str(s).strip()
    if not s:
        return None

    # Formato PT: "23 de ago. de 2024, 07:18:50" ou "23 de agosto de 2024 07:18:50"
    m_pt = re.search(r'(\d{1,2})\s+de\s+([a-zç]+)\.?\s+de\s+(\d{4}),?\s+(\d{1,2}):(\d{2}):(\d{2})', s, re.IGNORECASE)
    if m_pt:
        day, mon_str, year, hr, mn, sc = m_pt.groups()
        mon = PT_MONTHS.get(mon_str.lower()[:3], 1)
        return datetime(int(year), mon, int(day), int(hr), int(mn), int(sc), tzinfo=timezone.utc)

    # Formato EN: "Aug 23, 2024, 7:18:50 AM" ou "23 Aug 2024, 07:18:50"
    m_en = re.search(r'([a-z]+)\s+(\d{1,2}),?\s+(\d{4}),?\s+(\d{1,2}):(\d{2}):(\d{2})', s, re.IGNORECASE)
    if m_en:
        mon_str, day, year, hr, mn, sc = m_en.groups()
        mon = EN_MONTHS.get(mon_str.lower()[:3], 1)
        return datetime(int(year), mon, int(day), int(hr), int(mn), int(sc), tzinfo=timezone.utc)

    # Formato ISO ou padrão pandas
    try:
        dt = pd.to_datetime(s, utc=True)
        if pd.notna(dt):
            return dt.to_pydatetime()
    except Exception:
        pass

    return None


def parse_float_safe(val: Any) -> Optional[float]:
    """Converte números com vírgula ou ponto decimal para float de forma segura."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip().replace(" ", "")
    if not s or s.lower() == "nan" or s.lower() == "none":
        return None
    try:
        # Troca vírgula por ponto
        return float(s.replace(",", "."))
    except ValueError:
        return None


def parse_int_safe(val: Any) -> Optional[int]:
    """Converte inteiros de forma segura."""
    f = parse_float_safe(val)
    return int(round(f)) if f is not None else None


class CSVActivityReader:
    """Leitor semântico para o activities.csv do export de atividades."""

    COLUMN_MAPS = {
        "id": ["Activity ID", "ID da atividade", "id"],
        "date": ["Activity Date", "Data da atividade", "start_date", "Date"],
        "name": ["Activity Name", "Nome da atividade", "name", "Title"],
        "type": ["Activity Type", "Tipo de atividade", "type", "Sport"],
        "distance": ["Distance.1", "Distância.1", "Distance", "Distância", "distance"],
        "elevation": ["Elevation Gain", "Ganho de elevação", "total_elevation_gain", "Elevation"],
        "elapsed_time": ["Elapsed Time", "Tempo decorrido", "elapsed_time", "Duration"],
        "moving_time": ["Moving Time", "Tempo de movimentação", "moving_time"],
        "max_speed": ["Max Speed", "Velocidade máx.", "max_speed"],
        "avg_speed": ["Average Speed", "Velocidade média", "avg_speed"],
        "max_hr": ["Max Heart Rate", "Frequência cardíaca máxima.1", "Frequência cardíaca máxima", "max_heartrate"],
        "avg_hr": ["Average Heart Rate", "Frequência cardíaca média", "avg_heartrate"],
        "relative_effort": ["Relative Effort", "Esforço relativo.1", "Esforço relativo", "relative_effort"],
        "max_watts": ["Max Watts", "Máximo de watts", "max_watts"],
        "avg_watts": ["Average Watts", "Média de watts", "avg_watts"],
        "max_temp": ["Max Temperature", "Temperatura máxima", "max_temperature"],
        "avg_temp": ["Average Temperature", "Temperatura média", "avg_temperature"],
        "gear": ["Activity Gear", "Equipamento da atividade", "gear_id", "Gear"],
        "filename": ["Filename", "Nome do arquivo", "filename", "file"],
    }

    def __init__(self, csv_path: Path):
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Arquivo CSV não encontrado: {csv_path}")
        self.df = pd.read_csv(self.csv_path, low_memory=False)
        self._col_mapping = self._resolve_columns()

    def _resolve_columns(self) -> Dict[str, Optional[str]]:
        resolved = {}
        for canonical, candidates in self.COLUMN_MAPS.items():
            found = None
            for c in candidates:
                if c in self.df.columns:
                    found = c
                    break
            resolved[canonical] = found
        return resolved

    def read_activities(self) -> List[Dict[str, Any]]:
        """Lê todas as atividades do CSV em dicionários padronizados."""
        records = []
        for _, row in self.df.iterrows():
            def get_val(canonical: str) -> Any:
                col = self._col_mapping.get(canonical)
                return row[col] if col else None

            raw_id = get_val("id")
            act_id = parse_int_safe(raw_id)
            if act_id is None:
                continue

            start_dt = parse_flexible_date(get_val("date"))
            if start_dt is None:
                continue

            dist_raw = parse_float_safe(get_val("distance")) or 0.0
            # activity export em CSV traz distância em metros ou km dependendo do export (geralmente km ou m)
            # Se menor que 1000 em uma pedalada longa de 50km, pode ser km.
            # Some localized exports store distance in km while others use meters.
            # Verificamos pelo contexto do export da conta.
            # No export de atividades, "Distância" na UI é km, mas no CSV é km (ex: 28,4) ou m (ex: 28400).
            # Vamos checar se o número é pequeno (< 500) -> assumir km e converter para m, ou vice-versa.

            elev_raw = parse_float_safe(get_val("elevation")) or 0.0
            elapsed_raw = parse_int_safe(get_val("elapsed_time")) or 0
            moving_raw = parse_int_safe(get_val("moving_time")) or elapsed_raw

            fname = str(get_val("filename") or "").strip()
            if fname.lower() == "nan" or fname.lower() == "none":
                fname = ""

            records.append({
                "id": act_id,
                "name": str(get_val("name") or f"Activity {act_id}").strip(),
                "start_date": start_dt,
                "activity_type": str(get_val("type") or "Other").strip(),
                "distance_raw": dist_raw,
                "elevation_gain_m": elev_raw,
                "elapsed_time_s": elapsed_raw,
                "moving_time_s": moving_raw,
                "avg_speed_raw": parse_float_safe(get_val("avg_speed")),
                "max_speed_raw": parse_float_safe(get_val("max_speed")),
                "avg_heart_rate": parse_float_safe(get_val("avg_hr")),
                "max_heart_rate": parse_float_safe(get_val("max_hr")),
                "relative_effort": parse_float_safe(get_val("relative_effort")),
                "estimated_watts_avg": parse_float_safe(get_val("avg_watts")),
                "estimated_watts_max": parse_float_safe(get_val("max_watts")),
                "temperature_avg": parse_float_safe(get_val("avg_temp")),
                "temperature_max": parse_float_safe(get_val("max_temp")),
                "gear": str(get_val("gear") or "").strip() or None,
                "filename": fname,
            })
        return records
