"""Cálculo e derivação de métricas de telemetria (distância, velocidade, inclinação, bearing)."""

import math
from typing import List

from ride_visuals.model.trackpoint import TrackPoint


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula a distância ortodrômica em metros entre dois pares (lat, lon) em graus."""
    R = 6371000.0  # Raio da Terra em metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula o rumo (bearing) em graus (0–360) do ponto 1 para o ponto 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def enrich_trackpoints(points: List[TrackPoint]) -> List[TrackPoint]:
    """Enriquece uma lista de trackpoints derivando distância, velocidade, inclinação e rumo."""
    if not points:
        return []

    # Ordenar por timestamp
    points.sort(key=lambda p: p.timestamp)

    cum_dist = 0.0
    enriched: List[TrackPoint] = []

    for i, pt in enumerate(points):
        if i == 0:
            p_dist = pt.distance_m if pt.distance_m is not None else 0.0
            cum_dist = p_dist
            p_spd = pt.speed_mps
            prov_spd = pt.provenance_speed
            if p_spd is None:
                p_spd = 0.0
                prov_spd = "derived"

            enriched.append(TrackPoint(
                timestamp=pt.timestamp,
                lat=pt.lat,
                lon=pt.lon,
                altitude=pt.altitude,
                distance_m=cum_dist,
                speed_mps=p_spd,
                heart_rate_bpm=pt.heart_rate_bpm,
                power_watts=pt.power_watts,
                cadence_rpm=pt.cadence_rpm,
                temperature_c=pt.temperature_c,
                grade_pct=0.0,
                bearing_deg=0.0,
                provenance_speed=prov_spd,
                provenance_power=pt.provenance_power,
                provenance_temp=pt.provenance_temp,
                quality_flags=pt.quality_flags,
            ))
            continue

        prev = enriched[i - 1]
        dt = (pt.timestamp - prev.timestamp).total_seconds()
        d_dist = haversine_distance(prev.lat, prev.lon, pt.lat, pt.lon)

        # Atualizar distância acumulada se não fornecida nativamente
        if pt.distance_m is not None and pt.distance_m >= cum_dist:
            cum_dist = pt.distance_m
        else:
            cum_dist += d_dist

        # Velocidade: preserva medida se existir; caso contrário deriva
        spd = pt.speed_mps
        prov_spd = pt.provenance_speed
        if spd is None or prov_spd == "none":
            if dt > 0.001:
                spd = d_dist / dt
                prov_spd = "derived"
            else:
                spd = prev.speed_mps or 0.0
                prov_spd = "derived"

        # Sanity check para outliers absurdos de velocidade (> 40 m/s ou 144 km/h em ciclismo)
        quality = pt.quality_flags
        if spd is not None and spd > 40.0:
            quality = "gps_glitch"

        # Inclinação (%)
        grade = None
        if pt.altitude is not None and prev.altitude is not None and d_dist > 2.0:
            d_alt = pt.altitude - prev.altitude
            grade = (d_alt / d_dist) * 100.0
            # Limitar a -40% a +40%
            grade = max(-40.0, min(40.0, grade))

        # Bearing
        bearing = calculate_bearing(prev.lat, prev.lon, pt.lat, pt.lon) if d_dist > 0.5 else prev.bearing_deg

        enriched.append(TrackPoint(
            timestamp=pt.timestamp,
            lat=pt.lat,
            lon=pt.lon,
            altitude=pt.altitude,
            distance_m=cum_dist,
            speed_mps=spd,
            heart_rate_bpm=pt.heart_rate_bpm,
            power_watts=pt.power_watts,
            cadence_rpm=pt.cadence_rpm,
            temperature_c=pt.temperature_c,
            grade_pct=grade,
            bearing_deg=bearing,
            provenance_speed=prov_spd,
            provenance_power=pt.provenance_power,
            provenance_temp=pt.provenance_temp,
            quality_flags=quality,
        ))

    return enriched
