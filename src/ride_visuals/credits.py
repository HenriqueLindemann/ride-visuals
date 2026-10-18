"""Data-source credits for published media.

Every output that draws third-party map data gets a plain-text sidecar next to
it (``<name>.credits.txt``), ready to paste into a video description or a post.
Drawing the short attribution on the image itself is optional and off by
default: personal films stay clean, and the sidecar still carries the full,
license-complete wording that a single on-screen line cannot.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataSource:
    """One upstream dataset or tile service used to build an output."""

    key: str
    name: str
    #: Short line suitable for drawing on the media itself.
    attribution: str
    license: str
    url: str


SOURCES: dict[str, DataSource] = {
    source.key: source
    for source in (
        DataSource(
            key="esri-world-imagery",
            name="Esri World Imagery",
            attribution="Esri, Maxar, Earthstar Geographics, and the GIS User Community",
            license="Esri Master License Agreement / Terms of Use",
            url="https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9",
        ),
        DataSource(
            key="esri-dark-gray",
            name="Esri World Dark Gray Base",
            attribution="Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community",
            license="Esri Master License Agreement / Terms of Use",
            url="https://www.arcgis.com/home/item.html?id=358ec1e175ea41c3bf5c68f0da11ae2b",
        ),
        DataSource(
            key="esri-light-gray",
            name="Esri World Light Gray Base",
            attribution="Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS User Community",
            license="Esri Master License Agreement / Terms of Use",
            url="https://www.arcgis.com/home/item.html?id=979c6cc89af9449cbeb5342a439c6a76",
        ),
        DataSource(
            key="opentopomap",
            name="OpenTopoMap",
            attribution=(
                "Map data: © OpenStreetMap contributors · DEM: SRTM, Sonny · "
                "Map style: © OpenTopoMap (CC-BY-SA)"
            ),
            license="CC BY-SA 3.0 (style); ODbL (data)",
            url="https://opentopomap.org/about",
        ),
        DataSource(
            key="openstreetmap",
            name="OpenStreetMap",
            attribution="© OpenStreetMap contributors",
            license="Open Database License (ODbL) 1.0",
            url="https://www.openstreetmap.org/copyright",
        ),
        DataSource(
            key="openfreemap",
            name="OpenFreeMap vector tiles (OpenMapTiles schema)",
            attribution="© OpenMapTiles · © OpenStreetMap contributors",
            license="ODbL 1.0 (data); OpenMapTiles schema under CC BY 4.0",
            url="https://openfreemap.org",
        ),
        DataSource(
            key="terrain-tiles",
            name="Terrain Tiles (Mapzen, hosted on AWS Open Data)",
            attribution="Terrain: Mapzen Terrain Tiles (SRTM, GMTED, ETOPO1, and others)",
            license=(
                "Open data; see the source list (SRTM, GMTED2010, ETOPO1, NED, EU-DEM, "
                "and national datasets)"
            ),
            url="https://github.com/tilezen/joerd/blob/master/docs/attribution.md",
        ),
        DataSource(
            key="natural-earth",
            name="Natural Earth populated places",
            attribution="Made with Natural Earth",
            license="Public domain",
            url="https://www.naturalearthdata.com/about/terms-of-use/",
        ),
        DataSource(
            key="geonames",
            name="GeoNames cities15000",
            attribution="Places: GeoNames",
            license="CC BY 4.0",
            url="https://www.geonames.org/",
        ),
    )
}


def credits_path(output: Path) -> Path:
    """Sidecar path for an output: ``ride.mp4`` -> ``ride.credits.txt``."""
    output = Path(output)
    return output.with_name(f"{output.stem}.credits.txt")


def on_screen_line(keys: Iterable[str]) -> str:
    """Join the short attributions of several sources into one display line."""
    seen: list[str] = []
    for key in keys:
        line = SOURCES[key].attribution
        if line not in seen:
            seen.append(line)
    return " · ".join(seen)


def write_credits(output: Path, keys: Iterable[str]) -> Path | None:
    """Write the credits sidecar for ``output``; return its path.

    Nothing is written when ``keys`` is empty (a plain map uses only the rider's
    own data), and a stale sidecar from an earlier render with a basemap is
    removed so it never describes the wrong file.
    """
    unique = list(dict.fromkeys(keys))
    unknown = [key for key in unique if key not in SOURCES]
    if unknown:
        raise KeyError(f"Unknown data source(s): {', '.join(unknown)}")
    path = credits_path(output)
    if not unique:
        path.unlink(missing_ok=True)
        return None
    lines = [
        f"Credits for {Path(output).name}",
        "",
        "Map data and imagery:",
    ]
    for key in unique:
        source = SOURCES[key]
        lines.extend(
            [
                f"- {source.name}",
                f"  {source.attribution}",
                f"  License: {source.license}",
                f"  {source.url}",
            ]
        )
    lines.extend(["", "Route data: the rider's own activity recordings.", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
