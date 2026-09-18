# Ride Visuals

Ride Visuals turns a cycling activity archive into maps, ride films, and
animated telemetry. It is a small tool born from a personal archive and shared
for anyone who wants to see their rides differently: locally, from their own
export, with no account and no upload.

<p align="center">
  <img src="showcase/collection-minimal.gif" alt="A season of rides accumulating on a dark map with a live distance counter" width="840">
</p>

Every selected ride is drawn in order of elapsed time, repeated streets become
brighter with each pass, and the distance counter follows the archive.

## What it makes

- **Collection films** — every ride drawn over one map. Chronological, elapsed,
  simultaneous and comet motion; minimal, panel and clean layouts; nine route
  palettes; six basemaps; landscape, vertical, Story and 4K canvases.
- **Ride films** — one activity in detail, with speed, heart rate, elevation,
  grade, temperature, distance and an elevation profile beside the map, over a
  georeferenced basemap, a photo, or video with its own audio.
- **Transparent overlays** — reusable route and telemetry layers as still PNG,
  alpha WebM, or ProRes 4444 MOV for your own editing workflow.
- **Cartographic stills** — route overviews, density heatmaps and heart-rate
  effort maps at print resolution.

An analytics layer (dashboard infographic, season telemetry timeline, progress
metrics) is available through `ride-visuals report`.

## Quick start

You need Python 3.11+, FFmpeg, and — for ride films and overlays — Node.js and
npm. Collection films and maps are rendered without Node.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
npm --prefix renderer ci --no-bin-links
cp config/config.example.toml config/config.toml
```

If your archive comes from Strava, request it with
[Exporting Your Data and Bulk Export](https://support.strava.com/en-us/articles/15401919-exporting-your-data-and-bulk-export).
Place `activities.csv` and its `activities/` directory under `bulk_download/`,
then ingest and render the complete output set:

```bash
make --jobs=6 final
```

`final` audits the archive, builds the catalog, and renders reports, maps and
videos. Use `make final-visuals` when you only want maps and videos, and
`make final-activity ACTIVITY_ID=<activity-id>` for one ride.

Rides recorded outside Strava, or downloaded individually as `.fit` files, can
be added to the collection with `ingest-fit`. The file is copied into the
export, registered in `activities.csv`, and ingested.

```bash
ride-visuals ingest-fit ~/Downloads/Kalmit\ Weinstraße.fit --config config/config.toml
```

Run `ride-visuals doctor` if anything looks wrong: it checks Python, FFmpeg,
Node and the renderer setup.

## Collection films

Every ride is drawn over the same map, with a live panel (rides completed,
combined distance, elevation gain, averages, longest ride so far, progress
chart) or a minimal distance counter. The film above uses the minimal layout;
`--clean` removes the UI entirely.

```bash
ride-visuals video collection --motion chronological --style density
```

| Motion | Effect |
| --- | --- |
| `chronological` | Rides appear one by one, in date order. |
| `elapsed` / `simultaneous` | Every ride starts at once and runs its real elapsed time, so shorter rides finish first. |
| `comet` | Rides draw together and finish together, each with a trailing cursor. |

| Palette | Color |
| --- | --- |
| `density` | Single-color alpha accumulation: repeated streets grow brighter. |
| `orange`, `monochrome`, `monthly` | Fixed palettes, including a month legend. |
| `heart_rate`, `temperature`, `altitude`, `speed`, `grade` | Route samples colored by the recorded stream, with a legend. |

Basemaps are `plain` (no tiles, just the theme canvas), `light`, `dark`, `osm`,
`topo` and `satellite`. Use `--minimal` for a map-first film with only the
distance counter, or `--clean` for no UI at all. `--cursors`, `--legend`,
`--background-tracks` and `--progress-bar` add detail, and `--aspect` accepts
`16:9`, `9:16`, `instagram` and `4k`.

## Ride films

<p align="center">
  <img src="showcase/activity-telemetry.png" alt="Ride telemetry for a 138.7 km ride over a satellite map" width="840">
</p>

The activity view follows route progress alongside speed, heart rate, elapsed
time, grade, altitude, temperature, distance and elevation. The georeferenced
map continues behind the translucent telemetry column.

```bash
ride-visuals video telemetry <activity-id> --basemap satellite
```

`--minimal` keeps only the map, speed and distance; `--clean` drops the
telemetry entirely. Any basemap can be replaced with your own media:

```bash
ride-visuals video telemetry <activity-id> --background-image photo.jpg \
  --background-blur 0 --background-dim 0.18 --aspect 9:16
ride-visuals video telemetry <activity-id> --background-video clip.mp4 \
  --background-dim 0.2 --aspect instagram
```

A background video keeps its audio in the delivered MP4 unless you pass
`--no-background-video-audio`; it must cover the full render.

## Transparent overlays

<p align="center">
  <img src="showcase/activity-overlay.png" alt="Full telemetry overlay for a 127.5 km ride" width="720">
</p>

The route, the telemetry, or both can be exported as an overlay for another
layout or editor. `--overlay-format` chooses a still PNG, an alpha WebM video,
or ProRes 4444 MOV with alpha; `route-overlay` and `stats-overlay` export the
pieces separately.

```bash
ride-visuals video overlay <activity-id> --overlay-format png --aspect 16:9
ride-visuals video route-overlay <activity-id> --overlay-format mov
ride-visuals video stats-overlay <activity-id> --aspect 9:16 --overlay-format mov
```

<p align="center">
  <img src="showcase/activity-overlay-stats.gif" alt="Animated statistics overlay" width="720">
</p>

Overlays can also move: the route draws itself while speed, heart rate and the
other numbers update on screen, ready to sit on a photo or a clip.

<p align="center">
  <img src="showcase/activity-overlay-motion.gif" alt="Moving telemetry over a finish photo" width="300">
</p>

```bash
ride-visuals video telemetry <activity-id> --background-image photo.jpg \
  --background-blur 0 --background-dim 0.18 --aspect 9:16 \
  --title "" --config config/config.toml
```

## Maps

The same archive renders print-resolution cartographic stills: `overview` plots
every route, `heatmap` accumulates density, and `effort` colors each track
point by heart-rate zone.

```bash
ride-visuals map overview --dpi 300 --basemap dark
ride-visuals map heatmap --dpi 300 --basemap dark
ride-visuals map effort --dpi 300 --basemap dark
```

## Choose a period

Set dates, years, or months in `config/config.toml`, or pass them directly.
Filters are inclusive and combine with each other; with no filter, every
catalogued activity is used.

```bash
ride-visuals video collection --motion elapsed --year 2025 --month 4
ride-visuals video collection --start-date 2024-02-01 --end-date 2024-12-31
ride-visuals map overview --dpi 300 --basemap satellite
```

## Previews and delivery

Previews keep the full canvas and shorten the film to about five seconds, so a
layout check is fast. Finals run 12–15 seconds at 30 fps and also extract
inspection frames under `outputs/videos/keyframes/`.

```bash
# Short full-resolution previews
make preview-collection MOTION=elapsed STYLE=density VIDEO_BASEMAP=plain MINIMAL=1
make preview-activity ACTIVITY_ID=<activity-id> ACTIVITY_TYPE=telemetry

# Delivery renders
make final-visuals
```

The exact commands behind every image on this page are in
[showcase/README.md](showcase/README.md), which also ships
`showcase/generate.sh` to regenerate them.

## Commands

| Command | Output |
| --- | --- |
| `ride-visuals video collection` | Collection film (`--minimal`, `--clean`, motion, palette, basemap, aspect) |
| `ride-visuals video telemetry <id>` | Full ride film (basemap, photo or video background) |
| `ride-visuals video minimal <id>` | Map-first ride film with speed and distance |
| `ride-visuals video clean <id>` | Route only, no telemetry |
| `ride-visuals video overlay <id>` | Combined transparent overlay (`png`, `webm`, `mov`) |
| `ride-visuals video route-overlay <id>` | Transparent route overlay |
| `ride-visuals video stats-overlay <id>` | Transparent statistics overlay |
| `ride-visuals map overview\|heatmap\|effort` | Cartographic stills |
| `ride-visuals report progress\|dashboard\|timeline` | Analytics reports and dashboards |
| `ride-visuals ingest`, `ingest-fit` | Build and extend the local catalog |
| `ride-visuals audit`, `validate`, `doctor` | Data, media and environment checks |

Every command accepts `--config`, temporal selection flags, and `--help` for
its full option list. Videos also accept `--locale pt-BR` and `--theme frost`;
set `[app].locale` and `[video].theme` in the config to change the defaults.

## Development

```bash
make check
```

## License

Copyright (C) 2026 Henrique Lindemann

Ride Visuals is licensed under `AGPL-3.0-only`. The renderer has a narrow
compatibility exception for Remotion; see [LICENSE_EXCEPTION](LICENSE_EXCEPTION).
Remotion remains under its own license. Other credits and terms are listed in
[THIRD_PARTY.md](THIRD_PARTY.md).

---

> *“For all its material advantages, the sedentary life has left us edgy, unfulfilled. Even after 400 generations in villages and cities, we haven’t forgotten. The open road still softly calls, like a nearly forgotten song of childhood. We invest far-off places with a certain romance. This appeal, I suspect, has been meticulously crafted by natural selection as an essential element in our survival.”*
>
> — Carl Sagan
