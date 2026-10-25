import {type DrawOp, type Knockout, mixRGB, ringEdges, type SlicesOp, type Tent} from '../core/draw';
import {clamp01, glide, inOutCubic, inOutSine, lerp, smootherstep, span} from '../core/ease';
import {destination, type LngLat} from '../core/geo';
import {counterRow, frameMargins, LABEL_LINE, TYPE} from '../core/layout';
import {INK, type TagItem, type TextItem} from '../core/Typography';
import type {AscentStory} from '../stories';
import type {ScoreContext, ScoreOutput} from './index';

/** Seconds a ride keeps the accent after it is drawn, before it settles into the roads. */
const COOL_S = 1.6;
/** A road left flat on the map, under the lifted ones: a quiet warm hairline. */
const ROAD = {alpha: 0.32, width: 1};
/** A settled road, lifted: a see-through paper hairline. */
const LIFTED = {alpha: 0.5, width: 1};
/** A ride being drawn: the accent. */
const LIVE = {alpha: 0.95, width: 1.8};
/** A thing beside the line, drawn on as the line nears it; gone once the line is this many times its height. */
const THING = {alpha: 0.6, width: 1, drawS: [0.8, 1.8], gone: [5, 12]};
/** A level round the line: this share of its height across, drawn round in LEVEL_S. */
const LEVEL = {alpha: 0.5, width: 1, share: 0.1};
const LEVEL_S = 1.1;
/** Seconds a name takes to come in or give way. */
const TAG_FADE_S = 0.6;

type Height = AscentStory['heights'][number];

/** How much of a height's mark is drawn (0..1). */
function drawn(h: Height, now: number): number {
  if (!h.outline.length) return glide(span(now, h.t, h.t + LEVEL_S));
  const s = Math.max(THING.drawS[0], Math.min(THING.drawS[1], h.t - h.t0));
  return inOutCubic(span(now, h.t0, h.t0 + s));
}

/** The first `share` of an outline's strokes (lengthwise, in turn), as ground points and heights facing the camera. */
function outlineUpTo(outline: Height['outline'], share: number, home: LngLat, bearing: number) {
  const len = (a: number[], b: number[]) => Math.hypot(b[0] - a[0], b[1] - a[1]);
  const total = outline.reduce((sum, st) => sum + st.slice(1).reduce((acc, pt, i) => acc + len(st[i], pt), 0), 0);
  let left = share * total;
  const strokes: {pts: LngLat[]; lifts: number[]}[] = [];
  for (const st of outline) {
    if (left <= 0) break;
    const pts: LngLat[] = [];
    const lifts: number[] = [];
    const add = (x: number, z: number) => {
      pts.push(destination(home, bearing + 90, x));
      lifts.push(z);
    };
    add(st[0][0], st[0][1]);
    for (let i = 1; i < st.length && left > 0; i++) {
      const d = len(st[i - 1], st[i]);
      const f = Math.min(1, left / Math.max(d, 1e-9));
      add(lerp(st[i - 1][0], st[i][0], f), lerp(st[i - 1][1], st[i][1], f));
      left -= d;
    }
    strokes.push({pts, lifts});
  }
  return strokes;
}

export function ascentScore({spec, tracks, frame, channel, projector, width, height, scale, textScale}: ScoreContext<'ascent'>): ScoreOutput {
  const {story} = spec;
  const ops: DrawOp[] = [];
  const texts: TextItem[] = [];
  const knockouts: Knockout[] = [];
  const margins = frameMargins(height > width);
  const marginX = Math.round(margins.x * scale);
  const topY = Math.round(margins.y * scale);
  const now = frame / spec.profile.fps;

  const fade = channel('fade');
  const openingAlpha = channel('opening');
  const counterAlpha = channel('counter');
  const statsAlpha = channel('stats');
  const ground = channel('ground');
  const climbed = Math.max(0, channel('climbed'));
  const tent: Tent = {center: story.home, height: climbed, width: channel('tent')};

  // The real map of the roads, pulled up at home by the height climbed so
  // far: every road rises toward home along one smooth bend, and the
  // closer it runs to home the higher it goes. Each ride draws in the
  // accent and settles into paper, the newest carrying the head; the flat
  // map stays under it, faint.
  const flat: SlicesOp['slices'] = [];
  const lifted: SlicesOp['slices'] = [];
  const drawing: DrawOp[] = [];
  const newest = story.rides.filter((ride) => now >= ride.t0).length - 1;
  const period = newest >= 0 ? story.rides[newest].period : undefined;
  for (const [k, ride] of story.rides.entries()) {
    if (k > newest) break;
    const track = tracks[k];
    if (!track) continue;
    const to = smootherstep((now - ride.t0) / ride.dur) * track.length;
    const cool = smootherstep(clamp01((now - ride.t0 - ride.dur) / COOL_S));
    if (!ride.away) flat.push({track, from: 0, to});
    lifted.push({track, from: 0, to, tent});
    if (cool >= 1) continue;
    drawing.push({
      kind: 'track',
      track,
      from: 0,
      to,
      tent,
      rgb: mixRGB(INK.accentRGB, INK.paperRGB, cool),
      alpha: lerp(LIVE.alpha, LIFTED.alpha, cool) * fade,
      width: lerp(LIVE.width, LIFTED.width, cool) * scale,
      head: k === newest ? 1 - cool : 0,
    });
  }
  if (flat.length) ops.push({kind: 'slices', slices: flat, rgb: INK.warmRGB, alpha: ROAD.alpha * ground * fade, width: ROAD.width * scale});
  if (lifted.length) ops.push({kind: 'slices', slices: lifted, rgb: INK.paperRGB, alpha: LIFTED.alpha * fade, width: LIFTED.width * scale});

  // Known heights: things anyone knows standing beside the line at true
  // scale, drawn on as the line nears them; levels drawn round it.
  const bearing = projector.camera.bearing;
  const marks: {h: Height; summit: [number, number] | null}[] = [];
  for (const h of story.heights) {
    const share = drawn(h, now);
    if (share <= 0) continue;
    if (h.outline.length) {
      const gone = span(Math.log(climbed / h.at), Math.log(THING.gone[0]), Math.log(THING.gone[1]));
      const alpha = THING.alpha * (1 - smootherstep(gone)) * fade;
      if (alpha <= 0.004) continue;
      for (const {pts, lifts} of outlineUpTo(h.outline, share, story.home, bearing)) ops.push({kind: 'path', pts, lifts, rgb: INK.paperRGB, alpha, width: THING.width * scale});
      const top = h.outline.flat().reduce((a, b) => (b[1] > a[1] ? b : a));
      const [x, y, ok] = projector.lngLat(...destination(story.home, bearing + 90, top[0]), top[1]);
      marks.push({h, summit: ok ? [x, y] : null});
    } else {
      ops.push({kind: 'ring', center: story.home, radius: LEVEL.share * h.at, lift: h.at, rgb: INK.paperRGB, alpha: LEVEL.alpha * fade, width: LEVEL.width * scale, sweep: share});
      marks.push({h, summit: ringEdges(projector, story.home, LEVEL.share * h.at, h.at).right});
    }
  }
  ops.push(...drawing);
  ops.push({kind: 'dot', at: story.home, radius: 3 * scale, rgb: INK.paperRGB, alpha: 0.9 * fade});
  if (climbed > 0) ops.push({kind: 'dot', at: story.home, lift: climbed, radius: 3 * scale, rgb: INK.accentRGB, alpha: (1 - statsAlpha) * fade});

  // One name at a time: a mark is named once drawn, until the next one starts.
  marks.forEach(({h, summit}) => {
    const next = story.heights[story.heights.indexOf(h) + 1];
    const from = h.outline.length ? h.t0 + 0.6 * (h.t - h.t0) : h.t;
    const alpha = inOutSine(span(now, from, from + TAG_FADE_S)) * (next ? 1 - inOutSine(span(now, next.t0, next.t0 + TAG_FADE_S)) : 1) * fade;
    if (!summit || alpha <= 0.004) return;
    const tag: TagItem = {kind: 'tag', id: `ascent-height-${h.at}`, x: summit[0], y: summit[1], leader: 28 * scale, direction: 'right', text: h.name, sub: h.value, opacity: alpha};
    texts.push(tag);
    knockouts.push({text: tag.id, alpha});
  });

  // Each year named small at the left of the line, halfway up its stretch, once climbed and tall enough to hold it.
  story.years.forEach((year, k) => {
    const from = k ? story.years[k - 1].to : 0;
    const a = ringEdges(projector, story.home, LEVEL.share * year.to, from).left;
    const b = ringEdges(projector, story.home, LEVEL.share * year.to, year.to).left;
    if (!a || !b) return;
    const alpha = inOutSine(span(now, year.t, year.t + TAG_FADE_S)) * clamp01((a[1] - b[1] - LABEL_LINE * textScale) / (LABEL_LINE * textScale)) * fade;
    if (alpha <= 0.004) return;
    const id = `ascent-year-${year.label}`;
    texts.push({kind: 'caption', id, x: 0.5 * (a[0] + b[0]) - 14 * scale, y: 0.5 * (a[1] + b[1] - LABEL_LINE * textScale), label: year.label, text: '', align: 'right', opacity: alpha});
    knockouts.push({text: id, alpha});
  });

  if (openingAlpha > 0.004) {
    texts.push({
      kind: 'caption',
      id: 'ascent-opening',
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
  const live = `+${new Intl.NumberFormat(spec.locale, {maximumFractionDigits: 0}).format(climbed)}`;
  for (const item of counterRow(story.stats, {
    id: 'ascent',
    counter: story.counter,
    live,
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

  return {ops, texts, black: channel('black'), knockouts, scrim: {top: Math.max(openingAlpha, counterAlpha)}};
}
