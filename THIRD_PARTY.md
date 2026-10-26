# Third-party software and services

Ride Visuals is AGPL-3.0-only. The components below keep their own terms.

## Renderer

- Remotion 4.0.515 uses the
  [Remotion License](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md).
  Its free terms cover individuals, non-profits, and eligible small
  organizations; other organizations may need a paid license.
  `LICENSE_EXCEPTION` permits combining Ride Visuals with Remotion but grants no
  rights to Remotion itself.
- React and React DOM use MIT, TypeScript uses Apache-2.0, and Zod uses MIT.
- The 3D scenes use [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js)
  (BSD-3-Clause) and [maplibre-contour](https://github.com/onthegomap/maplibre-contour)
  (BSD-3-Clause). Text is set in [Geist](https://github.com/vercel/geist-font)
  (SIL Open Font License 1.1), copied from `node_modules` at render time.
- `renderer/package-lock.json` records the complete Node dependency tree.

## Python and local tools

Direct dependencies are listed in `pyproject.toml`. They include software under
MIT, Apache-2.0, BSD, PSF-based, and HPND terms. FFmpeg is invoked as a local
executable and keeps the terms of the installed build. DejaVu Sans may be loaded
from the operating system and is not bundled.

## Map tiles

Optional raster maps use services operated by
[OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/),
[OpenTopoMap](https://opentopomap.org/about), and
[Esri](https://doc.arcgis.com/en/data-appliance/2022/maps/world-dark-gray-base.htm).
Provider attribution is embedded in each output and names the contributors of
the selected composite map. Provider copyright, database, and service terms
apply separately.

The 3D scenes use:

- [Mapzen Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) on AWS
  Open Data for elevation (SRTM, GMTED2010, ETOPO1, EU-DEM, and national
  datasets; see their [attribution list](https://github.com/tilezen/joerd/blob/master/docs/attribution.md)).
- [OpenFreeMap](https://openfreemap.org) vector tiles: © OpenMapTiles,
  © OpenStreetMap contributors (ODbL 1.0).
- [Esri World Imagery](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9)
  for `--look satellite`, under Esri's own terms of use.
- [GeoNames](https://www.geonames.org/) `cities15000` (CC BY 4.0) to name where
  a ride starts (and smaller towns passed to `--toward`), and
  [Natural Earth](https://www.naturalearthdata.com/) populated places (public
  domain) for destinations.

Each output's `.credits.txt` sidecar lists exactly the sources it used.

`video ascent` draws landmarks at true scale: the Eiffel Tower from a silhouette by
GDJ ([openclipart](https://openclipart.org), CC0), the Burj Khalifa from a profile by
MJBurrage ([Wikimedia Commons](https://commons.wikimedia.org), public domain), Fuji and
Everest from Mapzen Terrain Tiles skylines.

This source repository does not include third-party packages, FFmpeg, fonts,
map tiles, or generated media.
