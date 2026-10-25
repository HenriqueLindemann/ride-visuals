import type {DrawOp, Knockout} from '../core/draw';
import {clamp01, smootherstep} from '../core/ease';
import {mercX, mercY} from '../core/geo';
import {LABEL_LINE, totalsGrid, TYPE} from '../core/layout';
import {pointAtDistance} from '../core/track';
import {INK, type TextItem} from '../core/Typography';
import type {FlyoverClimb, FlyoverStory} from '../stories';
import type {ScoreContext, ScoreOutput} from './index';

const scratch = new Float64Array(3);

export function flyoverScore({spec, tracks, channel, projector, width, height, scale, textScale}: ScoreContext<'flyover'>): ScoreOutput {
  const {story} = spec;
  const track = tracks[0];
  const ops: DrawOp[] = [];
  const texts: TextItem[] = [];
  const knockouts: Knockout[] = [];

  const portrait = height > width;
  const {marginX, topY, countersY, routeLift} = story.layout;

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

  // A featured climb's summit, marked on the land by a pulse as it is reached
  // (its figures live in the trace, not on the map).
  story.climbs.forEach((climb, k) => {
    const alpha = spec.channels[`climb${k}`] ? channel(`climb${k}`) : 0;
    if (alpha <= 0.005) return;
    ops.push({
      kind: 'pulse',
      at: [climb.lon, climb.lat],
      age: clamp01(1 - alpha * 0.85),
      radius: 32 * scale,
      rgb: INK.accentRGB,
      alpha: 0.72 * alpha,
    });
  });

  // While a climb is ridden, its trace sits centred under the counters.
  story.climbs.forEach((climb, k) => {
    const alpha = climb.trace && climb.rise && spec.channels[`trace${k}`] ? channel(`trace${k}`) : 0;
    if (alpha <= 0.004) return;
    const summit = smootherstep(clamp01(2 * channel(`summit${k}`)));
    climbTrace(climb, alpha, summit, head, story, spec.locale, scale, textScale, ops, texts, knockouts);
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
      size: TYPE.title,
      maxWidth: width - 2 * marginX,
      opacity: titleAlpha,
    });
    knockouts.push({text: 'opening-title', alpha: titleAlpha});
  }

  // Live counters during the 3D ride (top-left and top-right, over the land ahead).
  if (countersAlpha > 0.004) {
    const fmtKm = new Intl.NumberFormat(spec.locale, {minimumFractionDigits: 1, maximumFractionDigits: 1});
    const fmtInt = new Intl.NumberFormat(spec.locale, {maximumFractionDigits: 0});
    const metricSize = TYPE.number;
    const kmText = fmtKm.format(Math.max(0, kmVal));
    const ascentText = `+${fmtInt.format(Math.max(0, Math.round(ascentVal)))}`;
    knockouts.push({text: 'live-km', alpha: countersAlpha}, {text: 'live-ascent', alpha: countersAlpha});
    texts.push({
      kind: 'metric',
      id: 'live-km',
      x: marginX,
      y: countersY,
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
      y: countersY,
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
    // tagged at their summits during the ride.
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

    if (statsAlpha > 0.004) {
      const highlight = spec.channels.highlight ? channel('highlight') : 0;
      const totals = totalsGrid(story.stats, {
        x0,
        x1,
        top: baseY + 0.1 * height,
        portrait,
        textScale,
        opacity: statsAlpha,
        id: 'stat',
      });
      // The figure the highlight is about turns to the accent as the line comes in.
      totals.items.forEach((item, idx) => {
        if (story.stats[idx].accent) item.accent = highlight;
      });
      texts.push(...totals.items);
      if (story.highlight && highlight > 0.004) {
        texts.push({
          kind: 'caption',
          id: 'highlight',
          x: 0.5 * (x0 + x1),
          y: totals.bottom + 44 * textScale,
          text: story.highlight,
          size: TYPE.tag,
          align: 'center',
          maxWidth: x1 - x0,
          opacity: highlight,
        });
      }
    }
  }

  // Text along the top reads over darkened land while the map is there.
  const scrimTop = Math.max(titleAlpha, countersAlpha) * (1 - smootherstep(unfold / 0.3));
  return {ops, texts, black, knockouts, scrim: {top: scrimTop}};
}

/**
 * A climb's trace, centred under the counters: the metres it has gained over
 * the climb's whole profile, drawn only as it is ridden, with no preview of
 * the climb ahead. Every climb fills the box, so each one gets its
 * full moment: the figure tells its size, the line its shape. At the summit
 * the figure settles on the whole climb and its length and average grade
 * come in under it.
 */
function climbTrace(
  climb: FlyoverClimb,
  alpha: number,
  summit: number,
  head: number,
  story: FlyoverStory,
  locale: string,
  scale: number,
  textScale: number,
  ops: DrawOp[],
  texts: TextItem[],
  knockouts: Knockout[],
) {
  const [x0, y0, x1, y1] = story.layout.trace;
  const rise = climb.rise!;
  const n = rise.length;
  const lengthM = Math.max(1, climb.endM - climb.startM);
  const cx = 0.5 * (x0 + x1);
  // Rows: the figure, the line, then the summary on the baseline's foot.
  const lineTop = y0 + (TYPE.figure * 1.1 + 14) * textScale;
  const base = y1 - (LABEL_LINE + 12) * textScale;
  const top = Math.max(1, ...rise);
  const xAt = (i: number) => x0 + (i / (n - 1)) * (x1 - x0);
  const yAt = (m: number) => base - (m / top) * (base - lineTop);

  // Only the baseline is there from the start: the ride draws the line, with no preview of what is ahead.
  ops.push({kind: 'screen-path', xy: [x0, base, x1, base], rgb: INK.paperRGB, alpha: 0.14 * alpha, width: scale});
  const f = clamp01((head - climb.startM) / lengthM);
  const at = f * (n - 1);
  const i0 = Math.floor(at);
  const gained = rise[i0] + (rise[Math.min(n - 1, i0 + 1)] - rise[i0]) * (at - i0);
  if (f > 0) {
    const xy: number[] = [];
    for (let i = 0; i <= i0; i++) xy.push(xAt(i), yAt(rise[i]));
    xy.push(xAt(at), yAt(gained));
    ops.push({kind: 'screen-path', xy, rgb: INK.accentRGB, alpha: 0.96 * alpha, width: 2 * scale, head: alpha, smooth: true});
  }

  const figure = `+${new Intl.NumberFormat(locale, {maximumFractionDigits: 0}).format(Math.max(0, Math.round(gained)))} m`;
  texts.push({kind: 'caption', id: 'trace-gain', x: cx, y: y0, text: figure, size: TYPE.figure, align: 'center', opacity: alpha});
  knockouts.push({text: 'trace-gain', alpha});
  if (climb.summary && summit > 0.004) {
    const opacity = alpha * summit;
    texts.push({kind: 'caption', id: 'trace-summary', x: cx, y: base + 12 * textScale, label: climb.summary, text: '', align: 'center', opacity});
    knockouts.push({text: 'trace-summary', alpha: opacity});
  }
}
