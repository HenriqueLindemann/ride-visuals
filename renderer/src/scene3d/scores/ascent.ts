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
/** A level: a hairline drawn out from where the line crosses it to its name, and gone with the name. */
const LEVEL = {alpha: 0.4, width: 1, drawS: 1.2};
/**
 * A period done: a post rising from the ground to the profile where it ends (over `riseS`), running on
 * `leader` px below the ground to its name, which follows `nameLagS` later; the ground under the profile
 * is a fainter hairline. Folded, a tick of this many px right of the line (minor: a share).
 */
const POST = {alpha: 0.3, ground: 0.16, width: 1, riseS: 0.7, nameLagS: 0.15, leader: 12, tick: 6, minor: 0.5};
/** Folded, a tick left of the line at each multiple of the measure's height, drawn up one after another. */
const RULER = {alpha: 0.6, tick: 8};
/**
 * A level's glyph (something everyone knows at that height, too small for true scale): seen from above,
 * nose toward its name, `gap` px clear of the level's end; every glyph at one scale, so their sizes compare.
 */
const GLYPH = {fill: 0.85, pxPerM: 1.2, gap: 8};
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

/** How much of a height's mark is in (0..1): a thing fades in whole; a level is drawn out to its name as it comes in. */
function drawn(h: Height, now: number): number {
  if (h.shape === 'level') {
    const start = Math.max(h.t, h.named - TAG_FADE_S);
    return glide(span(now, start, start + LEVEL.drawS));
  }
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
    ops.push({kind: 'plane', plane, strokes, rgb: INK.paperRGB, alpha: alpha * fade, width: POST.width * scale});
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

  // How it grew: each year (or month), once done, marked where it ends by a
  // post rising from the ground to the profile, named under its foot with its
  // climbing; the post runs on as the name's leader, one line in one move.
  // Months over several years divide only the folded line, and their years
  // are named. Folded, the posts become ticks on the line, the names beside
  // them, riding the line in as it straightens.
  const lineLabels = smootherstep(span(fold, 0.45, 0.95));
  const baseLabels = 1 - smootherstep(span(fold, 0.05, 0.55));
  // Metres per pixel along the folded line, for things drawn a set size on screen.
  const mPerPx = total / Math.max(1, Math.abs(at(0, 0)[1] - at(0, total)[1]));
  const risen = (period: Span) => glide(span(now, period.t, period.t + POST.riseS));
  if (story.periods.length && baseLabels > 0.004 && head > 0) {
    hairline([[0, 0, head * squash, 0]], POST.ground * counterAlpha * baseLabels);
  }
  const divide = (spans: Span[], id: string, minor: boolean) => {
    const done = spans.map((period, k) => ({period, k, rise: risen(period)})).filter(({rise}) => rise > 0);
    const weight = minor ? POST.minor : 1;
    let lastTickY = Infinity;
    for (const {period, rise} of done) {
      const x = period.x[1] * squash;
      const z = period.z[1];
      if (!minor && baseLabels > 0.004) hairline([[x, 0, x, z * rise]], POST.alpha * baseLabels);
      if (lineLabels > 0.004) {
        const [, ty] = at(x, z);
        if (Math.abs(ty - lastTickY) >= 1.5 * scale) {
          lastTickY = ty;
          hairline([[x, z, x + POST.tick * weight * scale * mPerPx, z]], 2 * POST.alpha * weight * lineLabels);
        }
      }
    }
    if (minor) return;
    if (baseLabels > 0.004) {
      const compactBase = spans.length > 5;
      const baseSize = compactBase ? (height > width ? 15 : 17) : TYPE.tag;
      const minDx = compactBase ? 2.45 * baseSize * textScale : 82 * textScale;
      const loX = marginX + 0.45 * minDx;
      const hiX = width - marginX - 0.45 * minDx;
      const feet: {k: number; period: Span; ax: number; ay: number; rise: number}[] = [];
      for (const {period, k, rise} of done) {
        const [ax, ay, ok] = at(period.x[1] * squash, 0);
        if (ok) feet.push({k, period, ax, ay, rise});
      }
      // Names keep clear of each other, and make room for a new one as it comes in.
      const anchors = feet.map((it) => it.ax);
      let labelXs = feet.length ? spread([anchors[0]], minDx, loX, hiX) : [];
      for (let i = 1; i < feet.length; i++) {
        const prev = [...labelXs, Math.min(hiX, Math.max(anchors[i], labelXs[i - 1] + minDx))];
        const next = spread(anchors.slice(0, i + 1), minDx, loX, hiX);
        labelXs = next.map((nx, j) => lerp(prev[j], nx, feet[i].rise));
      }
      feet.forEach((it, i) => {
        const alpha = inOutSine(span(now, it.period.t + POST.nameLagS, it.period.t + POST.nameLagS + TAG_FADE_S)) * baseLabels * fade;
        const lx = labelXs[i];
        const leader = POST.leader * scale;
        const lead = leader * it.rise;
        if (lead > 0.5) {
          ops.push({
            kind: 'screen-path',
            xy: [it.ax, it.ay, it.ax, it.ay + 0.25 * lead, lx, it.ay + 0.75 * lead, lx, it.ay + lead],
            rgb: INK.paperRGB,
            alpha: POST.alpha * baseLabels * fade,
            width: POST.width * scale,
          });
        }
        if (alpha <= 0.004) return;
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
          opacity: alpha,
        };
        texts.push(tag);
        knockouts.push({text: tag.id, alpha});
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
      for (const {period, k} of done) {
        const [lx, ly, ok] = at(period.x[1] * squash, period.z[1]);
        if (ok) lineItems.push({k, period, lx, ly});
      }
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
  // in as the line nears it and fills up to the height climbed so far.
  // Levels are drawn out from where the line crosses them to their name,
  // and go with it: a level means nothing once its name has gone.
  const lastThing = story.heights.reduce((last, h, i) => (h.shape === 'level' ? last : i), -1);
  const lastLevel = story.heights.reduce((last, h, i) => (h.shape === 'level' ? i : last), -1);
  const glyphM = GLYPH.pxPerM * scale * mPerPx;
  // Where each is named: a thing above its top, and folded from its left end (where a skyline is fully
  // drawn); a level at its far end, past its glyph.
  const namedAt = story.heights.map((h) => {
    if (h.shape === 'level') {
      const [[far, z]] = h.strokes[0];
      const length = h.glyph ? Math.max(...h.glyph.flat().map(([x]) => x)) : 0;
      const nose = h.glyph ? far - GLYPH.gap * scale * mPerPx - length * glyphM : far;
      return {top: [nose, z], side: [nose, z]};
    }
    const pts = h.strokes.flat();
    const top = pts.reduce((a, b) => (b[1] > a[1] ? b : a));
    const x0 = Math.min(...pts.map(([x]) => x));
    const x1 = Math.max(...pts.map(([x]) => x));
    return {top, side: h.shape === 'skyline' ? pts.find(([x]) => x >= x0 + THING.taper * (x1 - x0))! : top};
  });

  // One name at a time while the line climbs (when, the director decides),
  // for a while or until the next one; the last stays on. Folded, the last
  // thing and level passed are named, to the left, clear of the line and its
  // ruler; the level only with room to read it clear of the thing.
  const sideY = (i: number) => (i < 0 ? undefined : at(namedAt[i].side[0], namedAt[i].side[1])[1]);
  const [thingY, levelY] = [sideY(lastThing), sideY(lastLevel)];
  const levelBack = thingY === undefined || levelY === undefined ? 1 : clamp01((Math.abs(thingY - levelY) - 2.6 * LABEL_LINE * textScale) / (0.6 * LABEL_LINE * textScale));
  const foldedBack = (i: number) => (i === lastThing ? 1 : i === lastLevel ? levelBack : 0);
  const gives = (i: number) => {
    const h = story.heights[i];
    const next = story.heights[i + 1];
    if (!next) return 0;
    const until = Math.min(next.named, h.named + 2 * TAG_FADE_S + NAME_HOLD_S);
    return inOutSine(span(now, until - TAG_FADE_S, until));
  };
  const climbing = (i: number) => inOutSine(span(now, story.heights[i].named, story.heights[i].named + TAG_FADE_S)) * (1 - gives(i));

  const marks: {i: number; standing: number}[] = [];
  story.heights.forEach((h, i) => {
    const share = drawn(h, now);
    if (share <= 0) return;
    if (h.shape === 'level') {
      const life = lerp(1 - gives(i), foldedBack(i), lineLabels);
      if (life <= 0.004) return;
      const [[far, z], [cross]] = h.strokes[0];
      const right = cross * squash;
      ops.push({kind: 'plane', plane, strokes: [[right, z, lerp(right, far, share), z]], rgb: INK.paperRGB, alpha: LEVEL.alpha * life * fade, width: LEVEL.width * scale});
      if (h.glyph) {
        const nose = namedAt[i].top[0];
        const strokes = h.glyph.map((st) => st.flatMap(([x, y]) => [nose + x * glyphM, z + y * glyphM]));
        const shown = lerp(climbing(i), foldedBack(i), lineLabels);
        ops.push({kind: 'plane', plane, strokes, rgb: INK.paperRGB, alpha: 0, width: 0, fill: GLYPH.fill * shown * fade});
      }
      marks.push({i, standing: 1});
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
    marks.push({i, standing});
  });
  ops.push({kind: 'dot', at: story.home, radius: 3 * scale, rgb: INK.paperRGB, alpha: 0.9 * fade * (1 - live)});

  for (const {i, standing} of marks) {
    const h = story.heights[i];
    const folded = lineLabels * foldedBack(i);
    const named: [TagItem['direction'], number, string][] =
      h.shape === 'skyline'
        ? [['up', climbing(i) * (1 - folded), ''], ['left', folded, '-folded']]
        : [['left', lerp(climbing(i), foldedBack(i), lineLabels), '']];
    for (const [direction, a, suffix] of named) {
      const alpha = a * standing * fade;
      if (alpha <= 0.004) continue;
      // A level's line, and its glyph, lead to its name already.
      const leader = h.shape === 'level' ? 0 : (direction === 'up' ? 20 : 28) * scale;
      const [x, y, ok] = at(...((suffix ? namedAt[i].side : namedAt[i].top) as [number, number]));
      if (!ok) continue;
      const tag: TagItem = {
        kind: 'tag',
        id: `ascent-height-${h.at}${suffix}`,
        x,
        y,
        leader,
        customLeader: h.shape === 'level',
        direction,
        text: h.name,
        sub: h.value,
        maxWidth: sideRoom(direction, x, leader),
        opacity: alpha,
      };
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
