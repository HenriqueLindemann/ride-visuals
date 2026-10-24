import {type DrawOp, type RGB, rgba} from '../core/draw';
import {clamp01, lerp, outCubic} from '../core/ease';
import type {LngLat} from '../core/geo';
import {frameMargins, LABEL_GAP, LABEL_LINE, metricHeight, totalsGrid, TYPE} from '../core/layout';
import {INK, type TextItem} from '../core/Typography';
import type {StrataFloor} from '../stories';
import type {ScoreContext, ScoreOutput} from './index';

/** Clear space between two floor blocks, and between the column and the totals (px at scale 1). */
const FLOOR_GAP = 10;
const LABELS_CLEAR_OF_TOTALS = 48;

export function strataScore({spec, tracks, channel, projector, width, height, scale, textScale}: ScoreContext<'strata'>): ScoreOutput {
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
    leftX: number;
    leftY: number;
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

    // Nearly clear plates: the floors below stay visible through them.
    ops.push({
      kind: 'plate',
      corners: story.corners,
      lift,
      fill: rgba([12, 12, 11], 0.14 * arrive * fade),
      stroke: rgba(INK.paperRGB, lerp(0.16, 0.42, focus) * arrive * fade),
      strokeWidth: lerp(1.0, 1.4, focus) * scale,
    });

    // The period's rides draw one after another; settled floors stay legible,
    // the floor in focus is brightest, and at the end all floors even out.
    const n = floor.trackIndices.length;
    const level = Math.max(lerp(0.3, 0.95, focus), 0.8 * final);
    floor.trackIndices.forEach((ti, j) => {
      if (ti < 0 || ti >= tracks.length) return;
      const tr = tracks[ti];
      const startFrac = n > 1 ? (j / n) * 0.6 : 0;
      const p = outCubic(clamp01((drawK - startFrac) / 0.4));
      if (p <= 0) return;
      const hot = p < 1;
      ops.push({
        kind: 'track',
        track: tr,
        from: 0,
        to: p * tr.length,
        rgb: hot ? INK.accentRGB : floorRGB,
        alpha: (hot ? 0.95 : level) * arrive * fade,
        width: (hot ? 2.1 : lerp(1.3, 1.9, Math.max(focus, final))) * scale,
        head: hot ? 0.75 : 0,
        lift,
        clip: story.corners,
      });
    });

    if (labelAlpha > 0.005) {
      let bestX = Infinity;
      let bestY = height * 0.5;
      for (const [lon, lat] of story.corners) {
        const [px, py, ok] = projector.lngLat(lon, lat, lift);
        if (ok && px < bestX) {
          bestX = px;
          bestY = py;
        }
      }
      if (Number.isFinite(bestX)) {
        labelCandidates.push({k, floor, leftX: bestX, leftY: bestY, alpha: labelAlpha * fade});
      }
    }
  });

  // Right-aligned column of floor distances, each led to its plate by a
  // hairline at the middle of its number; collisions resolved vertically.
  if (labelCandidates.length > 0) {
    // Sort bottom-to-top on screen (largest y first).
    labelCandidates.sort((a, b) => b.leftY - a.leftY);
    // y is the leader's height: the number's middle, with the period label above it.
    const blockAbove = (size: number) => (metricHeight(size) - size / 2) * textScale;
    const top = topY + (openingAlpha > 0.05 ? 110 : 40) * textScale;
    const footer = totals.top - LABELS_CLEAR_OF_TOTALS * textScale;
    // The list size when the column has room: n blocks and n - 1 gaps between the top
    // and the totals. Down to the tag size when many floors share it.
    const n = labelCandidates.length;
    const fit = ((footer - top) / textScale - (n - 1) * FLOOR_GAP) / n - LABEL_LINE - LABEL_GAP;
    const size = Math.max(TYPE.tag, Math.min(TYPE.figure, fit));
    const minGap = (metricHeight(size) + FLOOR_GAP) * textScale;
    const minY = top + blockAbove(size);
    const maxY = footer - (size / 2) * textScale;
    const ys = labelCandidates.map((c) => c.leftY);
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
    const minPlateX = Math.min(...labelCandidates.map((c) => c.leftX));
    const colX = Math.max(
      (portrait ? 185 : 235) * scale,
      Math.min(width * (portrait ? 0.3 : 0.28), minPlateX - 28 * scale),
    );

    labelCandidates.forEach((c, idx) => {
      const labelY = ys[idx];
      const elbowX = colX + 12 * scale;
      if (c.leftX > colX + 6 * scale) {
        ops.push({
          kind: 'screen-path',
          xy: [colX + 4 * scale, labelY, elbowX, labelY, c.leftX, c.leftY],
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

  return {ops, texts, black};
}
