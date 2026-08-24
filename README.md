# Ride Visuals

Ride Visuals turns cycling activity archives into maps, reports, and animated
telemetry. It is a small tool born from a personal archive and shared for anyone
who wants to see their rides differently. Everything runs locally.

## A collection over time

![Animated cycling activity collection](showcase/ride-collection.gif)

Routes accumulate chronologically while the map, heart-rate coverage, and
season totals evolve together.

```bash
make preview-collection SCOPE="--start-date 2026-02-06"
```

## One ride in detail

![Animated telemetry for a 138.7 km ride](showcase/ride-telemetry.png)

The activity view follows route progress alongside speed, heart rate,
elevation, grade, temperature, and distance.

```bash
make preview-activity ACTIVITY_ID=<activity-id> TELEMETRY_BASEMAP=satellite
```

## A reusable overlay

![A transparent overlay for a 115.8 km ride to Eberbach](showcase/ride-overlay.png)

The same route and summary can be exported as a transparent PNG for another
layout or editing workflow.

```bash
ride-visuals video overlay <activity-id> --overlay-format png --aspect 16:9 \
  --config config/config.toml
```

## Shape the collection

Collection videos support chronological, simultaneous, elapsed-time, and comet
motion. Routes can be colored by heart rate, temperature, altitude, speed,
grade, month, or a fixed palette, over plain, dark, satellite, topographic, or
OpenStreetMap backgrounds.

```bash
ride-visuals video collection --motion elapsed --style altitude --basemap topo \
  --config config/config.toml
```

## Start

You need Python 3.11+, FFmpeg, Node.js, and npm.

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
then generate the complete archive output set:

```bash
make --jobs=6 final
```

This creates three reports, three maps, and collection, progress, and timeline videos in both 16:9 and 9:16.
Individual activity media needs an ID and
is generated separately:

```bash
make final-activity ACTIVITY_ID=<activity-id>
```

## Choose a period

Set dates, years, or months in `config/config.toml`, or pass them directly:

```bash
make preview-collection SCOPE="--year 2025 --month 4"
make final SCOPE="--start-date 2024-02-01 --end-date 2024-12-31"
```

Filters are inclusive and combine with each other. With no filter, every
catalogued activity is used. Run `ride-visuals --help` for individual maps,
reports, videos, and activity overlays.

## Development

```bash
make check
```

## License

Ride Visuals is licensed under `AGPL-3.0-only`. The renderer has a narrow
compatibility exception for Remotion; see [LICENSE_EXCEPTION](LICENSE_EXCEPTION).
Remotion remains under its own license. Other credits and terms are listed in
[THIRD_PARTY.md](THIRD_PARTY.md).
