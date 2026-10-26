import {type DrawOp, type RGB, rgba} from '../core/draw';
import {inOutSine, lerp} from '../core/ease';
import type {LngLat} from '../core/geo';
import {frameMargins, LABEL_GAP, LABEL_LINE, metricHeight, totalsGrid, TYPE} from '../core/layout';
import {INK, type TextItem} from '../core/Typography';
import {extentUpTo, type Track} from '../core/track';
import type {StrataFloor} from '../stories';
import type {ScoreContext, ScoreOutput} from './index';

/** Clear space between two floor blocks, and between the column and the totals (px at scale 1). */
const FLOOR_GAP = 10;
const LABELS_CLEAR_OF_TOTALS = 48;

type Box = [number, number, number, number];

const boxOf = (corners: readonly LngLat[]): Box => [
  Math.min(...corners.map((c) => c[0])),
  Math.min(...corners.map((c) => c[1])),
  Math.max(...corners.map((c) => c[0])),
  Math.max(...corners.map((c) => c[1])),
];

/** Share of the draw that the rides' departures spread over, and how long (in draw) a trail lingers behind its head. */
const STAGGER = 0.45;
const TRAIL = 0.1;

/** A ride at one moment, as shares of its length: drawn up to `head`, hot from `tail`; `hot` lights its head. */
export type Ride = {track: Track; head: number; tail: number; hot: number};

/**
 * Each ride for a value of the floor's draw channel. The rides leave one after
 * another at an even cadence; a ride takes time with the square root of its
 * length (long days out move faster without racing), eased at both ends, and
 * its trail catches up with the head as it arrives.
 */
export function ridesAt(tracks: (Track | null)[], draw: number): (Ride | null)[] {
  const n = tracks.length;
  const stagger = (STAGGER * (n - 1)) / Math.max(1, n);
  const room = 1 - stagger - TRAIL;
  const longest = Math.max(1, ...tracks.map((track) => track?.length ?? 0));
  return tracks.map((track, j) => {
    if (!track) return null;
    const time = room * Math.max(0.4, Math.sqrt(track.length / longest));
    const q = (draw - (n > 1 ? (j / (n - 1)) * stagger : 0)) / time;
    const trail = TRAIL / time;
    return {track, head: inOutSine(q), tail: inOutSine(q - trail), hot: inOutSine(q / 0.1) * (1 - inOutSine((q - 1) / trail))};
  });
}

/** Rate (1/s) of a plate's critically damped edges: they settle in ~0.4 s. */
const PLATE_RATE = 11;
/** Shares of a plate's margin: how close a ride's line may come to the edge, and how softly it takes over the edge there. */
const PLATE_HOLD = 0.35;
const PLATE_SOFT = 0.5;
/** Outward direction of each side of a box: west and south grow down, east and north up. */
const OUT = [-1, -1, 1, 1];
const outward = (box: Box) => box.map((v, k) => OUT[k] * v);
const boxFrom = (out: number[]): Box => [-out[0], -out[1], out[2], out[3]];

/**
 * A floor's plate at every frame of its draw channel. It starts as the margin
 * around the first ride's start and only grows, towards what is drawn plus
 * the margin, on critically damped edges that aim where the lines head now
 * (never where they will go): it answers them as they come, carries on a
 * little as they turn, and many rides at once move it as one. A
 * line on the plate pushes it so the line is never cut; a ride that starts
 * beyond it (a day out that begins elsewhere) is uncovered as the plate
 * reaches out to it, and pushes once it lies on the plate. When the floor is
 * drawn the plate is exactly `final`.
 */
function plateFrames(tracks: (Track | null)[], draws: readonly number[], fps: number, final: Box): Box[] {
  const first = tracks.find((track) => track !== null);
  if (!first) return draws.map(() => final);
  // Each side's margin: how far the final plate reaches beyond all the rides.
  const tight = [-Infinity, -Infinity, -Infinity, -Infinity];
  for (const track of tracks) if (track) outward(extentUpTo(track, track.length)).forEach((v, k) => (tight[k] = Math.max(tight[k], v)));
  const limit = outward(final);
  const pad = limit.map((v, k) => Math.max(0, v - tight[k]));
  const start = outward([first.lon[0], first.lat[0], first.lon[0], first.lat[0]]);
  const landing = start.map((v, k) => v + pad[k]);
  const holds: boolean[] = [];
  const last: number[][] = [];
  const edge = [...landing];
  const x = [...landing];
  const v = [0, 0, 0, 0];
  const dt = 1 / fps;
  const decay = Math.exp(-PLATE_RATE * dt);
  return draws.map((draw) => {
    const target = [...landing];
    const push = [-Infinity, -Infinity, -Infinity, -Infinity];
    ridesAt(tracks, draw).forEach((ride, j) => {
      if (!ride || ride.head <= 0) return;
      const drawn = outward(extentUpTo(ride.track, ride.head * ride.track.length));
      holds[j] ||= drawn.every((d, k) => d + PLATE_HOLD * pad[k] <= edge[k]);
      drawn.forEach((d, k) => {
        // Aim where the line is heading now, a spring's lag ahead, so the edge keeps pace without waiting for it.
        const pace = last[j] ? (d - last[j][k]) / dt : 0;
        target[k] = Math.max(target[k], d + pad[k] + (2 / PLATE_RATE) * pace);
        if (holds[j]) push[k] = Math.max(push[k], d + PLATE_HOLD * pad[k]);
      });
      last[j] = drawn;
    });
    for (let k = 0; k < 4; k++) {
      // One exact step of the spring towards the target held for the frame.
      const d = x[k] - target[k];
      const c = v[k] + PLATE_RATE * d;
      x[k] = target[k] + (d + c * dt) * decay;
      v[k] = (v[k] - PLATE_RATE * c * dt) * decay;
      // A smooth max: the edge gives way to a line running into it.
      const gap = x[k] - push[k];
      const soft = PLATE_SOFT * pad[k];
      const held = Number.isFinite(gap) ? (x[k] + push[k] + Math.sqrt(gap * gap + soft * soft)) / 2 : x[k];
      edge[k] = Math.max(edge[k], Math.min(limit[k], held));
    }
    return boxFrom(edge);
  });
}

const plates = new WeakMap<readonly number[], Box[]>();
const NO_DRAW: readonly number[] = [0];

/** The plate's corners at `frame`, from the floor's frames (cached by its draw channel). */
export function plateAt(
  tracks: (Track | null)[],
  draws: readonly number[],
  frame: number,
  fps: number,
  corners: readonly LngLat[],
): [LngLat, LngLat, LngLat, LngLat] {
  let frames = plates.get(draws);
  if (!frames) {
    frames = plateFrames(tracks, draws, fps, boxOf(corners));
    plates.set(draws, frames);
  }
  const [x0, y0, x1, y1] = frames[Math.max(0, Math.min(frames.length - 1, Math.round(frame)))];
  return [
    [x0, y0],
    [x1, y0],
    [x1, y1],
    [x0, y1],
  ];
}

/** Where a level line at `y` first meets a screen quad from the left; `y` is kept within the quad's height. */
function leftEdgeAt(quad: readonly [number, number][], y: number): [number, number] {
  const ys = quad.map((p) => p[1]);
  const at = Math.min(Math.max(y, Math.min(...ys)), Math.max(...ys));
  let x = Infinity;
  quad.forEach(([x0, y0], i) => {
    const [x1, y1] = quad[(i + 1) % quad.length];
    if (y0 === y1 || at < Math.min(y0, y1) || at > Math.max(y0, y1)) return;
    x = Math.min(x, x0 + ((at - y0) / (y1 - y0)) * (x1 - x0));
  });
  return [Number.isFinite(x) ? x : Math.min(...quad.map((p) => p[0])), at];
}

export function strataScore({spec, tracks, frame, channel, projector, width, height, scale, textScale}: ScoreContext<'strata'>): ScoreOutput {
  const {story} = spec;
  const ops: DrawOp[] = [];
  const texts: TextItem[] = [];

  const portrait = height > width;
  const margins = frameMargins(portrait);
  const marginX = Math.round(margins.x * scale);
  const topY = Math.round(margins.y * scale);

  const final = channel('final');
  const openingAlpha = channel('opening');
  const statsAlpha = channel('stats');
  const fade = channel('fade');
  const black = channel('black');

  const floorCount = story.floors.length;
  const totals = totalsGrid(story.stats, {
    x0: marginX,
    x1: width - marginX,
    bottom: height - topY,
    portrait,
    textScale,
    opacity: statsAlpha,
    id: 'strata-stat',
  });

  // Painter's order: bottom floor (oldest, k=0) to top floor (newest, k=floorCount-1).
  const labelCandidates: {
    k: number;
    floor: StrataFloor;
    /** Screen height of home on the floor: the stack's axis. */
    axisY: number;
    /** The plate on screen. */
    quad: [number, number][];
    alpha: number;
  }[] = [];

  story.floors.forEach((floor, k) => {
    const arrive = spec.channels[`floor${k}`] ? channel(`floor${k}`) : 0;
    if (arrive <= 0.001) return;
    const drawK = spec.channels[`draw${k}`] ? channel(`draw${k}`) : 0;
    const focus = spec.channels[`focus${k}`] ? channel(`focus${k}`) : 0;
    const labelAlpha = spec.channels[`label${k}`] ? channel(`label${k}`) : 0;
    // Each plate lands on its floor from half a step above.
    const lift = floor.targetLift + (1 - arrive) * 0.5 * (floor.step ?? 0);
    const tColor = floorCount > 1 ? k / (floorCount - 1) : 1;
    const floorRGB: RGB = [
      lerp(INK.warmRGB[0], INK.accentRGB[0], tColor),
      lerp(INK.warmRGB[1], INK.accentRGB[1], tColor),
      lerp(INK.warmRGB[2], INK.accentRGB[2], tColor),
    ];

    // The period's rides draw one after another, each led by a hot trail that
    // cools into the floor's colour; settled floors stay legible, the floor in
    // focus is brightest, and at the end all floors even out.
    const floorTracks = floor.trackIndices.map((ti) => (ti >= 0 && ti < tracks.length ? tracks[ti] : null));
    const drawn = ridesAt(floorTracks, drawK);
    // The plate holds what is drawn, and grows with it to hold the whole period.
    const plate = plateAt(floorTracks, spec.channels[`draw${k}`] ?? NO_DRAW, frame, spec.profile.fps, floor.corners);

    // Nearly clear plates: the floors below stay visible through them.
    ops.push({
      kind: 'plate',
      corners: plate,
      lift,
      fill: rgba([12, 12, 11], 0.14 * arrive * fade),
      stroke: rgba(INK.paperRGB, lerp(0.16, 0.42, focus) * arrive * fade),
      strokeWidth: lerp(1.0, 1.4, focus) * scale,
    });

    const level = Math.max(lerp(0.3, 0.95, focus), 0.8 * final);
    const settled = lerp(1.3, 1.9, Math.max(focus, final)) * scale;
    // Many rides at once: quieter heads, so the bloom reads as one.
    const headGlow = 0.75 * Math.min(1, Math.sqrt(8 / Math.max(1, drawn.length)));
    drawn.forEach((ride) => {
      if (!ride || ride.head <= 0) return;
      const {track, head, tail, hot} = ride;
      ops.push({kind: 'track', track, from: 0, to: head * track.length, rgb: floorRGB, alpha: level * arrive * fade, width: settled, lift, clip: plate});
      // The trail: three nested runs to the head, so it brightens towards it.
      if (tail >= 1) return;
      for (let i = 0; i < 3; i++) {
        ops.push({
          kind: 'track',
          track,
          from: lerp(tail, head, i / 3) * track.length,
          to: head * track.length,
          rgb: INK.accentRGB,
          alpha: 0.4 * arrive * fade,
          width: 2.1 * scale,
          head: i === 2 ? headGlow * hot : 0,
          lift,
          clip: plate,
        });
      }
    });

    if (labelAlpha > 0.005) {
      const quad = plate.map(([lon, lat]) => projector.lngLat(lon, lat, lift));
      const [, axisY, onScreen] = projector.lngLat(story.home[0], story.home[1], lift);
      if (onScreen && quad.every(([, , ok]) => ok)) {
        labelCandidates.push({k, floor, axisY, quad: quad.map(([x, y]) => [x, y]), alpha: labelAlpha * fade});
      }
    }
  });

  // Right-aligned column of floor distances, in the stack's order. Each sits
  // level with its floor on the stack's axis (the floors are evenly spaced, so
  // the column is too), spread only where the blocks would touch, and is led
  // to its plate by a level hairline: the hairlines never cross.
  if (labelCandidates.length > 0) {
    labelCandidates.sort((a, b) => a.k - b.k);
    // y is the leader's height: the number's middle, with the period label above it.
    const blockAbove = (size: number) => (metricHeight(size) - size / 2) * textScale;
    const top = topY + lerp(40, 110, openingAlpha) * textScale;
    const footer = totals.top - LABELS_CLEAR_OF_TOTALS * textScale;
    // The list size when the column has room: n blocks and n - 1 gaps between the top
    // and the totals. Down to the tag size when many floors share it.
    const n = labelCandidates.length;
    const fit = ((footer - top) / textScale - (n - 1) * FLOOR_GAP) / n - LABEL_LINE - LABEL_GAP;
    const size = Math.max(TYPE.tag, Math.min(TYPE.figure, fit));
    const minGap = (metricHeight(size) + FLOOR_GAP) * textScale;
    const minY = top + blockAbove(size);
    const maxY = footer - (size / 2) * textScale;
    const ys = labelCandidates.map((c) => c.axisY);
    ys[0] = Math.min(ys[0], maxY);
    for (let i = 1; i < ys.length; i++) {
      ys[i] = Math.min(ys[i], ys[i - 1] - minGap);
    }
    if (ys[ys.length - 1] < minY) {
      ys[ys.length - 1] = minY;
      for (let i = ys.length - 2; i >= 0; i--) {
        ys[i] = Math.max(ys[i], ys[i + 1] + minGap);
      }
    }
    // A fixed column, just left of the room the camera keeps for the stack.
    const colX = Math.max((portrait ? 185 : 235) * scale, width * (portrait ? 0.3 : 0.27) - 24 * scale);

    labelCandidates.forEach((c, idx) => {
      const labelY = ys[idx];
      const [x, y] = leftEdgeAt(c.quad, labelY);
      if (x > colX + 6 * scale) {
        // Level when the label is level with its plate; a label spread past it bends once, at the column.
        const elbowX = colX + 12 * scale;
        ops.push({
          kind: 'screen-path',
          xy: y === labelY ? [colX + 4 * scale, labelY, x, y] : [colX + 4 * scale, labelY, elbowX, labelY, x, y],
          rgb: INK.paperRGB,
          alpha: 0.24 * c.alpha,
          width: 1 * scale,
        });
      }
      texts.push({
        kind: 'metric',
        id: `floor-label-${c.k}`,
        x: colX - 10 * scale,
        y: labelY - blockAbove(size),
        label: c.floor.label,
        value: c.floor.value,
        unit: c.floor.unit,
        align: 'right',
        size,
        opacity: c.alpha,
      });
    });
  }

  if (openingAlpha > 0.004) {
    texts.push({
      kind: 'caption',
      id: 'strata-opening',
      x: marginX,
      y: topY,
      label: story.opening.label,
      text: story.opening.text,
      accent: story.opening.accent,
      size: TYPE.title,
      maxWidth: width - 2 * marginX,
      opacity: openingAlpha,
    });
  }

  if (statsAlpha > 0.004) texts.push(...totals.items);

  return {ops, texts, black, scrim: {top: openingAlpha, bottom: statsAlpha}};
}
