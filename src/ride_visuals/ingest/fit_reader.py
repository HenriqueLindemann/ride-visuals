"""Lossless reader for FIT files (.fit / .fit.gz) using fitdecode."""

import gzip
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import fitdecode

from ride_visuals.model.trackpoint import TrackPoint


_SEMICIRCLE_TO_DEGREES = 180.0 / (2**31)


def _positions_are_semicircles(raw_bytes: bytes) -> bool:
    """Decide once per file whether coordinates are semicircles or degrees.

    FIT specifies semicircles, but some exporters write degrees. A per-sample
    threshold misreads a ride crossing the equator or prime meridian, where a
    genuinely semicircle-encoded coordinate can be small; the largest
    magnitude in the file disambiguates both encodings reliably.
    """
    largest = 0.0
    with fitdecode.FitReader(io.BytesIO(raw_bytes)) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage) or frame.name != "record":
                continue
            for field_name in ("position_lat", "position_long"):
                value = frame.get_value(field_name, fallback=None)
                if value is not None:
                    largest = max(largest, abs(float(value)))
    return largest > 180.0


def _semicircles_to_degrees(
    val: Optional[float], *, semicircles: bool | None = None
) -> Optional[float]:
    if val is None:
        return None
    if semicircles is None:
        # Without file context, values that cannot be degrees are assumed to
        # be semicircles (FIT's native unit); ambiguous near-zero values stay
        # as-is for backwards compatibility.
        semicircles = abs(val) > 180.0
    if semicircles:
        return float(val * _SEMICIRCLE_TO_DEGREES)
    return float(val)


class FITReader:
    """Extract trackpoints and metadata from FIT files without losing telemetry."""

    @staticmethod
    def read_session_metadata(file_path: Path) -> Dict[str, Any]:
        """Extract only the session message fields from a FIT file.

        Lightweight read for previews and standalone imports: it does not
        process telemetry records.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"FIT file not found: {file_path}")

        raw_bytes = file_path.read_bytes()
        if file_path.name.endswith(".gz") or raw_bytes[:2] == b"\x1f\x8b":
            raw_bytes = gzip.decompress(raw_bytes)

        session: Dict[str, Any] = {}
        with fitdecode.FitReader(io.BytesIO(raw_bytes)) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name == "session":
                    for field in frame.fields:
                        if field.value is not None:
                            session[field.name] = field.value
                    break
        return session

    @staticmethod
    def read_fit(file_path: Path) -> Tuple[List[TrackPoint], Dict[str, Any]]:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"FIT file not found: {file_path}")

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
        semicircles = _positions_are_semicircles(raw_bytes)

        with fitdecode.FitReader(io.BytesIO(raw_bytes)) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue

                if frame.name == "record":
                    lat_raw = frame.get_value("position_lat", fallback=None)
                    lon_raw = frame.get_value("position_long", fallback=None)
                    ts = frame.get_value("timestamp", fallback=None)

                    # Without a geographic position, skip the point in the GPS trace
                    if lat_raw is None or lon_raw is None or ts is None:
                        continue

                    lat = _semicircles_to_degrees(lat_raw, semicircles=semicircles)
                    lon = _semicircles_to_degrees(lon_raw, semicircles=semicircles)
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

                    # Speed: prefer enhanced_speed, then speed (in m/s)
                    spd = frame.get_value("enhanced_speed", fallback=None)
                    if spd is None:
                        spd = frame.get_value("speed", fallback=None)
                    prov_spd = "none"
                    if spd is not None:
                        spd = float(spd)
                        prov_spd = "measured"
                        metadata["has_speed"] = True

                    # Heart rate
                    hr = frame.get_value("heart_rate", fallback=None)
                    if hr is not None:
                        hr = float(hr)
                        metadata["has_hr"] = True

                    # Power
                    pwr = frame.get_value("power", fallback=None)
                    prov_pwr = "none"
                    if pwr is not None:
                        pwr = float(pwr)
                        prov_pwr = "measured"
                        metadata["has_power"] = True

                    # Cadence
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
