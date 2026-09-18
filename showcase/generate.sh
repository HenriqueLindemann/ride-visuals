#!/usr/bin/env bash
#
# Regenerate the README showcase assets from a local archive.
#
# Usage:
#   showcase/generate.sh [all|collection|activity|overlays]
#
# Every input can be overridden from the environment; see showcase/README.md
# for the full list. Renders land in outputs/ as usual and only the selected
# README assets are copied next to this script. Assets are rendered as finals;
# GIFs are converted from those finals at a smaller size and frame rate.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$PWD"
SHOWCASE="$ROOT/showcase"

# --- Configuration -----------------------------------------------------------

if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi
CONFIG="${CONFIG:-config/config.toml}"

SCOPE_START="${SCOPE_START:-2026-02-08}"
SCOPE_END="${SCOPE_END:-}"
ACTIVITY_TELEMETRY="${ACTIVITY_TELEMETRY:-19666115840}"
ACTIVITY_OVERLAY="${ACTIVITY_OVERLAY:-19949741255}"
ACTIVITY_PHOTO="${ACTIVITY_PHOTO:-19812875173}"
PHOTO="${PHOTO:-}"

TELEMETRY_BASEMAP="${TELEMETRY_BASEMAP:-satellite}"
OVERLAY_BASEMAP="${OVERLAY_BASEMAP:-plain}"

GIF_WIDTH="${GIF_WIDTH:-1280}"
GIF_FPS="${GIF_FPS:-15}"
GIF_COLORS="${GIF_COLORS:-192}"
# GIF playback speed relative to the final render.
GIF_SPEED="${GIF_SPEED:-2}"

RUN=(env PYTHONPATH=src "$PYTHON" -m ride_visuals.cli)
OUTPUTS="$ROOT/outputs"

SLUG="from-${SCOPE_START}"
SCOPE=(--start-date "$SCOPE_START")
if [[ -n "$SCOPE_END" ]]; then
  SLUG="${SLUG}_to-${SCOPE_END}"
  SCOPE+=(--end-date "$SCOPE_END")
fi

read -r THEME LOCALE < <("$PYTHON" - "$CONFIG" <<'PY'
import sys, tomllib
try:
    with open(sys.argv[1], "rb") as handle:
        config = tomllib.load(handle)
except FileNotFoundError:
    config = {}
print(config.get("video", {}).get("theme", "midnight"),
      config.get("app", {}).get("locale", "en"))
PY
)
LOCALE_TAG="${LOCALE,,}"
LOCALE_TAG="${LOCALE_TAG//-/_}"

log() { printf '\n== %s\n' "$*"; }

render() {
  "${RUN[@]}" "$@" --config "$CONFIG"
}

command -v ffmpeg >/dev/null || {
  echo "ffmpeg is required to write GIFs" >&2
  exit 1
}

# Two-pass palette GIF: crisp thin lines, small files. A speed factor above 1
# plays the final render faster so the loop stays short.
gif() {
  local source="$1" destination="$2" width="${3:-$GIF_WIDTH}" speed="${4:-$GIF_SPEED}"
  local palette
  palette="$(mktemp --suffix=.png)"
  local timing="fps=$GIF_FPS,scale=$width:-1:flags=lanczos"
  if [[ "$speed" != "1" ]]; then
    timing="setpts=PTS/$speed,$timing"
  fi
  ffmpeg -y -v error -i "$source" \
    -vf "$timing,palettegen=max_colors=$GIF_COLORS:stats_mode=diff" \
    "$palette"
  ffmpeg -y -v error -i "$source" -i "$palette" \
    -lavfi "$timing[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
    -loop 0 "$destination"
  rm -f "$palette"
}

# Composite a transparent render over a neutral surface for GitHub.
flatten() {
  local source="$1" destination="$2"
  "$PYTHON" - "$source" "$destination" <<'PY'
from PIL import Image
import sys

image = Image.open(sys.argv[1]).convert("RGBA")
background = Image.new("RGBA", image.size, (22, 22, 22, 255))
Image.alpha_composite(background, image).convert("RGB").save(sys.argv[2], optimize=True)
PY
}

# Composite an alpha video over the neutral surface, then convert to GIF.
stats_gif() {
  local source="$1" destination="$2" size="$3"
  local temp
  temp="$(mktemp --suffix=.mp4)"
  ffmpeg -y -v error -f lavfi -i "color=c=0x161616:s=${size}:r=$GIF_FPS" \
    -i "$source" -filter_complex "[0:v][1:v]overlay=shortest=1,format=yuv420p" \
    -c:v libx264 -crf 18 "$temp"
  gif "$temp" "$destination" "${size%%x*}"
  rm -f "$temp"
}

# Copy an inspection frame of a render into the showcase.
summary_frame() {
  local directory="$1" destination="$2" percent="${3:-100}"
  local frame
  frame="$(find "$directory" -maxdepth 1 -name "*_${percent}pct.png" | sort | tail -n 1)"
  [[ -n "$frame" ]] || { echo "No ${percent}% frame in $directory" >&2; exit 1; }
  cp "$frame" "$destination"
}

# --- Collection --------------------------------------------------------------

collection() {
  local collection_dir="$OUTPUTS/videos/collection"

  log "Collection: minimal hero (elapsed, density, plain)"
  render video collection --minimal --motion elapsed --style density \
    --basemap plain --aspect 16:9 "${SCOPE[@]}"
  gif "$collection_dir/collection_${SLUG}_elapsed_density_16_9_minimal_${LOCALE_TAG}.mp4" \
    "$SHOWCASE/collection-minimal.gif"
}

# --- Ride films --------------------------------------------------------------

activity() {
  local keyframes="$OUTPUTS/videos/keyframes"

  log "Ride: telemetry over $TELEMETRY_BASEMAP ($ACTIVITY_TELEMETRY)"
  render video telemetry "$ACTIVITY_TELEMETRY" --basemap "$TELEMETRY_BASEMAP" \
    --aspect 16:9
  summary_frame \
    "$keyframes/activity_${ACTIVITY_TELEMETRY}_${THEME}_${LOCALE_TAG}_${TELEMETRY_BASEMAP}_16_9" \
    "$SHOWCASE/activity-telemetry.png" 50
}

# --- Overlays ----------------------------------------------------------------

overlays() {
  local overlay_dir="$OUTPUTS/videos/overlay"
  local stats_dir="$OUTPUTS/videos/stats-overlay"
  local telemetry_dir="$OUTPUTS/videos/telemetry"
  local stem="activity_${ACTIVITY_OVERLAY}"

  log "Overlay: combined overlay"
  render video overlay "$ACTIVITY_OVERLAY" --overlay-format png --aspect 16:9 \
    --basemap "$OVERLAY_BASEMAP"
  flatten "$overlay_dir/${stem}_overlay_${THEME}_${LOCALE_TAG}_16_9.png" \
    "$SHOWCASE/activity-overlay.png"

  log "Overlay: animated statistics strip"
  render video stats-overlay "$ACTIVITY_OVERLAY" --overlay-format webm --aspect 16:9 \
    --basemap "$OVERLAY_BASEMAP"
  stats_gif "$stats_dir/${stem}_stats-overlay_${THEME}_${LOCALE_TAG}_16_9.webm" \
    "$SHOWCASE/activity-overlay-stats.gif" "960x320"

  if [[ -z "$PHOTO" ]]; then
    log "Overlay: skipping motion GIF (set PHOTO=/path/to/photo.jpg)"
    return
  fi
  [[ -f "$PHOTO" ]] || { echo "Photo not found: $PHOTO" >&2; exit 1; }

  log "Overlay: motion over photo ($ACTIVITY_PHOTO)"
  render video telemetry "$ACTIVITY_PHOTO" --background-image "$PHOTO" \
    --background-blur 0 --background-dim 0.18 --aspect 9:16
  gif "$telemetry_dir/activity_${ACTIVITY_PHOTO}_telemetry_${THEME}_${LOCALE_TAG}_9_16.mp4" \
    "$SHOWCASE/activity-overlay-motion.gif" 540
}

# --- Entry point -------------------------------------------------------------

target="${1:-all}"
case "$target" in
  all) collection; activity; overlays ;;
  collection | activity | overlays) "$target" ;;
  *)
    echo "Unknown target: $target (expected all, collection, activity or overlays)" >&2
    exit 2
    ;;
esac

log "Done. Review the files in showcase/ and commit the ones you want."
