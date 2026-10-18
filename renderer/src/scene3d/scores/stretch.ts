import type {DrawOp, RGB} from '../core/draw';
import {clamp01, lerp, outCubic} from '../core/ease';
import {destination, type LngLat} from '../core/geo';
import {pointAtDistance} from '../core/track';
import {INK, type TextItem} from '../core/Typography';
import type {ScoreContext, ScoreOutput} from './index';

export type StretchRideMeta = {
  trackIndex: number;
  lengthM: number;
  beforeM: number;
  restAlpha: number;
  restWidth: number;
};

export type StretchStory = {
  home: [number, number];
  pullBearing: number;
  totalM: number;
  totalKm: number;
  rides: StretchRideMeta[];
  opening: {
    label: string;
    text: string;
    accent?: string;
  };
  counter: {
    label: string;
    unit: string;
  };
  ending: {
    label: string;
    text: string;
    accent?: string;
  };
  destination?: {
    name: string;
    at: [number, number];
    distanceM: number;
  } | null;
};

export function stretchScore({spec, tracks, channel, projector, width, height, scale}: ScoreContext): ScoreOutput {
  const story = spec.story as unknown as StretchStory;
  const ops: DrawOp[] = [];
  const texts: TextItem[] = [];

  const portrait = height > width;
  const marginX = Math.round((portrait ? 72 : 112) * scale);
  const topY = Math.round((portrait ? 104 : 88) * scale);

  const laid = channel('laid');
  const openingAlpha = channel('opening');
  const counterAlpha = channel('counter');
  const kmVal = channel('km');
  const landed = channel('landed');
  const ghost = channel('ghost');
  const endingAlpha = channel('ending');
  const fade = channel('fade');
  const black = channel('black');

  // Home anchor dot.
  ops.push({
    kind: 'dot',
    at: story.home,
    radius: 3.2 * scale,
    rgb: INK.paperRGB,
    alpha: 0.9 * fade,
  });

  // Every ride boundary keeps its true distance along the line. A boundary
  // closer than a few pixels to its neighbours (short rides at continental
  // scale) fades out in place rather than being thinned by selection.
  const beads: {at: number; alpha: number}[] = [];

  // Each ride waits where it was ridden until its turn comes, then is used up.
  story.rides.forEach((ride, k) => {
    const m = clamp01((laid - ride.beforeM) / Math.max(1, ride.lengthM));
    if (m >= 1) {
      const junction = ride.beforeM + ride.lengthM;
      const next = story.rides[k + 1];
      if (next && junction < story.totalM - 10) {
        const gapPx = Math.min(ride.lengthM, next.lengthM) / Math.max(projector.resolution, 1e-6);
        const alpha = clamp01((gapPx - 4 * scale) / (8 * scale));
        if (alpha > 0.01) beads.push({at: junction, alpha});
      }
      return;
    }
    if (ride.trackIndex < 0 || ride.trackIndex >= tracks.length) return;
    const tr = tracks[ride.trackIndex];
    if (m <= 0) {
      const cue = outCubic(clamp01((laid - ride.beforeM + 10_000) / 10_000));
      const rgb: RGB = [
        lerp(INK.warmRGB[0], INK.accentRGB[0], cue),
        lerp(INK.warmRGB[1], INK.accentRGB[1], cue),
        lerp(INK.warmRGB[2], INK.accentRGB[2], cue),
      ];
      ops.push({
        kind: 'track',
        track: tr,
        from: 0,
        to: tr.length,
        rgb,
        alpha: lerp(ride.restAlpha, 0.9, cue) * fade,
        width: lerp(ride.restWidth, 2.0, cue) * scale,
      });
      return;
    }
    // The ride keeps its shape and is used up from home along its own road,
    // while the line's tip advances by the same distance: two heads, one
    // curving, one straight.
    const usedM = m * tr.length;
    ops.push({
      kind: 'track',
      track: tr,
      from: usedM,
      to: tr.length,
      rgb: INK.accentRGB,
      alpha: 0.95 * fade,
      width: 2.2 * scale,
    });
    const at = pointAtDistance(tr, usedM);
    ops.push({kind: 'dot', at: [at.lon, at.lat], radius: 3.4 * scale, rgb: INK.accentRGB, alpha: fade});
  });

  // The stretched great-circle line growing out from home.
  const S = Math.min(story.totalM, Math.max(0, laid));
  if (S > 1) {
    const steps = Math.min(220, Math.max(48, Math.ceil(S / 35_000)));
    const pts: LngLat[] = [];
    for (let i = 0; i <= steps; i++) {
      pts.push(destination(story.home, story.pullBearing, S * (i / steps)));
    }
    ops.push({
      kind: 'path',
      pts,
      rgb: INK.accentRGB,
      alpha: 0.96 * fade,
      width: 2.5 * scale,
      head: S < story.totalM * 0.998 ? 1 : 0,
    });
    for (const bead of beads) {
      if (bead.at < S) {
        ops.push({
          kind: 'dot',
          at: destination(story.home, story.pullBearing, bead.at),
          radius: 2.1 * scale,
          rgb: INK.paperRGB,
          alpha: 0.72 * bead.alpha * fade,
        });
      }
    }
  }

  // Landing pulse at the tip.
  if (landed > 0 && landed < 1) {
    ops.push({
      kind: 'pulse',
      at: destination(story.home, story.pullBearing, story.totalM),
      age: landed,
      radius: 42 * scale,
      rgb: INK.accentRGB,
      alpha: 0.9 * fade,
    });
  }

  // Optional destination marker and faint continuation line.
  if (ghost > 0.005 && story.destination) {
    const dest = story.destination;
    if (dest.distanceM > story.totalM * 1.01) {
      const restPts: LngLat[] = [];
      const steps = 48;
      for (let i = 0; i <= steps; i++) {
        const d = lerp(story.totalM, dest.distanceM, (i / steps) * outCubic(ghost));
        restPts.push(destination(story.home, story.pullBearing, d));
      }
      ops.push({
        kind: 'path',
        pts: restPts,
        rgb: INK.paperRGB,
        alpha: 0.35 * ghost * fade,
        width: 1.1 * scale,
      });
    }
    ops.push({
      kind: 'dot',
      at: dest.at,
      radius: 3.0 * scale,
      rgb: INK.paperRGB,
      alpha: 0.85 * ghost * fade,
    });
    const [dx, dy, visible] = projector.lngLat(dest.at[0], dest.at[1]);
    if (visible && dy > topY + 150 * scale && dy < height - 100 * scale && dx > marginX + 60 * scale && dx < width - marginX - 60 * scale) {
      texts.push({
        kind: 'tag',
        id: 'dest-tag',
        x: dx,
        y: dy,
        leader: 32 * scale,
        direction: 'up',
        text: dest.name,
        opacity: ghost * fade,
      });
    }
  }

  if (openingAlpha > 0.004) {
    texts.push({
      kind: 'caption',
      id: 'stretch-opening',
      x: marginX,
      y: topY,
      label: story.opening.label,
      text: story.opening.text,
      accent: story.opening.accent,
      size: portrait ? 42 : 46,
      opacity: openingAlpha,
    });
  }

  if (counterAlpha > 0.004) {
    const fmt = new Intl.NumberFormat(spec.locale, {
      maximumFractionDigits: kmVal < 100 ? 1 : 0,
      minimumFractionDigits: kmVal < 100 ? 1 : 0,
    });
    texts.push({
      kind: 'metric',
      id: 'stretch-counter',
      x: marginX,
      y: topY,
      label: story.counter.label,
      value: fmt.format(Math.max(0, kmVal)),
      unit: story.counter.unit,
      align: 'left',
      size: portrait ? 62 : 70,
      opacity: counterAlpha,
    });
  }

  if (endingAlpha > 0.004) {
    texts.push({
      kind: 'caption',
      id: 'stretch-ending',
      x: marginX,
      y: topY,
      label: story.ending.label,
      text: story.ending.text,
      accent: story.ending.accent,
      size: portrait ? 42 : 46,
      opacity: endingAlpha,
    });
  }

  return {ops, texts, black};
}
