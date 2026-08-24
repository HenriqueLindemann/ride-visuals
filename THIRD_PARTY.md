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
- `renderer/package-lock.json` records the complete Node dependency tree.

## Python and local tools

Direct dependencies are listed in `pyproject.toml`. They include software under
MIT, Apache-2.0, BSD, PSF-based, and HPND terms. FFmpeg is invoked as a local
executable and keeps the terms of the installed build. DejaVu Sans may be loaded
from the operating system and is not bundled.

## Map tiles

Optional raster maps use services operated by OpenStreetMap, OpenTopoMap, CARTO,
and Esri. Provider attribution is embedded in outputs; provider copyright,
database, and service terms apply separately.

This source repository does not include third-party packages, FFmpeg, fonts,
map tiles, or generated media.
