"""Leitor lossless de arquivos TCX (.tcx / .tcx.gz) preservando HR, velocidade e potência estimada."""

import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import dateutil.parser

from ride_visuals.model.trackpoint import TrackPoint


class TCXReader:
    """Extrai trackpoints e metadados de arquivos TCX sem perda de telemetria."""

    @staticmethod
    def _strip_ns(tag: str) -> str:
        return tag.split("}", 1)[1] if "}" in tag else tag

    @classmethod
    def read_tcx(cls, file_path: Path) -> Tuple[List[TrackPoint], Dict[str, Any]]:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Arquivo TCX não encontrado: {file_path}")

        raw_bytes = file_path.read_bytes()
        if file_path.name.endswith(".gz") or raw_bytes[:2] == b"\x1f\x8b":
            raw_bytes = gzip.decompress(raw_bytes)

        points: List[TrackPoint] = []
        metadata: Dict[str, Any] = {
            "has_hr": False,
            "has_speed": False,
            "has_temp": False,
            "has_power": False,
            "has_cadence": False,
        }

        try:
            root = ET.fromstring(raw_bytes)
        except Exception as e:
            # Fallback para parsing tolerante
            raise ValueError(f"Falha ao interpretar XML TCX em {file_path.name}: {e}")

        # Iterar sobre todos os Trackpoints
        for tp in root.iter():
            if cls._strip_ns(tp.tag) != "Trackpoint":
                continue

            time_elem = None
            pos_elem = None
            alt_elem = None
            dist_elem = None
            hr_elem = None
            cad_elem = None
            speed_elem = None
            watts_elem = None

            for child in tp:
                tag = cls._strip_ns(child.tag)
                if tag == "Time":
                    time_elem = child
                elif tag == "Position":
                    pos_elem = child
                elif tag == "AltitudeMeters":
                    alt_elem = child
                elif tag == "DistanceMeters":
                    dist_elem = child
                elif tag == "HeartRateBpm":
                    val = child.find("{*}Value") if child.find("{*}Value") is not None else child.find("Value")
                    hr_elem = val if val is not None else child
                elif tag == "Cadence":
                    cad_elem = child
                elif tag == "Extensions":
                    for ext_child in child.iter():
                        ext_tag = cls._strip_ns(ext_child.tag)
                        if ext_tag == "Speed":
                            speed_elem = ext_child
                        elif ext_tag == "Watts":
                            watts_elem = ext_child

            if pos_elem is None or time_elem is None or not time_elem.text:
                continue

            lat_elem = None
            lon_elem = None
            for p_child in pos_elem:
                p_tag = cls._strip_ns(p_child.tag)
                if p_tag == "LatitudeDegrees":
                    lat_elem = p_child
                elif p_tag == "LongitudeDegrees":
                    lon_elem = p_child

            if lat_elem is None or lon_elem is None or not lat_elem.text or not lon_elem.text:
                continue

            try:
                lat = float(lat_elem.text.strip())
                lon = float(lon_elem.text.strip())
            except ValueError:
                continue

            if abs(lat) > 90 or abs(lon) > 180:
                continue

            try:
                ts = dateutil.parser.isoparse(time_elem.text.strip())
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)
            except Exception:
                continue

            alt = None
            if alt_elem is not None and alt_elem.text:
                try:
                    alt = float(alt_elem.text.strip())
                except ValueError:
                    pass

            dist = None
            if dist_elem is not None and dist_elem.text:
                try:
                    dist = float(dist_elem.text.strip())
                except ValueError:
                    pass

            hr = None
            if hr_elem is not None and hr_elem.text:
                try:
                    hr = float(hr_elem.text.strip())
                    metadata["has_hr"] = True
                except ValueError:
                    pass

            cad = None
            if cad_elem is not None and cad_elem.text:
                try:
                    cad = float(cad_elem.text.strip())
                    metadata["has_cadence"] = True
                except ValueError:
                    pass

            spd = None
            prov_spd = "none"
            if speed_elem is not None and speed_elem.text:
                try:
                    spd = float(speed_elem.text.strip())
                    prov_spd = "measured"
                    metadata["has_speed"] = True
                except ValueError:
                    pass

            watts = None
            prov_pwr = "none"
            if watts_elem is not None and watts_elem.text:
                try:
                    watts = float(watts_elem.text.strip())
                    # Watts em TCX sem medidor de potência confirmado são estimados pela plataforma de origem
                    prov_pwr = "provider_estimated"
                    metadata["has_power"] = True
                except ValueError:
                    pass

            points.append(TrackPoint(
                timestamp=ts,
                lat=lat,
                lon=lon,
                altitude=alt,
                distance_m=dist,
                speed_mps=spd,
                heart_rate_bpm=hr,
                power_watts=watts,
                cadence_rpm=cad,
                temperature_c=None,
                grade_pct=None,
                bearing_deg=None,
                provenance_speed=prov_spd,
                provenance_power=prov_pwr,
                provenance_temp="none",
                quality_flags="ok",
            ))

        return points, metadata
