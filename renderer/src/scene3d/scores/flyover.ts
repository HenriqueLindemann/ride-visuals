import type {DrawOp, Knockout} from '../core/draw';
import {clamp01, smootherstep} from '../core/ease';
import {mercX, mercY} from '../core/geo';
import {pointAtDistance} from '../core/track';
import {INK, type TextItem} from '../core/Typography';
import type {ScoreContext, ScoreOutput} from './index';

export type FlyoverClimb = {
  lon: number;
  lat: number;
  alt: number;
  startAlt: number;
  startM: number;
  endM: number;
  gainText: string;
  subText: string;
  hero: boolean;
  /** Placement chosen by the director so the text never covers the route. */
  tagDir?: 'up' | 'left' | 'right';
  tagLeader?: number;
  /** Long enough for the live readout (channel `readout<k>`). */
  readout?: boolean;
  /** The climb's own profile, 0..1 between its lowest and highest point. */
  profile?: number[];
  /** Summit altitude, e.g. "666 m". */
  topText?: string;
};

/** The vertical plane (facing the level side camera) the route straightens into. */
export type FlyoverUnfold = {
  center: [number, number];
  /** Screen-right unit vector (east, north). */
  right: [number, number];
  lineM: number;
  /** Plane baseline height and vertical scale (exaggerated metres per metre). */
  baseZ: number;
  vertical: number;
  minAlt: number;
  altRange: number;
};

/** Screen furniture placement (px), decided by the director (`_Layout` in flyover.py). */
export type FlyoverLayout = {
  marginX: number;
  topY: number;
  /** Top of the corner counters. */
  bottomY: number;
  /** Height (m) the route is drawn above the relief, so slopes do not shadow their own road. */
  routeLift: number;
  /** Live climb readout: its box, and the profile strip inside it. */
  readout: {box: [number, number, number, number]; stripTop: number; stripBottom: number};
};

export type FlyoverStat = {
  label: string;
  value: string;
  unit?: string;
};

export type FlyoverStory = {
  title: {
    label?: string;
    text: string;
    accent?: string;
  };
  labels: {
    distance: string;
    ascent: string;
    climb?: string;
    kmUnit: string;
    mUnit: string;
    zeroKm: string;
    totalKm: string;
    peakAlt: string;
  };
  unfold: FlyoverUnfold;
  layout: FlyoverLayout;
  totalM: number;
  profile: number[];
  peakFraction: number;
  climbs: FlyoverClimb[];
  stats: FlyoverStat[];
};

const scratch = new Float64Array(3);
const gradeFormats = new Map<string, Intl.NumberFormat>();

/** Whole-number percent formatter, built once per locale (not every frame). */
function gradeFormat(locale: string) {
  let format = gradeFormats.get(locale);
  if (!format) gradeFormats.set(locale, (format = new Intl.NumberFormat(locale, {maximumFractionDigits: 0})));
  return format;
}

export function flyoverScore({spec, tracks, channel, projector, width, height, scale}: ScoreContext): ScoreOutput {
  const story = spec.story as unknown as FlyoverStory;
  const track = tracks[0];
  const ops: DrawOp[] = [];
  const texts: TextItem[] = [];
  const knockouts: Knockout[] = [];
  const overlay: DrawOp[] = [];

  const portrait = height > width;
  const {marginX, topY, bottomY, routeLift} = story.layout;

  const head = channel('head');
  const headDot = channel('headDot');
  const titleAlpha = channel('title');
  const countersAlpha = channel('counters');
  const kmVal = channel('km');
  const ascentVal = channel('ascent');
  const beat = channel('beat');
  const unfold = channel('unfold');
  const chart = channel('chart');
  const statsAlpha = channel('stats');
  const black = channel('black');

  const hasRelief = projector.exaggeration > 0.01;
  if (unfold <= 0.0001) {
    // The route only exists behind the rider; until the ride sets off, a dot marks the start.
    if (head <= 1 && headDot > 0.003) {
      const start = pointAtDistance(track, 0);
      ops.push({
        kind: 'dot',
        at: [start.lon, start.lat],
        radius: 5 * scale,
        rgb: INK.accentRGB,
        alpha: headDot,
        lift: routeLift,
        occlude: hasRelief,
      });
    }
    if (head > 1) {
      ops.push({
        kind: 'track',
        track,
        from: 0,
        to: head,
        rgb: INK.accentRGB,
        alpha: 0.96,
        width: 2.8 * scale,
        head: headDot,
        lift: routeLift,
        occlude: hasRelief,
      });
    }
  }

  // Hero climb cutaway stems: vertical hairlines from the foot altitude up to the route.
  const hero = story.climbs.find((c) => c.hero);
  if (hero && beat > 0.01 && head > hero.startM) {
    const toM = Math.min(head, hero.endM);
    const stepM = Math.max(45, (hero.endM - hero.startM) / 46);
    for (let d = hero.startM; d <= toM; d += stepM) {
      const pt = pointAtDistance(track, d);
      ops.push({
        kind: 'stem',
        at: [pt.lon, pt.lat],
        from: hero.startAlt,
        to: pt.alt,
        rgb: INK.accentRGB,
        alpha: 0.58 * beat,
        width: 1.1 * scale,
        fade: true,
      });
    }
  }

  // Featured climb summit tags.
  story.climbs.forEach((climb, k) => {
    const alpha = spec.channels[`climb${k}`] ? channel(`climb${k}`) : 0;
    if (alpha <= 0.005) return;
    const mx = mercX(climb.lon);
    const my = mercY(climb.lat);
    const z = projector.ground ? projector.ground(mx, my) : climb.alt * projector.exaggeration;
    if (!projector.merc(mx, my, z, scratch)) return;
    const x = Math.max(marginX + 90 * scale, Math.min(width - marginX - 90 * scale, scratch[0]));
    const y = Math.max(topY + 96 * scale, Math.min(bottomY - 64 * scale, scratch[1]));
    texts.push({
      kind: 'tag',
      id: `climb-${k}`,
      x,
      y,
      leader: (climb.tagLeader ?? 44) * scale,
      direction: climb.tagDir ?? 'up',
      text: climb.gainText,
      sub: climb.subText,
      opacity: alpha,
    });
    ops.push({
      kind: 'pulse',
      at: [climb.lon, climb.lat],
      age: clamp01(1 - alpha * 0.85),
      radius: 32 * scale,
      rgb: INK.accentRGB,
      alpha: 0.72 * alpha,
    });
  });

  story.climbs.forEach((climb, k) => {
    const alpha = climb.readout && spec.channels[`readout${k}`] ? channel(`readout${k}`) : 0;
    if (alpha > 0.004 && climb.profile) {
      climbReadout(climb, alpha, head, channel('grade'), story, spec.locale, scale, overlay, texts, knockouts);
    }
  });

  // Opening title (top-left).
  if (titleAlpha > 0.004) {
    texts.push({
      kind: 'caption',
      id: 'opening-title',
      x: marginX,
      y: topY,
      label: story.title.label,
      text: story.title.text,
      accent: story.title.accent,
      size: portrait ? 44 : 48,
      opacity: titleAlpha,
    });
    const titleSize = (portrait ? 44 : 48) * scale;
    const titleW = Math.max(story.title.text.length * 0.56 * titleSize, (story.title.label?.length ?? 0) * 9 * scale);
    knockouts.push({box: [marginX, topY, marginX + titleW, topY + 22 * scale + titleSize * 1.15], alpha: titleAlpha});
  }

  // Live counters during the 3D ride (bottom-left and bottom-right).
  if (countersAlpha > 0.004) {
    const fmtKm = new Intl.NumberFormat(spec.locale, {minimumFractionDigits: 1, maximumFractionDigits: 1});
    const fmtInt = new Intl.NumberFormat(spec.locale, {maximumFractionDigits: 0});
    const metricSize = portrait ? 60 : 68;
    const kmText = fmtKm.format(Math.max(0, kmVal));
    const ascentText = `+${fmtInt.format(Math.max(0, Math.round(ascentVal)))}`;
    const metricPx = metricSize * scale;
    const metricH = 22 * scale + metricPx;
    const metricW = (n: number) => n * 0.56 * metricPx + 0.6 * metricPx;
    knockouts.push(
      {box: [marginX, bottomY, marginX + metricW(kmText.length), bottomY + metricH], alpha: countersAlpha},
      {box: [width - marginX - metricW(ascentText.length), bottomY, width - marginX, bottomY + metricH], alpha: countersAlpha},
    );
    texts.push({
      kind: 'metric',
      id: 'live-km',
      x: marginX,
      y: bottomY,
      label: story.labels.distance,
      value: kmText,
      unit: story.labels.kmUnit,
      align: 'left',
      size: metricSize,
      opacity: countersAlpha,
    });
    texts.push({
      kind: 'metric',
      id: 'live-ascent',
      x: width - marginX,
      y: bottomY,
      label: story.labels.ascent,
      value: ascentText,
      unit: story.labels.mUnit,
      align: 'right',
      size: metricSize,
      opacity: countersAlpha,
    });
  }

  // Ending: seen level from the side, the route lifts off the land and
  // straightens into a vertical plane: its own elevation profile.
  if (unfold > 0.0001) {
    const u = story.unfold;
    const prof = story.profile;
    const n = prof.length;
    const kLon = 111_320 * Math.max(0.05, Math.cos((u.center[1] * Math.PI) / 180));
    const kLat = 110_540;
    // The land hides the route only until it starts lifting off (the land is dissolving by then).
    const occlude = unfold < 0.02 && projector.inAir;
    const planeAt = (f: number, z: number, out: Float64Array) => {
      const off = (f - 0.5) * u.lineM;
      return projector.merc(mercX(u.center[0] + (off * u.right[0]) / kLon), mercY(u.center[1] + (off * u.right[1]) / kLat), z, out);
    };
    // Two clean moves: first every point slides straight onto the plane (seen
    // from the side this barely changes the picture), then, inside that plane
    // and facing the camera, distance becomes x and altitude takes the
    // profile's scale.
    const flatten = smootherstep(unfold / 0.45);
    const inPlane = smootherstep((unfold - 0.3) / 0.7);
    const runs: number[][] = [];
    let run: number[] = [];
    for (let i = 0; i < n; i++) {
      const f = i / Math.max(1, n - 1);
      const pt = pointAtDistance(track, f * track.length);
      const mx0 = mercX(pt.lon);
      const my0 = mercY(pt.lat);
      const z0 = projector.ground ? projector.ground(mx0, my0) + routeLift : pt.alt * projector.exaggeration;
      // Plane coordinates: `along` (screen-right) and `depth` (towards the camera's view).
      const dx = (pt.lon - u.center[0]) * kLon;
      const dy = (pt.lat - u.center[1]) * kLat;
      const along0 = dx * u.right[0] + dy * u.right[1];
      const depth0 = -dx * u.right[1] + dy * u.right[0];
      const along = along0 + ((f - 0.5) * u.lineM - along0) * inPlane;
      const depth = depth0 * (1 - flatten);
      const ex = along * u.right[0] - depth * u.right[1];
      const ey = along * u.right[1] + depth * u.right[0];
      const mx = mercX(u.center[0] + ex / kLon);
      const my = mercY(u.center[1] + ey / kLat);
      const z = z0 + (u.baseZ + prof[i] * u.altRange * u.vertical - z0) * inPlane;
      const visible = occlude ? projector.inAir!(mx, my, z, scratch) === 1 : projector.merc(mx, my, z, scratch);
      if (!visible) {
        if (run.length >= 4) runs.push(run);
        run = [];
        continue;
      }
      run.push(scratch[0], scratch[1]);
    }
    if (run.length >= 4) runs.push(run);

    // The baseline of the finished profile, in screen space.
    planeAt(0, u.baseZ, scratch);
    const x0 = scratch[0];
    const y0 = scratch[1];
    planeAt(1, u.baseZ, scratch);
    const x1 = scratch[0];
    const baseY = 0.5 * (y0 + scratch[1]);
    const whole = runs.length === 1 && runs[0].length === n * 2;

    if (chart > 0.004) {
      ops.push({kind: 'screen-path', xy: [x0, baseY, x1, baseY], rgb: INK.paperRGB, alpha: 0.24 * chart, width: 1 * scale});
      texts.push({kind: 'caption', id: 'axis-start', x: x0, y: baseY + 14 * scale, text: story.labels.zeroKm, size: 16, opacity: chart * 0.72});
      texts.push({kind: 'caption', id: 'axis-end', x: x1, y: baseY + 14 * scale, text: story.labels.totalKm, size: 16, align: 'right', opacity: chart * 0.72});
      const peakIdx = Math.min(n - 1, Math.max(0, Math.round(story.peakFraction * (n - 1))));
      planeAt(story.peakFraction, u.baseZ + prof[peakIdx] * u.altRange * u.vertical, scratch);
      texts.push({
        kind: 'tag',
        id: 'peak-alt',
        x: Math.max(x0 + 48 * scale, Math.min(x1 - 48 * scale, scratch[0])),
        y: scratch[1],
        leader: 34 * scale,
        direction: 'up',
        text: story.labels.peakAlt,
        opacity: chart,
      });
    }
    // The featured climbs stand out of the finished profile: the same climbs
    // the readout followed during the ride.
    if (whole && chart > 0.004) {
      const xy = runs[0];
      for (const climb of story.climbs) {
        const i0 = Math.max(0, Math.round((climb.startM / story.totalM) * (n - 1)));
        const i1 = Math.min(n - 1, Math.round((climb.endM / story.totalM) * (n - 1)));
        if (i1 - i0 < 2) continue;
        ops.push({
          kind: 'screen-path',
          xy: xy.slice(i0 * 2, (i1 + 1) * 2),
          rgb: INK.accentRGB,
          alpha: 0,
          width: 0,
          fillTo: baseY,
          fillAlpha: (climb.hero ? 0.26 : 0.16) * chart,
        });
      }
    }
    for (const xy of runs) {
      ops.push({
        kind: 'screen-path',
        xy,
        rgb: INK.accentRGB,
        alpha: 0.96,
        width: 2.5 * scale,
        fillTo: whole && chart > 0.004 ? baseY : undefined,
        fillAlpha: 0.18 * chart,
      });
    }

    if (statsAlpha > 0.004 && story.stats.length > 0) {
      if (portrait) {
        const rows = [baseY + 0.1 * height, baseY + 0.19 * height];
        story.stats.slice(0, 4).forEach((stat, idx) => {
          const rightCol = idx % 2 === 1;
          texts.push({
            kind: 'metric',
            id: `stat-${idx}`,
            x: rightCol ? x1 : x0,
            y: Math.round(rows[idx < 2 ? 0 : 1]),
            label: stat.label,
            value: stat.value,
            unit: stat.unit,
            align: rightCol ? 'right' : 'left',
            size: 50,
            opacity: statsAlpha,
          });
        });
      } else {
        const statY = Math.round(baseY + 0.13 * height);
        const count = story.stats.length;
        story.stats.forEach((stat, idx) => {
          const isLast = idx === count - 1;
          texts.push({
            kind: 'metric',
            id: `stat-${idx}`,
            x: isLast ? x1 : x0 + (idx / Math.max(1, count - 1)) * (x1 - x0) * 0.88,
            y: statY,
            label: stat.label,
            value: stat.value,
            unit: stat.unit,
            align: isLast ? 'right' : 'left',
            size: 54,
            opacity: statsAlpha,
          });
        });
      }
    }
  }

  return {ops, texts, black, knockouts, overlay};
}

/**
 * Live climb readout, in its reserved box: a label row (climb, summit
 * altitude), the climb's profile drawn only as far as it has been ridden over
 * a baseline as long as the whole climb, and the current grade under the rider.
 */
function climbReadout(
  climb: FlyoverClimb,
  alpha: number,
  head: number,
  grade: number,
  story: FlyoverStory,
  locale: string,
  scale: number,
  ops: DrawOp[],
  texts: TextItem[],
  knockouts: Knockout[],
) {
  const {box, stripTop: top, stripBottom: base} = story.layout.readout;
  const [x0, y0, x1, y1] = box;
  const prof = climb.profile!;
  const n = prof.length;
  const f = clamp01((head - climb.startM) / Math.max(1, climb.endM - climb.startM));
  const xAt = (u: number) => x0 + u * (x1 - x0);
  const yAt = (v: number) => base - v * (base - top);

  knockouts.push({box: [x0 - 18 * scale, y0 - 6 * scale, x1 + 18 * scale, y1], alpha});
  ops.push({kind: 'screen-path', xy: [x0, base, x1, base], rgb: INK.paperRGB, alpha: 0.24 * alpha, width: scale});
  ops.push({kind: 'screen-path', xy: [x1, base, x1, top - 4 * scale], rgb: INK.paperRGB, alpha: 0.24 * alpha, width: scale});
  const at = f * (n - 1);
  const i0 = Math.floor(at);
  if (f > 0) {
    const xy: number[] = [];
    for (let i = 0; i <= i0; i++) xy.push(xAt(i / (n - 1)), yAt(prof[i]));
    const next = prof[Math.min(n - 1, i0 + 1)];
    xy.push(xAt(f), yAt(prof[i0] + (next - prof[i0]) * (at - i0)));
    ops.push({
      kind: 'screen-path',
      xy,
      rgb: INK.accentRGB,
      alpha: 0.96 * alpha,
      width: 2 * scale,
      fillTo: base,
      fillAlpha: 0.2 * alpha,
      head: alpha,
    });
  }
  texts.push({kind: 'caption', id: 'readout-label', x: x0, y: y0, label: story.labels.climb ?? '', text: '', opacity: alpha});
  texts.push({kind: 'caption', id: 'readout-top', x: x1, y: y0, label: climb.topText ?? '', text: '', align: 'right', opacity: alpha});
  const pct = Math.round(grade) || 0;
  const gx = Math.max(x0 + 24 * scale, Math.min(x1 - 24 * scale, xAt(f)));
  texts.push({
    kind: 'caption',
    id: 'readout-grade',
    x: gx,
    y: base + 10 * scale,
    text: `${gradeFormat(locale).format(pct)}%`,
    size: 22,
    align: 'center',
    opacity: alpha,
  });
}
