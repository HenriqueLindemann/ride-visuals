import {type DrawOp, type RGB, rgba} from '../core/draw';
import {clamp01, lerp, outCubic} from '../core/ease';
import type {LngLat} from '../core/geo';
import {metricHeight, STORY_SAFE_BOTTOM, STORY_SAFE_TOP} from '../core/layout';
import {INK, type TextItem} from '../core/Typography';
import type {ScoreContext, ScoreOutput} from './index';

export type StrataFloor = {
  id: string;
  label: string;
  subLabel: string;
  targetLift: number;
  /** Vertical distance between floors (m); a landing plate starts this far above. */
  step?: number;
  trackIndices: number[];
};

export type StrataStory = {
  corners: [LngLat, LngLat, LngLat, LngLat];
  floors: StrataFloor[];
  opening: {
    label: string;
    text: string;
    accent?: string;
  };
  stats: {
    label: string;
    value: string;
    unit?: string;
  }[];
};

/** Portrait totals: a 2x2 block resting on the safe area, the label column stopping above it. */
const PORTRAIT_STAT_SIZE = 50;
const PORTRAIT_STAT_ROW_PITCH = 110;
const LABELS_CLEAR_OF_STATS = 60;

export function strataScore({spec, tracks, channel, projector, width, height, scale}: ScoreContext): ScoreOutput {
  const story = spec.story as unknown as StrataStory;
  const ops: DrawOp[] = [];
  const texts: TextItem[] = [];

  const portrait = height > width;
  const marginX = Math.round((portrait ? 68 : 112) * scale);
  const topY = Math.round((portrait ? STORY_SAFE_TOP : 84) * scale);
  const statsBottomRowY = Math.round(height - (STORY_SAFE_BOTTOM + metricHeight(PORTRAIT_STAT_SIZE)) * scale);
  const statsTopRowY = Math.round(statsBottomRowY - PORTRAIT_STAT_ROW_PITCH * scale);

  const final = channel('final');
  const openingAlpha = channel('opening');
  const statsAlpha = channel('stats');
  const fade = channel('fade');
  const black = channel('black');

  const floorCount = story.floors.length;

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

  // Left-aligned column of floor labels with leaders and vertical collision avoidance.
  if (labelCandidates.length > 0) {
    // Sort bottom-to-top on screen (largest y first).
    labelCandidates.sort((a, b) => b.leftY - a.leftY);
    const maxY = portrait ? statsTopRowY - LABELS_CLEAR_OF_STATS * scale : height - 210 * scale;
    const minY = topY + (openingAlpha > 0.05 ? 110 : 40) * scale;
    // A tag with its sub-line is ~47 px tall at 1080p: keep a clear gap between them,
    // tightening slightly only when many floors share a short vertical span.
    const spanY = Math.max(0, maxY - minY);
    const minGap =
      labelCandidates.length > 1
        ? Math.min(54 * scale, Math.max(28 * scale, spanY / (labelCandidates.length - 1)))
        : 54 * scale;
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
        kind: 'tag',
        id: `floor-label-${c.k}`,
        x: colX,
        y: labelY,
        leader: 0,
        direction: 'left',
        text: c.floor.label,
        sub: c.floor.subLabel,
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
      size: portrait ? 42 : 46,
      maxWidth: width - 2 * marginX,
      opacity: openingAlpha,
    });
  }

  if (statsAlpha > 0.004 && story.stats.length > 0) {
    if (portrait) {
      story.stats.slice(0, 4).forEach((stat, idx) => {
        const rightCol = idx % 2 === 1;
        const rowY = idx < 2 ? statsTopRowY : statsBottomRowY;
        texts.push({
          kind: 'metric',
          id: `strata-stat-${idx}`,
          x: rightCol ? width - marginX : marginX,
          y: rowY,
          label: stat.label,
          value: stat.value,
          unit: stat.unit,
          align: rightCol ? 'right' : 'left',
          size: PORTRAIT_STAT_SIZE,
          opacity: statsAlpha,
        });
      });
    } else {
      const statY = Math.round(height - 148 * scale);
      const spanW = width - 2 * marginX;
      const count = story.stats.length;
      story.stats.forEach((stat, idx) => {
        const isLast = idx === count - 1;
        const x = isLast ? width - marginX : marginX + (idx / Math.max(1, count - 1)) * spanW * 0.88;
        texts.push({
          kind: 'metric',
          id: `strata-stat-${idx}`,
          x,
          y: statY,
          label: stat.label,
          value: stat.value,
          unit: stat.unit,
          align: isLast ? 'right' : 'left',
          size: 56,
          opacity: statsAlpha,
        });
      });
    }
  }

  return {ops, texts, black};
}
