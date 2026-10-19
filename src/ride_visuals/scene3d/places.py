"""Gazetteer lookups and spherical helpers for 3D scene storytelling.

Start places come from GeoNames ``cities15000`` (CC BY 4.0, every town with
15,000+ inhabitants), which is dense enough to name where most rides begin.
Destinations come from Natural Earth's 10m populated places (public domain),
with GeoNames backing smaller towns passed to ``--toward`` and start places
when one gazetteer is unavailable. Both are cached locally on first use. When
running offline without a cached copy, every lookup degrades gracefully to
``None`` so renders still succeed with distance-only copy.
"""

from __future__ import annotations

import io
import json
import math
import urllib.request
import zipfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ride_visuals.scene3d.tiles import USER_AGENT
from ride_visuals.scene3d.track import EARTH_RADIUS_M, haversine_m

NATURALEARTH_PLACES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_populated_places_simple.geojson"
)
GEONAMES_TOWNS_URL = "https://download.geonames.org/export/dump/cities15000.zip"
DEFAULT_PLACES_CACHE_DIR = Path("data/cache/places")
PLACES_FILENAME = "ne_10m_populated_places_simple.geojson"
TOWNS_FILENAME = "cities15000.txt"
# GeoNames feature codes for city sections and historical/abandoned places.
TOWN_POPULATION_PULL_KM = 4.0
SKIPPED_TOWN_CODES = frozenset({"PPLX", "PPLH", "PPLQ", "PPLW", "PPLCH"})


@dataclass(frozen=True)
class Place:
    """One populated place; ``source`` is its credits key (None for raw coordinates)."""

    name: str
    name_ascii: str
    country: str
    lon: float
    lat: float
    pop_max: int
    scalerank: int
    source: str | None = "natural-earth"


@dataclass(frozen=True)
class PlaceMatch:
    """A resolved place together with its distance and bearing from an origin."""

    place: Place
    distance_m: float
    bearing_deg: float


_MEMORY_CACHE: dict[tuple[Path, int], tuple[Place, ...]] = {}


def _fetch(url: str, target: Path, extract: str | None = None) -> bool:
    """Download ``url`` into ``target`` atomically (optionally one member of a zip)."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = response.read()
        if extract is not None:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                payload = archive.read(extract)
    except (OSError, KeyError, zipfile.BadZipFile):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(payload)
    partial.replace(target)
    return True


def great_circle_bearing(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial compass bearing (0..360) from (lon1, lat1) to (lon2, lat2)."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360.0


def great_circle_destination(
    lon: float,
    lat: float,
    bearing_deg: float,
    distance_m: float,
) -> tuple[float, float]:
    """Destination (lon, lat) at ``distance_m`` along ``bearing_deg``."""
    d = distance_m / EARTH_RADIUS_M
    b = math.radians(bearing_deg)
    p1 = math.radians(lat)
    l1 = math.radians(lon)
    sin_p2 = math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b)
    p2 = math.asin(max(-1.0, min(1.0, sin_p2)))
    l2 = l1 + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(p1),
        math.cos(d) - math.sin(p1) * math.sin(p2),
    )
    return ((math.degrees(l2) + 540.0) % 360.0) - 180.0, math.degrees(p2)


def load_places(
    cache_dir: Path = DEFAULT_PLACES_CACHE_DIR,
    *,
    offline: bool = False,
) -> tuple[Place, ...]:
    """Load the Natural Earth gazetteer from disk or fetch it once."""
    target = Path(cache_dir).resolve() / PLACES_FILENAME
    if not target.exists() and not offline and not _fetch(NATURALEARTH_PLACES_URL, target):
        return ()
    if not target.exists():
        return ()
    cache_key = (target, target.stat().st_mtime_ns)
    if cache_key in _MEMORY_CACHE:
        return _MEMORY_CACHE[cache_key]
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        places: list[Place] = []
        for feature in raw.get("features", ()):
            geom = feature.get("geometry") or {}
            coords = geom.get("coordinates")
            props = feature.get("properties") or {}
            if not coords or len(coords) < 2:
                continue
            name = str(props.get("name") or props.get("nameascii") or "").strip()
            if not name:
                continue
            name_ascii = str(props.get("nameascii") or name).strip()
            places.append(
                Place(
                    name=name,
                    name_ascii=name_ascii,
                    country=str(props.get("adm0name") or "").strip(),
                    lon=float(coords[0]),
                    lat=float(coords[1]),
                    pop_max=int(props.get("pop_max") or 0),
                    scalerank=int(props.get("scalerank") if props.get("scalerank") is not None else 10),
                )
            )
        result = tuple(places)
        _MEMORY_CACHE[cache_key] = result
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def load_towns(
    cache_dir: Path = DEFAULT_PLACES_CACHE_DIR,
    *,
    offline: bool = False,
) -> tuple[Place, ...]:
    """Load GeoNames ``cities15000`` (tab-separated) from disk or fetch it once."""
    target = Path(cache_dir).resolve() / TOWNS_FILENAME
    if not target.exists() and not offline and not _fetch(GEONAMES_TOWNS_URL, target, TOWNS_FILENAME):
        return ()
    if not target.exists():
        return ()
    cache_key = (target, target.stat().st_mtime_ns)
    if cache_key in _MEMORY_CACHE:
        return _MEMORY_CACHE[cache_key]
    places: list[Place] = []
    try:
        with target.open(encoding="utf-8") as handle:
            for line in handle:
                cols = line.rstrip("\n").split("\t")
                if len(cols) < 15 or not cols[1].strip() or cols[7] in SKIPPED_TOWN_CODES:
                    continue
                places.append(
                    Place(
                        name=cols[1].strip(),
                        name_ascii=cols[2].strip() or cols[1].strip(),
                        country=cols[8].strip(),
                        lon=float(cols[5]),
                        lat=float(cols[4]),
                        pop_max=int(cols[14] or 0),
                        scalerank=10,
                        source="geonames",
                    )
                )
    except (OSError, ValueError):
        return ()
    result = tuple(places)
    _MEMORY_CACHE[cache_key] = result
    return result


def _nearest_in(
    places: tuple[Place, ...], lon: float, lat: float, max_distance_km: float
) -> PlaceMatch | None:
    if not places:
        return None
    lons = np.array([p.lon for p in places], dtype=float)
    lats = np.array([p.lat for p in places], dtype=float)
    dists = haversine_m(np.full(len(places), lon), np.full(len(places), lat), lons, lats)
    inside = np.flatnonzero(dists <= max_distance_km * 1000.0)
    if len(inside) == 0:
        return None
    # A metropolis beats its own districts, but not a nearby town 10+ km from its centre.
    pops = np.array([max(places[i].pop_max, 1) for i in inside], dtype=float)
    score = dists[inside] / 1000.0 - TOWN_POPULATION_PULL_KM * np.log10(np.maximum(pops / 15_000.0, 1.0))
    idx = int(inside[int(np.argmin(score))])
    best_dist = float(dists[idx])
    chosen = places[idx]
    return PlaceMatch(
        place=chosen,
        distance_m=best_dist,
        bearing_deg=great_circle_bearing(lon, lat, chosen.lon, chosen.lat),
    )


def nearest_place(
    lon: float,
    lat: float,
    *,
    max_distance_km: float = 30.0,
    cache_dir: Path = DEFAULT_PLACES_CACHE_DIR,
    offline: bool = False,
) -> PlaceMatch | None:
    """Closest town (GeoNames, else Natural Earth) within ``max_distance_km``, or ``None``."""
    towns = _nearest_in(load_towns(cache_dir, offline=offline), lon, lat, max_distance_km)
    if towns is not None:
        return towns
    return _nearest_in(load_places(cache_dir, offline=offline), lon, lat, max_distance_km)


def _parse_lat_lon(text: str) -> tuple[float, float] | None:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 2:
        return None
    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError(f"Coordinates out of range in --toward: {text!r}")
    return lon, lat


def _country_matches(country: str, query: str) -> bool:
    """Match a gazetteer country name or ISO code without 2-letter false positives."""
    country = country.casefold()
    query = query.casefold()
    if not query:
        return True
    # Natural Earth stores full names; GeoNames stores ISO codes. Exact matching
    # for short codes prevents "US" from also matching "Austria" or "Australia".
    return country == query if len(query) == 2 else query in country


def _match_named_place(places: Sequence[Place], raw_query: str) -> list[Place]:
    """Match ``City`` or ``City, Country`` against a gazetteer (exact first, then substring)."""
    if "," in raw_query:
        city_part, country_part = (part.strip().casefold() for part in raw_query.split(",", 1))
    else:
        city_part, country_part = raw_query.strip().casefold(), ""

    def country_ok(place: Place) -> bool:
        return _country_matches(place.country, country_part)

    exact = [
        p
        for p in places
        if country_ok(p) and (p.name.casefold() == city_part or p.name_ascii.casefold() == city_part)
    ]
    if exact:
        return exact
    return [
        p
        for p in places
        if country_ok(p) and (city_part in p.name.casefold() or city_part in p.name_ascii.casefold())
    ]


def destination_for_distance(  # noqa: PLR0913
    origin_lon: float,
    origin_lat: float,
    distance_m: float,
    *,
    toward: str | None = None,
    cache_dir: Path = DEFAULT_PLACES_CACHE_DIR,
    offline: bool = False,
) -> PlaceMatch | None:
    """Resolve an automatic or user-specified destination for ``stretch``."""
    if toward is not None and toward.strip():
        raw_toward = toward.strip()
        coords = _parse_lat_lon(raw_toward)
        if coords is not None:
            lon, lat = coords
            nearby = nearest_place(lon, lat, max_distance_km=35.0, cache_dir=cache_dir, offline=offline)
            place = (
                Place(
                    name=nearby.place.name,
                    name_ascii=nearby.place.name_ascii,
                    country=nearby.place.country,
                    lon=lon,
                    lat=lat,
                    pop_max=nearby.place.pop_max,
                    scalerank=nearby.place.scalerank,
                    source=nearby.place.source,
                )
                if nearby is not None
                else Place(
                    name=f"{lat:.2f}°, {lon:.2f}°",
                    name_ascii=f"{lat:.2f}, {lon:.2f}",
                    country="",
                    lon=lon,
                    lat=lat,
                    pop_max=0,
                    scalerank=10,
                    source=None,
                )
            )
            dist = float(
                haversine_m(
                    np.array([origin_lon]),
                    np.array([origin_lat]),
                    np.array([lon]),
                    np.array([lat]),
                )[0]
            )
            return PlaceMatch(
                place=place,
                distance_m=dist,
                bearing_deg=great_circle_bearing(origin_lon, origin_lat, lon, lat),
            )

        candidates = _match_named_place(load_places(cache_dir, offline=offline), raw_toward)
        if not candidates:
            # GeoNames backs smaller towns that Natural Earth omits. Load it only
            # when the primary gazetteer had no match, so a hit never downloads.
            candidates = _match_named_place(load_towns(cache_dir, offline=offline), raw_toward)
        if not candidates:
            raise ValueError(f"Unknown destination place for --toward: {toward!r}")
        chosen = max(candidates, key=lambda p: (p.pop_max, -p.scalerank))
        dist = float(
            haversine_m(
                np.array([origin_lon]),
                np.array([origin_lat]),
                np.array([chosen.lon]),
                np.array([chosen.lat]),
            )[0]
        )
        return PlaceMatch(
            place=chosen,
            distance_m=dist,
            bearing_deg=great_circle_bearing(origin_lon, origin_lat, chosen.lon, chosen.lat),
        )

    if distance_m <= 0.0 or distance_m > 20_000_000.0:
        return None
    places = load_places(cache_dir, offline=offline)
    if not places:
        return None
    major = [p for p in places if p.pop_max >= 350_000 or p.scalerank <= 3] or list(places)
    lons = np.array([p.lon for p in major], dtype=float)
    lats = np.array([p.lat for p in major], dtype=float)
    dists = haversine_m(
        np.full(len(major), origin_lon),
        np.full(len(major), origin_lat),
        lons,
        lats,
    )
    min_dist = min(distance_m * 0.4, 15_000.0)
    valid = np.flatnonzero(dists >= min_dist)
    if len(valid) == 0:
        valid = np.arange(len(major))
    rel_err = np.abs(dists[valid] - distance_m) / max(distance_m, 1.0)
    best_idx = int(valid[int(np.argmin(rel_err))])
    chosen = major[best_idx]
    return PlaceMatch(
        place=chosen,
        distance_m=float(dists[best_idx]),
        bearing_deg=great_circle_bearing(origin_lon, origin_lat, chosen.lon, chosen.lat),
    )


def home_cluster(starts: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """Median (lon, lat) of the densest ~2 km cluster of ride start points."""
    if not starts:
        raise ValueError("Cannot compute home cluster from an empty ride list")
    pts = np.asarray(starts, dtype=float)
    if len(pts) == 1:
        return float(pts[0, 0]), float(pts[0, 1])
    cell_lat = np.round(pts[:, 1] / 0.02).astype(int)
    cos_lat = np.maximum(0.1, np.cos(np.radians(pts[:, 1])))
    cell_lon = np.round(pts[:, 0] * cos_lat / 0.02).astype(int)
    counts = Counter(zip(cell_lon.tolist(), cell_lat.tolist(), strict=True))
    best_cell: tuple[int, int] | None = None
    best_score = -1
    for cx, cy in counts:
        score = sum(
            counts.get((cx + dx, cy + dy), 0)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
        )
        if score > best_score:
            best_score = score
            best_cell = (cx, cy)
    assert best_cell is not None
    mask = (np.abs(cell_lon - best_cell[0]) <= 1) & (np.abs(cell_lat - best_cell[1]) <= 1)
    cluster = pts[mask]
    return float(np.median(cluster[:, 0])), float(np.median(cluster[:, 1]))
