#!/usr/bin/env bash
#
# Regenerate the README showcase assets from a local archive.
#
# Usage:
#   showcase/generate.sh [all|collection|scene3d|activity|overlays]
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
ACTIVITY_FLYOVER="${ACTIVITY_FLYOVER:-19949741255}"
# Seconds of the flyover kept in the GIF: the main climb up to its top, then the
# ending from the last metres ridden. A long cross-fade joins the two moves.
FLYOVER_CLIMB="${FLYOVER_CLIMB:-22.67-30.83}"
FLYOVER_ENDING="${FLYOVER_ENDING:-64.33-76.70}"
STRATA_YEAR="${STRATA_YEAR:-2026}"
# Seconds of title card skipped before the first floor appears.
STRATA_START="${STRATA_START:-3.5}"

TELEMETRY_BASEMAP="${TELEMETRY_BASEMAP:-satellite}"
OVERLAY_BASEMAP="${OVERLAY_BASEMAP:-plain}"

GIF_WIDTH="${GIF_WIDTH:-1280}"
GIF_FPS="${GIF_FPS:-15}"
GIF_COLORS="${GIF_COLORS:-192}"
# GIF playback speed relative to the final render.
GIF_SPEED="${GIF_SPEED:-2}"
# The 3D GIFs sit two by two in the README.
SCENE_GIF_WIDTH="${SCENE_GIF_WIDTH:-640}"

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

# The route and statistics layers side by side, each on its own transparency
# checkerboard and named, so they read as two separate files. The explicit
# libvpx-vp9 decoder is required: ffmpeg's default VP9 decoder ignores WebM
# alpha and would flatten the transparent background to black.
layers_gif() {
  local route="$1" stats="$2" destination="$3"
  local board
  board="$(mktemp --suffix=.png)"
  # Canvas, card boxes (x, y, w, h) and captions; the cards share one height.
  "$PYTHON" - "$board" "$ROOT/renderer/node_modules/geist/dist/fonts/geist-mono/GeistMono-Regular.ttf" <<'PY'
import sys
from PIL import Image, ImageDraw, ImageFont

pad, gap, card_h = 24, 24, 252
cards = [("route-overlay", 448), ("stats-overlay", 756)]
width = pad * 2 + gap + sum(w for _, w in cards)
height = pad + card_h + 14 + 16 + pad
board = Image.new("RGB", (width, height), (22, 22, 22))
draw = ImageDraw.Draw(board)
font = ImageFont.truetype(sys.argv[2], 14)
x = pad
for name, card_w in cards:
    checker = Image.new("RGB", (card_w, card_h))
    tiles = ImageDraw.Draw(checker)
    for ty in range(0, card_h, 12):
        for tx in range(0, card_w, 12):
            shade = 30 if (tx // 12 + ty // 12) % 2 else 36
            tiles.rectangle((tx, ty, tx + 11, ty + 11), fill=(shade, shade, shade))
    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, card_w - 1, card_h - 1), radius=6, fill=255)
    board.paste(checker, (x, pad), mask)
    draw.text((x, pad + card_h + 14), name, font=font, fill=(138, 138, 138))
    x += card_w + gap
board.save(sys.argv[1])
PY
  ffmpeg -y -v error -loop 1 -i "$board" \
    -c:v libvpx-vp9 -i "$route" -c:v libvpx-vp9 -i "$stats" -filter_complex "
    [1:v]scale=448:252:flags=lanczos[route];
    [2:v]scale=756:252:flags=lanczos[stats];
    [0:v][route]overlay=24:24:shortest=1[a];
    [a][stats]overlay=496:24:shortest=1,
      setpts=PTS/$GIF_SPEED,fps=$GIF_FPS,split[b][c];
    [b]palettegen=max_colors=$GIF_COLORS:stats_mode=diff[p];
    [c][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
    -loop 0 "$destination"
  rm -f "$board"
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

# --- 3D ----------------------------------------------------------------------

# A 3D GIF is mostly fine relief texture that changes every frame, so it is
# cut short and kept small: the climb at 10 fps, the flat ending at 12 fps,
# one shared palette, and a hold on the last frame.
flyover_gif() {
  local source="$1" destination="$2"
  local fade=1.2 climb split
  calc() { LC_ALL=C awk "BEGIN { print $* }"; }
  climb="$(calc "${FLYOVER_CLIMB#*-} - ${FLYOVER_CLIMB%-*}")"
  # Where the cross-fade is half done, in GIF time.
  split="$(calc "($climb - $fade / 2) / $GIF_SPEED")"
  ffmpeg -y -v error -i "$source" -filter_complex "
    [0:v]trim=${FLYOVER_CLIMB/-/:},setpts=PTS-STARTPTS[climb];
    [0:v]trim=${FLYOVER_ENDING/-/:},setpts=PTS-STARTPTS[ending];
    [climb][ending]xfade=transition=fade:duration=$fade:offset=$(calc "$climb - $fade"),
      setpts=PTS/$GIF_SPEED,scale=$SCENE_GIF_WIDTH:-1:flags=lanczos,hqdn3d=6:6:8:8,split[a][b];
    [a]trim=0:$split,fps=10,setpts=PTS-STARTPTS[c];
    [b]trim=$split,fps=12,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=1.8[d];
    [c][d]concat=n=2:v=1,split[e][f];
    [e]palettegen=max_colors=32:stats_mode=full[p];
    [f][p]paletteuse=dither=none:diff_mode=rectangle" \
    -loop 0 "$destination"
}

# The strata floors are thin lines over a near-black terrain whose faint texture
# changes every frame. Mapping only that texture to black (it ends below
# 15/255; the floors start above 18/255) keeps every line and cuts the GIF to
# a fraction of its size.
strata_gif() {
  local source="$1" destination="$2"
  local black='if(lt(val\,15)\,0\,if(lt(val\,20)\,(val-15)*4\,val))'
  ffmpeg -y -v error -ss "$STRATA_START" -i "$source" -filter_complex "
    setpts=PTS/$GIF_SPEED,fps=10,scale=$SCENE_GIF_WIDTH:-1:flags=lanczos,format=rgb24,
    lutrgb=r=$black:g=$black:b=$black,tpad=stop_mode=clone:stop_duration=1.5,split[a][b];
    [a]palettegen=max_colors=64:stats_mode=full[p];
    [b][p]paletteuse=dither=none:diff_mode=rectangle" \
    -loop 0 "$destination"
}

# Ascent and stretch are lines on a near-black map: the same black mapping as
# strata keeps them crisp, and a lower frame rate keeps the loop small.
line_gif() {
  local source="$1" destination="$2" start="${3:-0}"
  local black='if(lt(val\,15)\,0\,if(lt(val\,20)\,(val-15)*4\,val))'
  ffmpeg -y -v error -ss "$start" -i "$source" -filter_complex "
    setpts=PTS/$GIF_SPEED,fps=10,scale=$SCENE_GIF_WIDTH:-1:flags=lanczos,format=rgb24,
    lutrgb=r=$black:g=$black:b=$black,tpad=stop_mode=clone:stop_duration=1.5,split[a][b];
    [a]palettegen=max_colors=64:stats_mode=full[p];
    [b][p]paletteuse=dither=none:diff_mode=rectangle" \
    -loop 0 "$destination"
}

# Ascent's streets fade into the dark through values the black mapping above
# would crush into bands that flip from frame to frame. Temporal denoising
# keeps that fade steady (and the dense city light enough for a GIF) instead.
city_gif() {
  local source="$1" destination="$2"
  ffmpeg -y -v error -i "$source" -filter_complex "
    setpts=PTS/$GIF_SPEED,fps=10,scale=$SCENE_GIF_WIDTH:-1:flags=lanczos,hqdn3d=6:6:10:10,
    tpad=stop_mode=clone:stop_duration=1.5,split[a][b];
    [a]palettegen=max_colors=64:stats_mode=full[p];
    [b][p]paletteuse=dither=none:diff_mode=rectangle" \
    -loop 0 "$destination"
}

scene3d() {
  log "3D: flyover ($ACTIVITY_FLYOVER)"
  render video flyover "$ACTIVITY_FLYOVER" --preview --aspect 16:9
  flyover_gif \
    "$OUTPUTS/videos/flyover/flyover_${ACTIVITY_FLYOVER}_carbon_16_9_${LOCALE_TAG}_preview.mp4" \
    "$SHOWCASE/flyover.gif"

  log "3D: strata ($STRATA_YEAR by month)"
  render video strata --year "$STRATA_YEAR" --period month --preview --aspect 16:9
  strata_gif \
    "$OUTPUTS/videos/strata/strata_years-${STRATA_YEAR}_month_carbon_16_9_${LOCALE_TAG}_preview.mp4" \
    "$SHOWCASE/strata.gif"

  log "3D: stretch ($STRATA_YEAR)"
  render video stretch --year "$STRATA_YEAR" --preview --aspect 16:9
  line_gif \
    "$OUTPUTS/videos/stretch/stretch_years-${STRATA_YEAR}_carbon_16_9_${LOCALE_TAG}_preview.mp4" \
    "$SHOWCASE/stretch.gif"

  log "3D: ascent (all by year)"
  render video ascent --period year --preview --aspect 16:9
  city_gif \
    "$OUTPUTS/videos/ascent/ascent_all_year_carbon_16_9_${LOCALE_TAG}_preview.mp4" \
    "$SHOWCASE/ascent.gif"
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
  local route_dir="$OUTPUTS/videos/route-overlay"
  local stats_dir="$OUTPUTS/videos/stats-overlay"
  local stem="activity_${ACTIVITY_OVERLAY}"

  log "Overlay: combined overlay"
  render video overlay "$ACTIVITY_OVERLAY" --overlay-format png --aspect 16:9 \
    --basemap "$OVERLAY_BASEMAP"
  flatten "$overlay_dir/${stem}_overlay_${THEME}_${LOCALE_TAG}_16_9.png" \
    "$SHOWCASE/activity-overlay.png"

  log "Overlay: route and statistics as separate layers"
  render video route-overlay "$ACTIVITY_OVERLAY" --overlay-format webm --aspect 16:9 \
    --basemap "$OVERLAY_BASEMAP"
  render video stats-overlay "$ACTIVITY_OVERLAY" --overlay-format webm --aspect 16:9 \
    --basemap "$OVERLAY_BASEMAP"
  layers_gif "$route_dir/${stem}_route-overlay_${THEME}_${LOCALE_TAG}_16_9.webm" \
    "$stats_dir/${stem}_stats-overlay_${THEME}_${LOCALE_TAG}_16_9.webm" \
    "$SHOWCASE/activity-overlay-layers.gif"
}

# --- Entry point -------------------------------------------------------------

target="${1:-all}"
case "$target" in
  all) collection; scene3d; activity; overlays ;;
  collection | scene3d | activity | overlays) "$target" ;;
  *)
    echo "Unknown target: $target (expected all, collection, scene3d, activity or overlays)" >&2
    exit 2
    ;;
esac

log "Done. Review the files in showcase/ and commit the ones you want."
