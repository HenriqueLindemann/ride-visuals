import {type DrawOp, type Knockout, type Plane, planePoint, type SlicesOp} from '../core/draw';
import {clamp01, glide, inOutSine, lerp, smootherstep, span} from '../core/ease';
import {counterRow, frameMargins, LABEL_LINE, metricHeight, spread, TYPE} from '../core/layout';
import {INK, type TagItem, type TextItem} from '../core/Typography';
import type {AscentStory} from '../stories';
import type {ScoreContext, ScoreOutput} from './index';

/** The profile: a paper hairline; the newest climbing carries the accent. */
const PROFILE = {alpha: 0.8, width: 1.3};
const LIVE = {alpha: 0.95, width: 2};
/** Rides on the map, flat: a quiet warm hairline. */
const ROAD = {alpha: 0.3, width: 1};
/**
 * A thing beside the line: a hairline outline that comes in whole, filled up to the height climbed so far;
 * gone once the line is `gone` times its height. A skyline is lit up to that height instead, over a faint
 * shade, and fades out toward its ends: a range has no edge.
 */
const THING = {alpha: 0.75, width: 1, fill: 0.08, shade: 0.1, inS: 0.9, gone: [5, 12], taper: 0.2};
/** A level, drawn from where the line crosses it out to its far end; it gives way once the next is drawn. */
const LEVEL = {alpha: 0.4, width: 1, drawS: 1.2, outS: 1.2};
/** A period's divider, from the ground up to the profile; folded, a tick of this many px right of the line (minor: a share). */
const DIVIDER = {alpha: 0.3, width: 1, tick: 6, minor: 0.5};
/** Folded, a tick left of the line at each multiple of the measure's height, drawn up one after another. */
const RULER = {alpha: 0.6, tick: 8};
/**
 * A level's glyph (something everyone knows at that height, too small for true scale): a quiet
 * silhouette leading the line out, nose first, and resting at its end; every glyph at one px per metre.
 */
const GLYPH = {fill: 0.7, pxPerM: 0.75};
/** Seconds a name takes to come in or give way, and stays before it does (folded, the last ones come back). */
const TAG_FADE_S = 0.6;
const NAME_HOLD_S = 4;

type Height = AscentStory['heights'][number];
type Span = AscentStory['periods'][number];
type Profile = {x: Float64Array; z: Float64Array};

const profiles = new WeakMap<AscentStory, Profile>();

/** The chained profile, decoded once per spec. */
function profileOf(story: AscentStory): Profile {
  let profile = profiles.get(story);
  if (!profile) {
    const undelta = (values: number[]) => {
      const out = new Float64Array(values.length);
      let acc = 0;
      values.forEach((v, i) => {
        acc += v;
        out[i] = acc / 10;
      });
      return out;
    };
    profile = {x: undelta(story.profile.x), z: undelta(story.profile.z)};
    profiles.set(story, profile);
  }
  return profile;
}

/** Index of the last vertex at or before plane x. */
function indexAt(xs: Float64Array, x: number): number {
  let lo = 0;
  let hi = xs.length - 1;
  if (x >= xs[hi]) return hi;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= x) lo = mid;
    else hi = mid;
  }
  return lo;
}

/** Height of the profile at plane x. */
function heightAt({x: xs, z: zs}: Profile, x: number): number {
  const i = indexAt(xs, x);
  const j = Math.min(xs.length - 1, i + 1);
  return xs[j] > xs[i] ? lerp(zs[i], zs[j], clamp01((x - xs[i]) / (xs[j] - xs[i]))) : zs[i];
}

/** Plane x where the profile first reaches height z. */
function xAtHeight({x: xs, z: zs}: Profile, z: number): number {
  let lo = 0;
  let hi = zs.length - 1;
  if (z >= zs[hi]) return xs[hi];
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (zs[mid] < z) lo = mid;
    else hi = mid;
  }
  return zs[hi] > zs[lo] ? lerp(xs[lo], xs[hi], clamp01((z - zs[lo]) / (zs[hi] - zs[lo]))) : xs[lo];
}

/** The profile from plane x `from` to `to`, squashed toward home: flat x, z pairs. */
function stretch(profile: Profile, from: number, to: number, squash: number): number[] {
  if (to <= from) return [];
  const out = [from * squash, heightAt(profile, from)];
  const last = indexAt(profile.x, to);
  for (let i = indexAt(profile.x, from) + 1; i <= last; i++) out.push(profile.x[i] * squash, profile.z[i]);
  out.push(to * squash, heightAt(profile, to));
  return out;
}

/** How much of a height's mark is in (0..1): a thing fades in whole, a level is drawn out. */
function drawn(h: Height, now: number): number {
  if (h.shape === 'level') return glide(span(now, h.t, h.t + LEVEL.drawS));
  return inOutSine(span(now, h.t0, h.t0 + THING.inS));
}

export function ascentScore({spec, tracks, frame, channel, projector, width, height, scale, textScale}: ScoreContext<'ascent'>): ScoreOutput {
  const {story} = spec;
  const profile = profileOf(story);
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
  const climbed = Math.max(0, channel('climbed'));
  const head = channel('head');
  const tail = channel('tail');
  const live = channel('live');
  const fold = channel('fold');
  const squash = 1 - fold;
  const plane: Plane = {origin: story.home, bearing: story.axis};
  const at = (x: number, z: number) => planePoint(projector, plane, x, z);
  const total = profile.z[profile.z.length - 1];
  const hairline = (strokes: number[][], alpha: number) =>
    ops.push({kind: 'plane', plane, strokes, rgb: INK.paperRGB, alpha: alpha * fade, width: DIVIDER.width * scale});
  // A name beside its mark wraps rather than run past the side margin.
  const sideRoom = (direction: TagItem['direction'], x: number, leader: number) =>
    direction === 'left' ? x - leader - 10 * scale - marginX : direction === 'right' ? width - marginX - x - leader - 10 * scale : undefined;

  // From high enough the Earth curves away: its limb sinks below eye
  // level and space opens above it.
  const eyeZ = projector.eye?.z ?? 0;
  const sky = smootherstep(span(eyeZ, 1_500, 12_000));
  if (sky > 0.004) ops.push({kind: 'horizon', alpha: sky, limb: 0.2 * sky * fade, air: smootherstep(span(eyeZ, 8_000, 60_000)) * fade});

  // The rides on the map, drawn flat as their climbing joins the profile.
  const roads: SlicesOp['slices'] = [];
  story.rides.forEach((ride, k) => {
    if (ride.track === undefined || ride.x0 >= head) return;
    const track = tracks[ride.track];
    roads.push({track, from: 0, to: Math.min(track.length, (head - ride.x0) / story.scale)});
  });
  if (roads.length) ops.push({kind: 'slices', slices: roads, rgb: INK.warmRGB, alpha: ROAD.alpha * fade, width: ROAD.width * scale});

  if (head > 0) {
    // The profile: every ride's climbing chained, the newest in the accent.
    ops.push({kind: 'plane', plane, strokes: [stretch(profile, 0, head, squash)], rgb: INK.paperRGB, alpha: PROFILE.alpha * fade, width: PROFILE.width * scale});
    if (live > 0.004 && head > tail) {
      ops.push({kind: 'plane', plane, strokes: [stretch(profile, tail, head, squash)], rgb: INK.accentRGB, alpha: LIVE.alpha * fade, width: LIVE.width * scale, head: live});
    }
  }

  // How it grew: each year (or month) divided off along the base and named
  // under its stretch, with its climbing once done. Months over several
  // years divide the base more finely, and their years are named. Folded,
  // the dividers become ticks on the line, the names beside it, riding the
  // line in as it straightens.
  const lineLabels = smootherstep(span(fold, 0.45, 0.95));
  const baseLabels = 1 - smootherstep(span(fold, 0.05, 0.55));
  // Metres per pixel along the folded line, for things drawn a set size on screen.
  const mPerPx = total / Math.max(1, Math.abs(at(0, 0)[1] - at(0, total)[1]));
  const divide = (spans: Span[], id: string, minor: boolean) => {
    let lastTickY = Infinity;
    spans.forEach((period, k) => {
      const [x0] = period.x;
      const [z0] = period.z;
      if (head <= x0) return;
      const enter = k ? inOutSine(span(now, spans[k - 1].t, spans[k - 1].t + TAG_FADE_S)) : counterAlpha;
      const weight = minor ? DIVIDER.minor : 1;
      // Months within years divide only the folded line: along the base they would be a comb.
      if (k && !minor && baseLabels > 0.004) hairline([[x0 * squash, 0, x0 * squash, z0]], DIVIDER.alpha * enter * baseLabels);
      if (k && lineLabels > 0.004) {
        const x = x0 * squash;
        const [, ty] = at(x, z0);
        if (Math.abs(ty - lastTickY) >= 1.5 * scale) {
          lastTickY = ty;
          hairline([[x, z0, x + DIVIDER.tick * weight * scale * mPerPx, z0]], 2 * DIVIDER.alpha * weight * lineLabels);
        }
      }
    });
    if (minor) return;
    if (baseLabels > 0.004) {
      const compactBase = spans.length > 5;
      const baseSize = compactBase ? (height > width ? 15 : 17) : TYPE.tag;
      const minDx = compactBase ? 2.45 * baseSize * textScale : 82 * textScale;
      const loX = marginX + 0.45 * minDx;
      const hiX = width - marginX - 0.45 * minDx;
      const baseItems: {k: number; period: Span; ax: number; ay: number; enter: number; done: number; alpha: number}[] = [];
      spans.forEach((period, k) => {
        const [x0, x1] = period.x;
        if (head <= x0) return;
        const enter = k ? inOutSine(span(now, spans[k - 1].t, spans[k - 1].t + TAG_FADE_S)) : counterAlpha;
        const done = inOutSine(span(now, period.t, period.t + TAG_FADE_S));
        const alpha = enter * baseLabels * fade;
        if (alpha <= 0.004) return;
        const [ax, ay, okA] = at(x0 * squash, 0);
        const [bx, by, okB] = at(Math.min(x1, head) * squash, 0);
        if (!okA || !okB) return;
        baseItems.push({k, period, ax: 0.5 * (ax + bx), ay: 0.5 * (ay + by), enter, done, alpha});
      });
      const rawAnchors = baseItems.map((it) => it.ax);
      let labelXs = baseItems.length ? spread([rawAnchors[0]], minDx, loX, hiX) : [];
      for (let i = 1; i < baseItems.length; i++) {
        const prev = [...labelXs, Math.min(hiX, Math.max(rawAnchors[i], labelXs[i - 1] + minDx))];
        const next = spread(rawAnchors.slice(0, i + 1), minDx, loX, hiX);
        const w = baseItems[i].enter;
        labelXs = next.map((nx, j) => lerp(prev[j], nx, w));
      }
      baseItems.forEach((it, i) => {
        const lx = labelXs[i];
        const leader = 12 * scale;
        const lead = leader * it.alpha;
        if (lead > 0.5) {
          ops.push({
            kind: 'screen-path',
            xy: [it.ax, it.ay, it.ax, it.ay + 0.25 * lead, lx, it.ay + 0.75 * lead, lx, it.ay + lead],
            rgb: INK.paperRGB,
            alpha: 0.22 * it.alpha,
            width: scale,
          });
        }
        const tag: TagItem = {
          kind: 'tag',
          id: `${id}-${it.k}`,
          x: lx,
          y: it.ay,
          leader,
          customLeader: true,
          direction: 'down',
          text: it.period.label,
          sub: compactBase ? undefined : it.period.value,
          size: baseSize,
          subOpacity: it.done,
          opacity: it.alpha,
        };
        texts.push(tag);
        knockouts.push({text: tag.id, alpha: it.alpha});
      });
    }
    if (lineLabels > 0.004) {
      const [, yBase] = at(0, 0);
      const [, yTop] = at(0, total);
      const safeTop = topY + (metricHeight(TYPE.number) + 32) * textScale;
      const safeBottom = height - topY - 32 * textScale;
      let minY = Math.max(safeTop, Math.min(yTop, yBase) - 8 * textScale);
      let maxY = Math.min(safeBottom, Math.max(yTop, yBase) + 8 * textScale);
      const lineItems: {k: number; period: Span; lx: number; ly: number}[] = [];
      spans.forEach((period, k) => {
        const [z0, z1] = period.z;
        if (head <= period.x[0]) return;
        const zMid = 0.5 * (z0 + z1);
        const [lx, ly, ok] = at(xAtHeight(profile, zMid) * squash, zMid);
        if (ok) lineItems.push({k, period, lx, ly});
      });
      const a = lineLabels * fade;
      if (lineItems.length && a > 0.004) {
        const n = lineItems.length;
        const availPerGap = (maxY - minY) / Math.max(1, n - 1) / textScale;
        const lineTagSize = Math.max(15, Math.min(TYPE.tag, (availPerGap - LABEL_LINE - 4) / (1.15 + 4 / TYPE.tag)));
        const minGap = (1.15 * lineTagSize + 4 * (lineTagSize / TYPE.tag) + LABEL_LINE + 4) * textScale;
        const spanNeeded = (n - 1) * minGap;
        const extra = Math.max(0, spanNeeded - (maxY - minY));
        minY = Math.max(safeTop, minY - 0.5 * extra);
        maxY = Math.min(safeBottom, Math.max(maxY + 0.5 * extra, minY + spanNeeded));
        minY = Math.max(safeTop, Math.min(minY, maxY - spanNeeded));
        const topDown = [...lineItems].reverse();
        const labelYs = spread(
          topDown.map((it) => it.ly),
          minGap,
          minY,
          maxY,
        );
        topDown.forEach((it, i) => {
          const labelY = labelYs[i];
          const [x, leader] = [it.lx + 8 * scale, 18 * scale];
          const lead = leader * a;
          if (lead > 0.5) {
            ops.push({
              kind: 'screen-path',
              xy: [x, it.ly, x + 0.55 * lead, labelY, x + lead, labelY],
              rgb: INK.paperRGB,
              alpha: 0.22 * a,
              width: scale,
            });
          }
          const tag: TagItem = {
            kind: 'tag',
            id: `${id}-line-${it.k}`,
            x,
            y: labelY,
            leader,
            customLeader: true,
            direction: 'right',
            text: it.period.label,
            sub: it.period.value,
            size: lineTagSize,
            maxWidth: sideRoom('right', x, leader),
            opacity: a,
          };
          texts.push(tag);
          knockouts.push({text: tag.id, alpha: a});
        });
      }
    }
  };
  const grouped = story.groups.length > 0 && story.periods.length > 14;
  divide(story.periods, 'ascent-period', grouped);
  if (grouped) divide(story.groups, 'ascent-group', false);

  // Folded, the line is ruled in the last thing's height, left of it as
  // the years are right: a tick each time it was climbed, drawn out one
  // after another from the ground up.
  const ruler = channel('ruler');
  if (story.ruler && ruler > 0) {
    const {at: unit, count} = story.ruler;
    const reach = smootherstep(ruler) * (count + 0.6);
    for (let k = 1; k <= count; k++) {
      const grown = smootherstep(reach - k + 0.6);
      if (grown > 0.004) hairline([[0, k * unit, -grown * RULER.tick * scale * mPerPx, k * unit]], RULER.alpha * grown * lineLabels);
    }
  }

  // Things anyone knows, standing left of home at true scale: each comes
  // in as the line nears it and fills up to the height climbed so far;
  // levels are drawn out from where the line crosses them, one at a time.
  const lastThing = story.heights.reduce((last, h, i) => (h.shape === 'level' ? last : i), -1);
  const lastLevel = story.heights.reduce((last, h, i) => (h.shape === 'level' ? i : last), -1);
  const levels = story.heights.filter((h) => h.shape === 'level');
  const marks: {h: Height; anchor: [number, number]; side: [number, number]; standing: number}[] = [];
  story.heights.forEach((h, i) => {
    const share = drawn(h, now);
    if (share <= 0) return;
    if (h.shape === 'level') {
      const next = levels[levels.indexOf(h) + 1];
      const standing = next ? 1 - smootherstep(span(now, next.t + LEVEL.drawS, next.t + LEVEL.drawS + LEVEL.outS)) : 1;
      if (standing <= 0.004) return;
      const [[far, z], [cross]] = h.strokes[0];
      const right = cross * squash;
      const left = lerp(right, far, share);
      ops.push({kind: 'plane', plane, strokes: [[right, z, left, z]], rgb: INK.paperRGB, alpha: LEVEL.alpha * standing * fade, width: LEVEL.width * scale});
      let nose = left;
      if (h.glyph) {
        const m = GLYPH.pxPerM * scale * mPerPx;
        nose = left - m * Math.max(...h.glyph.flat().map(([x]) => x));
        const strokes = h.glyph.map((st) => st.flatMap(([x, y]) => [nose + x * m, z + y * m]));
        ops.push({kind: 'plane', plane, strokes, rgb: INK.paperRGB, alpha: 0, width: 0, fill: GLYPH.fill * Math.min(1, 3 * share) * standing * fade});
      }
      const [x, y, ok] = at(nose, z);
      if (ok) marks.push({h, anchor: [x, y], side: [x, y], standing});
      return;
    }
    // The last thing passed stays as the measure; the others give way once outgrown.
    const gone = i === lastThing ? 0 : span(Math.log(climbed / h.at), Math.log(THING.gone[0]), Math.log(THING.gone[1]));
    const standing = 1 - smootherstep(gone);
    if (standing <= 0.004) return;
    const alpha = share * standing * fade;
    const strokes = h.strokes.map((st) => st.flat());
    if (h.shape === 'outline') {
      ops.push({kind: 'plane', plane, strokes, rgb: INK.paperRGB, alpha: THING.alpha * alpha, width: THING.width * scale, fill: THING.fill * alpha, upTo: climbed});
    } else {
      ops.push({kind: 'plane', plane, strokes, rgb: INK.paperRGB, alpha: THING.alpha * alpha, width: THING.width * scale, shade: THING.shade * alpha, lit: climbed, taper: [THING.taper, THING.taper]});
    }
    // Named above its top; folded, from its left end, where a skyline is fully drawn.
    const pts = h.strokes.flat();
    const top = pts.reduce((a, b) => (b[1] > a[1] ? b : a));
    const x0 = Math.min(...pts.map(([x]) => x));
    const x1 = Math.max(...pts.map(([x]) => x));
    const end = h.shape === 'skyline' ? pts.find(([x]) => x >= x0 + THING.taper * (x1 - x0))! : top;
    const [x, y, ok] = at(top[0], top[1]);
    const [sx, sy] = at(end[0], end[1]);
    if (ok) marks.push({h, anchor: [x, y], side: [sx, sy], standing});
  });
  ops.push({kind: 'dot', at: story.home, radius: 3 * scale, rgb: INK.paperRGB, alpha: 0.9 * fade * (1 - live)});

  // One name at a time while the line climbs (when, the director decides),
  // for a while or until the next one. Folded, the last thing and level
  // passed are named again, to the left, clear of the line and its ruler.
  // Folded, the level comes back only with room to read it clear of the thing.
  const sideOf = (i: number) => marks.find((m) => m.h === story.heights[i])?.side;
  const [thingSide, levelSide] = [sideOf(lastThing), sideOf(lastLevel)];
  const levelBack = !thingSide || !levelSide ? 1 : clamp01((Math.abs(thingSide[1] - levelSide[1]) - 2.6 * LABEL_LINE * textScale) / (0.6 * LABEL_LINE * textScale));
  for (const {h, anchor, side, standing} of marks) {
    const i = story.heights.indexOf(h);
    const next = story.heights[i + 1];
    const until = Math.min(next ? next.named : Infinity, h.named + 2 * TAG_FADE_S + NAME_HOLD_S);
    const climbing = inOutSine(span(now, h.named, h.named + TAG_FADE_S)) * (1 - inOutSine(span(now, until - TAG_FADE_S, until)));
    const folded = i === lastThing ? lineLabels : i === lastLevel ? lineLabels * levelBack : 0;
    const named: [TagItem['direction'], number, string][] =
      h.shape === 'skyline'
        ? [['up', climbing * (1 - folded), ''], ['left', folded, '-folded']]
        : [['left', Math.max(climbing, folded), '']];
    for (const [direction, a, suffix] of named) {
      const alpha = a * standing * fade;
      if (alpha <= 0.004) continue;
      const leader = (direction === 'up' ? 20 : 28) * scale;
      const [x, y] = suffix ? side : anchor;
      const tag: TagItem = {kind: 'tag', id: `ascent-height-${h.at}${suffix}`, x, y, leader, direction, text: h.name, sub: h.value, maxWidth: sideRoom(direction, x, leader), opacity: alpha};
      texts.push(tag);
      knockouts.push({text: tag.id, alpha});
    }
  }

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
  // The ride the head is on (the first one until the profile sets off).
  const ride = story.rides[Math.max(0, story.rides.filter((r) => r.x0 < head).length - 1)];
  const value = `+${new Intl.NumberFormat(spec.locale, {maximumFractionDigits: 0}).format(climbed)}`;
  for (const item of counterRow(story.stats, {
    id: 'ascent',
    counter: story.counter,
    live: value,
    period: ride.period,
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

  return {ops, texts, black: channel('black'), knockouts, scrim: {top: Math.max(openingAlpha, counterAlpha), far: projector.camera.buildings * fade}};
}
