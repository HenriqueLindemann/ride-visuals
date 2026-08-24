"""Leitor lossless de arquivos GPX (.gpx / .gpx.gz) preservando extensões Garmin."""

import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Any
import gpxpy
import dateutil.parser

from ride_visuals.model.trackpoint import TrackPoint


class GPXReader:
    """Extrai trackpoints de arquivos GPX preservando extensões de telemetria."""

    @staticmethod
    def _strip_ns(tag: str) -> str:
        return tag.split("}", 1)[1] if "}" in tag else tag

    @classmethod
    def read_gpx(cls, file_path: Path) -> Tuple[List[TrackPoint], Dict[str, Any]]:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Arquivo GPX não encontrado: {file_path}")

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

        # Parse via XML etree para extração direta e segura de extensões
        try:
            root = ET.fromstring(raw_bytes)
        except Exception:
            # Fallback usando gpxpy
            gpx = gpxpy.parse(raw_bytes.decode("utf-8", errors="replace"))
            for track in gpx.tracks:
                for seg in track.segments:
                    for pt in seg.points:
                        ts = pt.time
                        if ts and ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        points.append(TrackPoint(
                            timestamp=ts or datetime.now(timezone.utc),
                            lat=pt.latitude,
                            lon=pt.longitude,
                            altitude=pt.elevation,
                            distance_m=None,
                            speed_mps=pt.speed,
                            heart_rate_bpm=None,
                            power_watts=None,
                            cadence_rpm=None,
                            temperature_c=None,
                            provenance_speed="measured" if pt.speed is not None else "none",
                            provenance_power="none",
                            provenance_temp="none",
                            quality_flags="ok",
                        ))
            return points, metadata

        # Iterar sobre todos os trkpt
        for pt in root.iter():
            if cls._strip_ns(pt.tag) != "trkpt":
                continue

            lat_attr = pt.get("lat")
            lon_attr = pt.get("lon")
            if not lat_attr or not lon_attr:
                continue

            try:
                lat = float(lat_attr)
                lon = float(lon_attr)
            except ValueError:
                continue

            if abs(lat) > 90 or abs(lon) > 180:
                continue

            time_elem = None
            ele_elem = None
            hr_val = None
            speed_val = None
            temp_val = None
            cad_val = None
            power_val = None

            for child in pt:
                tag = cls._strip_ns(child.tag)
                if tag == "time":
                    time_elem = child
                elif tag == "ele":
                    ele_elem = child
                elif tag == "extensions":
                    for ext_elem in child.iter():
                        ext_tag = cls._strip_ns(ext_elem.tag).lower()
                        if ext_tag in ("hr", "heartrate", "heart_rate") and ext_elem.text:
                            try:
                                hr_val = float(ext_elem.text.strip())
                                metadata["has_hr"] = True
                            except ValueError:
                                pass
                        elif ext_tag == "speed" and ext_elem.text:
                            try:
                                speed_val = float(ext_elem.text.strip())
                                metadata["has_speed"] = True
                            except ValueError:
                                pass
                        elif ext_tag in ("atemp", "temp", "temperature") and ext_elem.text:
                            try:
                                temp_val = float(ext_elem.text.strip())
                                metadata["has_temp"] = True
                            except ValueError:
                                pass
                        elif ext_tag in ("cad", "cadence") and ext_elem.text:
                            try:
                                cad_val = float(ext_elem.text.strip())
                                metadata["has_cadence"] = True
                            except ValueError:
                                pass
                        elif ext_tag in ("power", "watts") and ext_elem.text:
                            try:
                                power_val = float(ext_elem.text.strip())
                                metadata["has_power"] = True
                            except ValueError:
                                pass

            if time_elem is None or not time_elem.text:
                continue

            try:
                ts = dateutil.parser.isoparse(time_elem.text.strip())
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)
            except Exception:
                continue

            ele = None
            if ele_elem is not None and ele_elem.text:
                try:
                    ele = float(ele_elem.text.strip())
                except ValueError:
                    pass

            prov_spd = "measured" if speed_val is not None else "none"
            prov_pwr = "unknown" if power_val is not None else "none"
            prov_tmp = "sensor" if temp_val is not None else "none"

            points.append(TrackPoint(
                timestamp=ts,
                lat=lat,
                lon=lon,
                altitude=ele,
                distance_m=None,
                speed_mps=speed_val,
                heart_rate_bpm=hr_val,
                power_watts=power_val,
                cadence_rpm=cad_val,
                temperature_c=temp_val,
                grade_pct=None,
                bearing_deg=None,
                provenance_speed=prov_spd,
                provenance_power=prov_pwr,
                provenance_temp=prov_tmp,
                quality_flags="ok",
            ))

        return points, metadata
