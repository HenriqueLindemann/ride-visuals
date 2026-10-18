# Showcase assets

This directory holds the images and GIFs used by the root `README.md`, plus
`generate.sh`, the script that regenerates them from final renders.

## Assets

| File | Shows | Rendered from |
| --- | --- | --- |
| `collection-minimal.gif` | Hero: season accumulating in real elapsed time, minimal layout, density palette, plain canvas | `video collection --minimal --motion elapsed --style density --aspect 16:9` |
| `flyover.gif` | 3D, one ride: the Kalmit climb up to its top, then the ending that unfolds the ride into its profile | `video flyover 19949741255 --preview --aspect 16:9` |
| `strata.gif` | 3D, a season: the 2026 rides stacked as floors, one per month | `video strata --year 2026 --period month --preview --aspect 16:9` |
| `activity-telemetry.png` | Full ride telemetry over a satellite basemap, mid-ride frame | `video telemetry 19666115840 --basemap satellite --aspect 16:9` |
| `activity-overlay.png` | Combined transparent overlay (route + telemetry) | `video overlay 19949741255 --overlay-format png --aspect 16:9` |
| `activity-overlay-layers.gif` | Route and statistics layers side by side, composited for display | `video route-overlay` and `video stats-overlay 19949741255 --overlay-format webm` |

Transparent renders keep their alpha in `outputs/`; the files in this directory
are composited over `#161616` so the white telemetry stays readable on GitHub.
The two 3D GIFs sit side by side at 640 px; their size budget and how each is
kept small is noted next to `flyover_gif` and `strata_gif` in `generate.sh`.

## Personal defaults

The checked-in assets use the author's export and can be pointed anywhere with
environment variables. The defaults are:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SCOPE_START` | `2026-02-08` | Start of the 2026 season selection |
| `ACTIVITY_TELEMETRY` | `19666115840` | Kaiserslautern → Koblenz, 138.7 km |
| `ACTIVITY_OVERLAY` | `19949741255` | Kalmit + Weinstraße, 127.5 km, +1,859 m |
| `ACTIVITY_FLYOVER` | `19949741255` | The same Kalmit ride, in 3D |
| `FLYOVER_CLIMB` | `22.67-30.83` | Seconds of the flyover shown in 3D: the main climb up to its top |
| `FLYOVER_ENDING` | `64.33-76.70` | Seconds of the ending, from the last metres ridden |
| `STRATA_YEAR` | `2026` | Season stacked in the strata GIF |
| `STRATA_START` | `3.5` | Seconds of title card skipped before the first floor |

## Regenerating

With the project installed, a populated catalog, and FFmpeg available:

```bash
# Everything, with the author's defaults
showcase/generate.sh

# Pick your own rides
ACTIVITY_TELEMETRY=<id> ACTIVITY_OVERLAY=<id> ACTIVITY_FLYOVER=<id> \
SCOPE_START=2026-04-01 showcase/generate.sh

# One group at a time
showcase/generate.sh collection
showcase/generate.sh scene3d
showcase/generate.sh activity
showcase/generate.sh overlays
```
