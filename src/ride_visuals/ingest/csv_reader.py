"""Robust activities.csv reader with multi-language Strava export support."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd


PT_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}

EN_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

ES_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

FR_MONTHS = {
    "jan": 1, "janv": 1, "fév": 2, "fev": 2, "févr": 2, "fevr": 2,
    "mar": 3, "mars": 3, "avr": 4, "mai": 5, "jun": 6, "juin": 6,
    "jul": 7, "juil": 7, "aoû": 8, "aou": 8, "août": 8, "aout": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "déc": 12, "dec": 12,
    "janvier": 1, "février": 2, "fevrier": 2, "avril": 4, "juillet": 7,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

DE_MONTHS = {
    "jan": 1, "jän": 1, "jaen": 1, "feb": 2, "mär": 3, "maer": 3, "mar": 3, "mrz": 3,
    "apr": 4, "mai": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "okt": 10, "nov": 11, "dez": 12,
    "januar": 1, "jänuar": 1, "jaenuar": 1, "februar": 2, "märz": 3, "maerz": 3,
    "april": 4, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "dezember": 12,
}

IT_MONTHS = {
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "sett": 9, "ott": 10, "nov": 11, "dic": 12,
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

NL_MONTHS = {
    "jan": 1, "feb": 2, "mrt": 3, "maa": 3, "apr": 4, "mei": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "okt": 10, "nov": 11, "dec": 12,
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}

ALL_MONTHS: Dict[str, int] = {
    **EN_MONTHS,
    **PT_MONTHS,
    **ES_MONTHS,
    **FR_MONTHS,
    **DE_MONTHS,
    **IT_MONTHS,
    **NL_MONTHS,
}


def _resolve_month(token: str) -> Optional[int]:
    cleaned = token.strip().rstrip(".").lower()
    if not cleaned:
        return None
    if cleaned in ALL_MONTHS:
        return ALL_MONTHS[cleaned]
    if len(cleaned) >= 4 and cleaned[:4] in ALL_MONTHS:
        return ALL_MONTHS[cleaned[:4]]
    return ALL_MONTHS.get(cleaned[:3])


def _apply_meridiem(hour: int, meridiem: Optional[str]) -> int:
    if not meridiem:
        return hour
    norm = re.sub(r"[\s.]", "", meridiem).lower()
    if norm == "pm" and hour < 12:
        return hour + 12
    if norm == "am" and hour == 12:
        return 0
    return hour


def parse_flexible_date(s: Any) -> Optional[datetime]:
    """Convert date strings across Strava export languages and ISO formats to UTC datetime."""
    if s is None or pd.isna(s):
        return None
    s = str(s).strip()
    if not s:
        return None

    # Day-first with named month (PT, ES, FR, DE, IT, NL, en-GB):
    # Examples:
    #   "23 de ago. de 2024, 07:18:50" (PT/ES)
    #   "23 ago. 2024, 7:18:50 p. m." (ES)
    #   "23 août 2024 à 07:18:50" (FR)
    #   "23. Aug. 2024, 07:18:50" / "23. August 2024 um 07:18:50" (DE)
    #   "23 ago 2024, 07:18:50" (IT)
    #   "23 aug. 2024 07:18:50" (NL)
    #   "23 Aug 2024, 07:18:50" (en-GB)
    m_day_first = re.search(
        r"(\d{1,2})\.?\s+(?:de\s+|d['’])?([^\W\d_]+)\.?\s+(?:de\s+|del\s+)?(\d{4})"
        r"(?:[,\s]+(?:à|um|alle|om)?\s*)(\d{1,2}):(\d{2}):(\d{2})\s*([ap]\.?\s*m\.?)?",
        s,
        re.IGNORECASE,
    )
    if m_day_first:
        day, mon_str, year, hr, mn, sc, meridiem = m_day_first.groups()
        mon = _resolve_month(mon_str)
        if mon is not None:
            hour = _apply_meridiem(int(hr), meridiem)
            return datetime(int(year), mon, int(day), hour, int(mn), int(sc), tzinfo=timezone.utc)

    # Month-first with named month (en-US):
    # Examples: "Aug 23, 2024, 7:18:50 PM" or "August 23, 2024, 19:18:50"
    m_month_first = re.search(
        r"([^\W\d_]+)\.?\s+(\d{1,2}),?\s+(\d{4})[,\s]+(\d{1,2}):(\d{2}):(\d{2})\s*([ap]\.?\s*m\.?)?",
        s,
        re.IGNORECASE,
    )
    if m_month_first:
        mon_str, day, year, hr, mn, sc, meridiem = m_month_first.groups()
        mon = _resolve_month(mon_str)
        if mon is not None:
            hour = _apply_meridiem(int(hr), meridiem)
            return datetime(int(year), mon, int(day), hour, int(mn), int(sc), tzinfo=timezone.utc)

    # Numeric DD.MM.YYYY or DD/MM/YYYY with time (DE, FR, IT, NL, PT, ES):
    m_num = re.match(
        r"^(\d{1,2})([./])(\d{1,2})\2(\d{4})(?:[,\s]+(?:à|um|alle|om)?\s*)"
        r"(\d{1,2}):(\d{2}):(\d{2})\s*([ap]\.?\s*m\.?)?$",
        s,
        re.IGNORECASE,
    )
    if m_num:
        first_s, _sep, second_s, year, hr, mn, sc, meridiem = m_num.groups()
        first, second = int(first_s), int(second_s)
        if first <= 12 and second > 12:
            mon, day = first, second
        else:
            day, mon = first, second
        if 1 <= mon <= 12 and 1 <= day <= 31:
            hour = _apply_meridiem(int(hr), meridiem)
            return datetime(int(year), mon, day, hour, int(mn), int(sc), tzinfo=timezone.utc)

    # ISO format or pandas default
    try:
        dt = pd.to_datetime(s, utc=True)
        if pd.notna(dt):
            return dt.to_pydatetime()
    except Exception:
        pass

    return None


def parse_float_safe(val: Any) -> Optional[float]:
    """Convert numbers with comma or dot decimal separators to float safely."""
    if val is None or pd.isna(val):
        return None
    s = re.sub(r"[\s\u00a0\u202f]+", "", str(val))
    if not s or s.lower() in ("nan", "none"):
        return None
    try:
        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
        return float(s)
    except ValueError:
        return None


def parse_int_safe(val: Any) -> Optional[int]:
    """Convert integers safely."""
    f = parse_float_safe(val)
    return int(round(f)) if f is not None else None


def _normalize_col_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).replace("’", "'").strip()).lower()


class CSVActivityReader:
    """Semantic reader for the activity export's activities.csv across languages."""

    COLUMN_MAPS = {
        "id": [
            "Activity ID", "ID da atividade", "ID de actividad", "ID de l'activité",
            "Identifiant de l'activité", "Aktivitäts-ID", "ID attività", "Activiteit-ID", "id",
        ],
        "date": [
            "Activity Date", "Data da atividade", "Fecha de la actividad", "Date de l'activité",
            "Aktivitätsdatum", "Data attività", "Activiteitsdatum", "Datum van activiteit",
            "start_date", "Date",
        ],
        "name": [
            "Activity Name", "Nome da atividade", "Nombre de la actividad", "Nom de l'activité",
            "Name der Aktivität", "Aktivitätsname", "Nome attività", "Naam van activiteit",
            "Activiteitsnaam", "name", "Title",
        ],
        "type": [
            "Activity Type", "Tipo de atividade", "Tipo de actividad", "Type d'activité",
            "Aktivitätsart", "Tipo di attività", "Activiteitstype", "Type activiteit",
            "type", "Sport",
        ],
        "distance": [
            "Distance.1", "Distância.1", "Distancia.1", "Distanz.1", "Distanza.1", "Afstand.1",
            "Distance", "Distância", "Distancia", "Distanz", "Distanza", "Afstand", "distance",
        ],
        "elevation": [
            "Elevation Gain", "Ganho de elevação", "Desnivel positivo", "Ganancia de elevación",
            "Dénivelé positif", "Gain d'altitude", "Höhenzunahme", "Dislivello positivo",
            "Guadagno di quota", "Hoogteverschil", "Hoogtewinst", "total_elevation_gain",
            "Elevation",
        ],
        "elapsed_time": [
            "Elapsed Time", "Tempo decorrido", "Tiempo transcurrido", "Temps écoulé",
            "Verstrichene Zeit", "Tempo trascorso", "Verstreken tijd", "elapsed_time", "Duration",
        ],
        "moving_time": [
            "Moving Time", "Tempo de movimentação", "Tiempo en movimiento", "Temps de déplacement",
            "Bewegungszeit", "Tempo in movimento", "Beweegtijd", "Tijd in beweging", "moving_time",
        ],
        "max_speed": [
            "Max Speed", "Velocidade máx.", "Velocidad máxima", "Velocidad máx.", "Vitesse max.",
            "Vitesse maximale", "Höchstgeschw.", "Höchstgeschwindigkeit", "Max. Geschwindigkeit",
            "Velocità max", "Velocità massima", "Max. snelheid", "Maximale snelheid", "max_speed",
        ],
        "avg_speed": [
            "Average Speed", "Velocidade média", "Velocidad media", "Velocidad promedio",
            "Vitesse moyenne", "Durchschnittliche Geschwindigkeit", "Ø Geschwindigkeit",
            "Velocità media", "Gemiddelde snelheid", "avg_speed",
        ],
        "max_hr": [
            "Max Heart Rate.1", "Max Heart Rate", "Frequência cardíaca máxima.1",
            "Frequência cardíaca máxima", "Frecuencia cardíaca máxima.1",
            "Frecuencia cardíaca máxima", "Fréquence cardiaque max..1",
            "Fréquence cardiaque max.", "Fréquence cardiaque maximale.1",
            "Fréquence cardiaque maximale", "Max. Herzfrequenz.1", "Maximale Herzfrequenz.1",
            "Maximale Herzfrequenz", "Max. Herzfrequenz", "Frequenza cardiaca max.1",
            "Frequenza cardiaca max", "Frequenza cardiaca massima.1",
            "Frequenza cardiaca massima", "Max. hartslag.1", "Max. hartslag",
            "Maximale hartslag.1", "Maximale hartslag", "max_heartrate",
        ],
        "avg_hr": [
            "Average Heart Rate", "Frequência cardíaca média", "Frecuencia cardíaca media",
            "Frecuencia cardíaca promedio", "Fréquence cardiaque moyenne",
            "Durchschnittliche Herzfrequenz", "Ø Herzfrequenz", "Frequenza cardiaca media",
            "Gemiddelde hartslag", "avg_heartrate",
        ],
        "relative_effort": [
            "Relative Effort", "Esforço relativo.1", "Esforço relativo", "Esfuerzo relativo.1",
            "Esfuerzo relativo", "Effort relatif.1", "Effort relatif", "Relative Leistung.1",
            "Relative Leistung", "Sforzo relativo.1", "Sforzo relativo",
            "Relatieve inspanning.1", "Relatieve inspanning", "relative_effort",
        ],
        "max_watts": [
            "Max Watts", "Máximo de watts", "Vatios máximos", "Vatios máx.", "Puissance max.",
            "Watts max.", "Maximale Watt", "Max. Watt", "Watt max", "Watt massimi",
            "Max. vermogen", "Maximaal wattage", "max_watts",
        ],
        "avg_watts": [
            "Average Watts", "Média de watts", "Vatios medios", "Promedio de vatios",
            "Puissance moyenne", "Watts moyens", "Durchschnittliche Watt", "Ø Watt",
            "Watt medi", "Gemiddeld vermogen", "Gemiddeld wattage", "avg_watts",
        ],
        "max_temp": [
            "Max Temperature", "Temperatura máxima", "Temperatura máx.", "Température max.",
            "Température maximale", "Maximale Temperatur", "Max. Temperatur", "Temperatura max",
            "Max. temperatuur", "Maximale temperatuur", "max_temperature",
        ],
        "avg_temp": [
            "Average Temperature", "Temperatura média", "Temperatura media",
            "Temperatura promedio", "Température moyenne", "Durchschnittstemperatur",
            "Ø Temperatur", "Gemiddelde temperatuur", "avg_temperature",
        ],
        "gear": [
            "Activity Gear", "Equipamento da atividade", "Equipamiento de la actividad",
            "Material de la actividad", "Équipement de l'activité", "Matériel de l'activité",
            "Aktivitätsausrüstung", "Ausrüstung", "Attrezzatura attività",
            "Uitrusting voor activiteit", "gear_id", "Gear",
        ],
        "filename": [
            "Filename", "Nome do arquivo", "Nome do ficheiro", "Nombre del archivo",
            "Nom du fichier", "Dateiname", "Nome file", "Bestandsnaam", "filename", "file",
        ],
    }

    STRAVA_EXPORT_COLUMN_INDICES = {
        "id": 0,
        "date": 1,
        "name": 2,
        "type": 3,
        "elapsed_time": 5,
        "gear": 11,
        "filename": 12,
        "moving_time": 16,
        "distance": 17,
        "max_speed": 18,
        "avg_speed": 19,
        "elevation": 20,
        "max_hr": 30,
        "avg_hr": 31,
        "max_watts": 32,
        "avg_watts": 33,
        "max_temp": 35,
        "avg_temp": 36,
        "relative_effort": 37,
    }

    def __init__(self, csv_path: Path):
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        self.df = pd.read_csv(self.csv_path, low_memory=False)
        self._col_mapping = self._resolve_columns()

    def _is_strava_export_layout(self) -> bool:
        cols = list(self.df.columns)
        return (
            len(cols) >= 38
            and cols[15] == f"{cols[5]}.1"
            and cols[17] == f"{cols[6]}.1"
        )

    def _resolve_columns(self) -> Dict[str, Optional[str]]:
        resolved: Dict[str, Optional[str]] = {}
        cols = list(self.df.columns)
        is_strava_layout = self._is_strava_export_layout()
        normalized_df_cols = {_normalize_col_name(col): col for col in cols}
        for canonical, candidates in self.COLUMN_MAPS.items():
            found = None
            for c in candidates:
                if c in self.df.columns:
                    found = c
                    break
                norm_c = _normalize_col_name(c)
                if norm_c in normalized_df_cols:
                    found = normalized_df_cols[norm_c]
                    break
            if found is None and is_strava_layout:
                idx = self.STRAVA_EXPORT_COLUMN_INDICES.get(canonical)
                if idx is not None and idx < len(cols):
                    found = cols[idx]
            resolved[canonical] = found
        return resolved

    def read_activities(self) -> List[Dict[str, Any]]:
        """Read every activity from the CSV into standardized dictionaries."""
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
            # CSV summary distance is in km in some exports and in meters in
            # others, depending on the export language. Keep the raw value; the
            # pipeline interprets it as kilometers when no GPS stream is available.

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
