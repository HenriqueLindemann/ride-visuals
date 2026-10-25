import {type DrawOp, type Knockout, mixRGB, type SlicesOp} from '../core/draw';
import {clamp01, lerp, smootherstep} from '../core/ease';
import {counterRow, frameMargins, TYPE} from '../core/layout';
import {INK, type TextItem} from '../core/Typography';
import type {ScoreContext, ScoreOutput} from './index';

/** Seconds a new road keeps the accent after its ride is drawn, before it settles into the territory. */
const COOL_S = 1.6;
/** Share of a ride lit behind its head. */
const TAIL = 0.18;
/** Seconds a piece of road takes to brighten into its next wear level. */
const WEAR_FADE_S = 0.5;
const FADE_STEPS = 4;

type Slice = SlicesOp['slices'][number];

/** Worn roads: a quiet warm hairline once, a brighter, wider paper line the more it is ridden. */
function wearStyle(u: number, scale: number) {
  return {rgb: mixRGB(INK.warmRGB, INK.paperRGB, u ** 0.8), alpha: lerp(0.55, 1, u ** 0.6), width: lerp(1.1, 2.8, u ** 1.25) * scale};
}

/** Adds a stretch to a layer, extending the last one when it continues it (one joint-free stroke). */
function push(layer: Slice[], track: Slice['track'], from: number, to: number) {
  const last = layer[layer.length - 1];
  if (last && last.track === track && Math.abs(last.to - from) < 0.5) last.to = to;
  else layer.push({track, from, to});
}

export function territoryScore({spec, tracks, frame, channel, width, height, scale, textScale}: ScoreContext<'territory'>): ScoreOutput {
  const {story} = spec;
  const ops: DrawOp[] = [];
  const texts: TextItem[] = [];
  const knockouts: Knockout[] = [];
  const portrait = height > width;
  const margins = frameMargins(portrait);
  const marginX = Math.round(margins.x * scale);
  const topY = Math.round(margins.y * scale);
  const now = frame / spec.profile.fps;

  const fade = channel('fade');
  const black = channel('black');
  const openingAlpha = channel('opening');
  const counterAlpha = channel('counter');
  const statsAlpha = channel('stats');

  // Settled territory, one layer per wear level (and per step of a level fading in).
  const top = Math.max(1, story.wearCounts.length - 1);
  const worn: Slice[][] = Array.from({length: top + 1}, () => []);
  const rising: Slice[][][] = Array.from({length: top + 1}, () => Array.from({length: FADE_STEPS}, () => []));
  const cooling: DrawOp[] = [];
  const running: DrawOp[] = [];
  let period: string | undefined;
  for (const ride of story.rides) {
    if (now < ride.t0) break;
    const track = tracks[ride.trackIndex];
    if (!track) continue;
    period = ride.period;
    const p = smootherstep((now - ride.t0) / ride.dur);
    const head = p * track.length;
    const cool = clamp01((now - ride.t0 - ride.dur) / COOL_S);
    if (cool < 1) {
      const slices = ride.fresh.filter(([a]) => a < head).map(([a, b]) => ({track, from: a, to: Math.min(b, head)}));
      if (slices.length) {
        // From the accent to the territory's first wear level.
        const k = smootherstep(cool);
        const base = wearStyle(0, scale);
        cooling.push({kind: 'slices', slices, rgb: mixRGB(INK.accentRGB, base.rgb, k), alpha: lerp(0.98, base.alpha, k) * fade, width: lerp(2.0, base.width, k)});
      }
    } else {
      ride.fresh.forEach(([a, b], i) => {
        const pieces = ride.wear[i] ?? [[]];
        const step = (b - a) / Math.max(1, pieces.length);
        pieces.forEach((times, q) => {
          let level = 0;
          while (level < times.length && times[level] <= now) level++;
          const from = a + q * step;
          const to = from + step;
          const rise = level > 0 ? clamp01((now - times[level - 1]) / WEAR_FADE_S) : 1;
          if (rise < 1) {
            push(worn[level - 1], track, from, to);
            push(rising[level][Math.min(FADE_STEPS - 1, Math.floor(rise * FADE_STEPS))], track, from, to);
          } else {
            push(worn[level], track, from, to);
          }
        });
      });
    }
    if (p < 1) {
      // The rider: a short lit stretch behind a quiet head, over known and new road alike.
      running.push({
        kind: 'track',
        track,
        from: Math.max(0, head - TAIL * track.length),
        to: head,
        rgb: INK.paperRGB,
        alpha: 0.7 * fade,
        width: 1.3 * scale,
        head: fade,
        dot: 2.4 * scale,
      });
    }
  }
  for (let j = 0; j <= top; j++) {
    const style = wearStyle(j / top, scale);
    if (worn[j].length) ops.push({kind: 'slices', slices: worn[j], rgb: style.rgb, alpha: style.alpha * fade, width: style.width});
    if (j < top) {
      const next = wearStyle((j + 1) / top, scale);
      rising[j + 1].forEach((slices, b) => {
        if (slices.length) ops.push({kind: 'slices', slices, rgb: next.rgb, alpha: next.alpha * ((b + 0.5) / FADE_STEPS) * fade, width: next.width});
      });
    }
  }
  ops.push(...cooling, ...running);

  if (openingAlpha > 0.004) {
    texts.push({
      kind: 'caption',
      id: 'territory-opening',
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

  const km = Math.max(0, channel('km'));
  const fmt = new Intl.NumberFormat(spec.locale, {maximumFractionDigits: km < 100 ? 1 : 0, minimumFractionDigits: km < 100 ? 1 : 0});
  for (const item of counterRow(story.stats, {
    id: 'territory',
    counter: story.counter,
    live: fmt.format(km),
    period,
    x0: marginX,
    x1: width - marginX,
    top: topY,
    textScale,
    counterAlpha,
    statsAlpha,
  })) {
    texts.push(item);
    if (item.kind === 'metric') knockouts.push({text: item.id, alpha: item.opacity});
  }

  return {ops, texts, black, knockouts, scrim: {top: Math.max(openingAlpha, counterAlpha)}};
}
