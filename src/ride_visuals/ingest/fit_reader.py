"""Leitor lossless de arquivos FIT (.fit / .fit.gz) usando fitdecode."""

import gzip
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import fitdecode

from ride_visuals.model.trackpoint import TrackPoint


def _semicircles_to_degrees(val: Optional[float]) -> Optional[float]:
    if val is None:
        return None
    if abs(val) > 180.0:
        return float(val * (180.0 / (2**31)))
    return float(val)


class FITReader:
    """Extrai trackpoints e metadados de arquivos FIT sem perda de telemetria."""

    @staticmethod
    def read_fit(file_path: Path) -> Tuple[List[TrackPoint], Dict[str, Any]]:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Arquivo FIT não encontrado: {file_path}")

        raw_bytes = file_path.read_bytes()
        if file_path.name.endswith(".gz") or raw_bytes[:2] == b"\x1f\x8b":
            raw_bytes = gzip.decompress(raw_bytes)

        points: List[TrackPoint] = []
        metadata: Dict[str, Any] = {
            "laps": [],
            "session": {},
            "has_hr": False,
            "has_speed": False,
            "has_temp": False,
            "has_power": False,
            "has_cadence": False,
        }

        with fitdecode.FitReader(io.BytesIO(raw_bytes)) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue

                if frame.name == "record":
                    lat_raw = frame.get_value("position_lat", fallback=None)
                    lon_raw = frame.get_value("position_long", fallback=None)
                    ts = frame.get_value("timestamp", fallback=None)

                    # Se não houver posição geográfica, ignoramos o ponto no traçado GPS
                    if lat_raw is None or lon_raw is None or ts is None:
                        continue

                    lat = _semicircles_to_degrees(lat_raw)
                    lon = _semicircles_to_degrees(lon_raw)
                    if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
                        continue

                    if isinstance(ts, datetime):
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    else:
                        continue

                    alt = frame.get_value("altitude", fallback=None)
                    if alt is not None:
                        alt = float(alt)

                    dist = frame.get_value("distance", fallback=None)
                    if dist is not None:
                        dist = float(dist)

                    # Velocidade: prefere enhanced_speed, depois speed (em m/s)
                    spd = frame.get_value("enhanced_speed", fallback=None)
                    if spd is None:
                        spd = frame.get_value("speed", fallback=None)
                    prov_spd = "none"
                    if spd is not None:
                        spd = float(spd)
                        prov_spd = "measured"
                        metadata["has_speed"] = True

                    # Frequência Cardíaca
                    hr = frame.get_value("heart_rate", fallback=None)
                    if hr is not None:
                        hr = float(hr)
                        metadata["has_hr"] = True

                    # Potência
                    pwr = frame.get_value("power", fallback=None)
                    prov_pwr = "none"
                    if pwr is not None:
                        pwr = float(pwr)
                        prov_pwr = "measured"
                        metadata["has_power"] = True

                    # Cadência
                    cad = frame.get_value("cadence", fallback=None)
                    if cad is not None:
                        cad = float(cad)
                        metadata["has_cadence"] = True

                    # Temperatura
                    temp = frame.get_value("temperature", fallback=None)
                    prov_tmp = "none"
                    if temp is not None:
                        temp = float(temp)
                        prov_tmp = "sensor"
                        metadata["has_temp"] = True

                    points.append(TrackPoint(
                        timestamp=ts,
                        lat=lat,
                        lon=lon,
                        altitude=alt,
                        distance_m=dist,
                        speed_mps=spd,
                        heart_rate_bpm=hr,
                        power_watts=pwr,
                        cadence_rpm=cad,
                        temperature_c=temp,
                        grade_pct=None,
                        bearing_deg=None,
                        provenance_speed=prov_spd,
                        provenance_power=prov_pwr,
                        provenance_temp=prov_tmp,
                        quality_flags="ok",
                    ))

                elif frame.name == "lap":
                    lap_data = {}
                    for field in frame.fields:
                        if field.value is not None:
                            lap_data[field.name] = field.value
                    metadata["laps"].append(lap_data)

                elif frame.name == "session":
                    for field in frame.fields:
                        if field.value is not None:
                            metadata["session"][field.name] = field.value

        return points, metadata
