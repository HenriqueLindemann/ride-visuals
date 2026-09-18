# Showcase assets

This directory holds the images and GIFs used by the root `README.md`, plus
`generate.sh`, the script that regenerates them from final renders.

## Assets

| File | Shows | Rendered from |
| --- | --- | --- |
| `collection-minimal.gif` | Hero: season accumulating in real elapsed time, minimal layout, density palette, plain canvas | `video collection --minimal --motion elapsed --style density --aspect 16:9` |
| `collection-chronological.gif` | Section preview: routes accumulating in date order, full layout, speed palette, dark basemap | `video collection --motion chronological --style speed --basemap dark --aspect 16:9` |
| `activity-telemetry.png` | Full ride telemetry over a satellite basemap, mid-ride frame | `video telemetry 19666115840 --basemap satellite --aspect 16:9` |
| `activity-overlay.png` | Combined transparent overlay (route + telemetry) | `video overlay 19949741255 --overlay-format png --aspect 16:9` |
| `activity-overlay-stats.gif` | Animated statistics overlay, composited for display | `video stats-overlay 19949741255 --overlay-format webm --aspect 16:9` |
| `activity-overlay-motion.gif` | Moving telemetry composited over a photo, 9:16 | `video telemetry 19812875173 --background-image <photo> --aspect 9:16` |

Transparent renders keep their alpha in `outputs/`; the files in this directory
are composited over `#161616` so the white telemetry stays readable on GitHub.

## Personal defaults

The checked-in assets use the author's export and can be pointed anywhere with
environment variables. The defaults are:

| Variable | Default | Ride |
| --- | --- | --- |
| `SCOPE_START` | `2026-02-08` | Start of the 2026 season selection |
| `ACTIVITY_TELEMETRY` | `19666115840` | Kaiserslautern → Koblenz, 138.7 km |
| `ACTIVITY_OVERLAY` | `19949741255` | Kalmit + Weinstraße, 127.5 km, +1,859 m |
| `ACTIVITY_PHOTO` | `19812875173` | Subida e mais subida, 71.7 km, +1,105 m |
| `PHOTO` | *(unset)* | Image used behind the moving overlay |

## Regenerating

With the project installed, a populated catalog, and FFmpeg available:

```bash
# Everything, with the author's defaults
showcase/generate.sh

# Pick your own rides
ACTIVITY_TELEMETRY=<id> ACTIVITY_OVERLAY=<id> \
ACTIVITY_PHOTO=<id> PHOTO=~/ride-photo.jpg \
SCOPE_START=2026-04-01 showcase/generate.sh

# One group at a time
showcase/generate.sh collection
showcase/generate.sh activity
showcase/generate.sh overlays
```
