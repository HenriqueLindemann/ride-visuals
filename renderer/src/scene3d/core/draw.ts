import {destination, type LngLat, mercX, mercY} from './geo';
import type {Projector} from './projector';
import {indexAtDistance, lodFor, type Track} from './track';

export type RGB = readonly [number, number, number];

/** A slice of a recorded track, draped on the map or the 3D relief. */
export type TrackOp = {
  kind: 'track';
  track: Track;
  /** Distance window (m) to draw. */
  from: number;
  to: number;
  rgb: RGB;
  alpha: number;
  width: number;
  /** 0..1: position marker at the `to` end. */
  head?: number;
  /** Height above the map in metres (unscaled), e.g. a stacked plate. */
  lift?: number;
  /** Sit on the rendered relief and hide what the relief hides from the camera. */
  occlude?: boolean;
  /** Cut the line at this lifted polygon (e.g. the plate it lies on). */
  clip?: readonly LngLat[];
};

/** A free geographic polyline computed per frame (e.g. a ride pulled straight). */
export type PathOp = {
  kind: 'path';
  pts: LngLat[];
  rgb: RGB;
  alpha: number;
  width: number;
  /** 0..1: position marker at the last point. */
  head?: number;
};

/** A polyline already in screen pixels, optionally filled down to a baseline. */
export type ScreenPathOp = {
  kind: 'screen-path';
  xy: number[];
  rgb: RGB;
  alpha: number;
  width: number;
  /** Fill between the line and this y (px), fading downwards. */
  fillTo?: number;
  fillAlpha?: number;
  dash?: number[];
  /** 0..1: position marker at the last point. */
  head?: number;
};

/**
 * A vertical hairline at a ground point between two absolute altitudes
 * (unscaled metres): a cross-section of the land under a climb. With 3D
 * terrain it is scaled by the exaggeration, its top snaps to the rendered
 * relief, and hills in front of it hide it like any solid thing.
 */
export type StemOp = {
  kind: 'stem';
  at: LngLat;
  from: number;
  to: number;
  rgb: RGB;
  alpha: number;
  width: number;
  /** Fade from full alpha at the top to nothing at the bottom. */
  fade?: boolean;
};

export type DotOp = {kind: 'dot'; at: LngLat; lift?: number; radius: number; rgb: RGB; alpha: number; occlude?: boolean};

/** An expanding ring marking an arrival (age 0..1). */
export type PulseOp = {kind: 'pulse'; at: LngLat; age: number; radius: number; rgb: RGB; alpha: number};

/** A horizontal rectangle lifted above the map: one floor of a stack. */
export type PlateOp = {
  kind: 'plate';
  corners: [LngLat, LngLat, LngLat, LngLat];
  lift: number;
  fill: string;
  stroke: string;
  strokeWidth: number;
};

/** A circle on the ground (metres), e.g. the reach of a collection. */
export type RingOp = {kind: 'ring'; center: LngLat; radius: number; rgb: RGB; alpha: number; width: number; dash?: number[]};

export type DrawOp = TrackOp | PathOp | ScreenPathOp | StemOp | DotOp | PulseOp | PlateOp | RingOp;

const tmp = new Float64Array(3);

export const rgba = (c: RGB, a: number) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a))})`;

type Traced = {path: Path2D; head: [number, number] | null; any: boolean; pts: number[] | null};

function traceTrack(p: Projector, op: TrackOp): Traced {
  const t = op.track;
  const from = Math.max(0, op.from);
  const to = Math.min(t.length, op.to);
  const path = new Path2D();
  if (to <= from || t.n < 2) return {path, head: null, any: false, pts: null};
  const idx = lodFor(t, p.resolution);
  const i0 = indexAtDistance(t, from);
  const i1 = indexAtDistance(t, to);
  const lift = op.lift ?? 0;
  const relief = op.occlude ? p.onRelief : undefined;
  // With occlusion, keep (x, y, depth) per vertex for perspective tapering;
  // NaN marks a break where the relief hides the line.
  const pts: number[] | null = relief ? [] : null;
  let pen = false;
  let any = false;
  let lastX = 0;
  let lastY = 0;
  const emit = (mx: number, my: number) => {
    const ok = relief ? relief(mx, my, lift, tmp) === 1 : p.merc(mx, my, lift, tmp);
    if (!ok) {
      if (pen && pts) pts.push(NaN, NaN, NaN);
      pen = false;
      return;
    }
    const x = tmp[0];
    const y = tmp[1];
    if (!pen) {
      path.moveTo(x, y);
      pen = true;
    } else if (Math.abs(x - lastX) + Math.abs(y - lastY) > 0.35) {
      path.lineTo(x, y);
    } else {
      return;
    }
    pts?.push(x, y, tmp[2]);
    lastX = x;
    lastY = y;
    any = true;
  };
  const at = (i: number, dist: number): [number, number] => {
    const j = Math.min(t.n - 1, i + 1);
    const spanM = t.d[j] - t.d[i];
    const f = spanM > 0 ? Math.min(1, Math.max(0, (dist - t.d[i]) / spanM)) : 0;
    return [t.mx[i] + (t.mx[j] - t.mx[i]) * f, t.my[i] + (t.my[j] - t.my[i]) * f];
  };
  emit(...at(i0, from));
  let lo = 0;
  let hi = idx.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (idx[mid] <= i0) lo = mid + 1;
    else hi = mid;
  }
  for (let k = lo; k < idx.length && idx[k] <= i1; k++) emit(t.mx[idx[k]], t.my[idx[k]]);
  // Always land exactly on the head, even within the dedupe threshold.
  const [hx, hy] = at(i1, to);
  const ok = relief ? relief(hx, hy, lift, tmp) === 1 : p.merc(hx, hy, lift, tmp);
  const head: [number, number] | null = ok ? [tmp[0], tmp[1]] : null;
  if (head && pen) {
    path.lineTo(head[0], head[1]);
    pts?.push(head[0], head[1], tmp[2]);
  }
  return {path, head, any, pts};
}

/**
 * Strokes a traced line in short runs whose width follows perspective: full
 * width at the depth of the map centre, thicker near the eye, thinner and
 * quieter towards the horizon. Slivers peeking over a ridge are dropped.
 */
function strokeTapered(ctx: CanvasRenderingContext2D, pts: number[], width: number, refDepth: number) {
  const run = 4;
  const n = pts.length / 3;
  for (let a = 0; a < n; ) {
    if (Number.isNaN(pts[a * 3])) {
      a++;
      continue;
    }
    let b = a;
    let len = 0;
    while (b + 1 < n && !Number.isNaN(pts[(b + 1) * 3])) {
      len += Math.hypot(pts[(b + 1) * 3] - pts[b * 3], pts[(b + 1) * 3 + 1] - pts[b * 3 + 1]);
      b++;
    }
    if (len < 24) for (let i = a; i <= b; i++) pts[i * 3] = NaN;
    a = b + 1;
  }
  let k = 0;
  while (k < n - 1) {
    if (Number.isNaN(pts[k * 3])) {
      k++;
      continue;
    }
    let end = k;
    let depth = 0;
    let count = 0;
    ctx.beginPath();
    ctx.moveTo(pts[k * 3], pts[k * 3 + 1]);
    while (end < n - 1 && end - k < run && !Number.isNaN(pts[(end + 1) * 3])) {
      end++;
      ctx.lineTo(pts[end * 3], pts[end * 3 + 1]);
      depth += pts[end * 3 + 2];
      count++;
    }
    if (count > 0) {
      const near = Math.min(1.9, Math.max(0.35, refDepth / (depth / count)));
      ctx.lineWidth = width * near ** 0.9;
      ctx.globalAlpha = Math.min(1, Math.max(0.4, near ** 0.7));
      ctx.stroke();
    }
    k = end > k ? end : k + 1;
  }
  ctx.globalAlpha = 1;
}

/** Crisp position marker: an accent disc with a paper-white core, no halo. */
function drawHead(ctx: CanvasRenderingContext2D, x: number, y: number, rgb: RGB, intensity: number) {
  if (intensity <= 0.01) return;
  ctx.fillStyle = rgba(rgb, intensity);
  ctx.beginPath();
  ctx.arc(x, y, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = rgba([255, 252, 247], intensity);
  ctx.beginPath();
  ctx.arc(x, y, 2.2, 0, Math.PI * 2);
  ctx.fill();
}

let scratchCtx: CanvasRenderingContext2D | null = null;
/** An offscreen layer the size of the frame, sharing the main canvas's transform. */
function scratch(main: CanvasRenderingContext2D): CanvasRenderingContext2D {
  const {width, height} = main.canvas;
  if (!scratchCtx || scratchCtx.canvas.width !== width || scratchCtx.canvas.height !== height) {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    scratchCtx = canvas.getContext('2d')!;
  }
  scratchCtx.setTransform(main.getTransform());
  return scratchCtx;
}

function drawTrack(ctx: CanvasRenderingContext2D, p: Projector, op: TrackOp) {
  if (op.clip) {
    const area = new Path2D();
    for (const [lon, lat] of op.clip) {
      const [x, y, visible] = p.lngLat(lon, lat, op.lift);
      if (!visible) return;
      area.lineTo(x, y);
    }
    area.closePath();
    ctx.save();
    ctx.clip(area);
    drawTrack(ctx, p, {...op, clip: undefined});
    ctx.restore();
    return;
  }
  const {path, head, any, pts} = traceTrack(p, op);
  if (any && pts) {
    // Translucent runs would double up at their joints: draw them opaque into
    // a layer and composite it once at the op's alpha.
    const layer = scratch(ctx);
    layer.clearRect(0, 0, p.width, p.height);
    layer.lineCap = 'round';
    layer.lineJoin = 'round';
    layer.strokeStyle = rgba(op.rgb, 1);
    strokeTapered(layer, pts, op.width, p.centerDepth);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = Math.max(0, Math.min(1, op.alpha));
    ctx.drawImage(layer.canvas, 0, 0);
    ctx.restore();
  } else if (any) {
    ctx.strokeStyle = rgba(op.rgb, op.alpha);
    ctx.lineWidth = op.width;
    ctx.stroke(path);
  }
  if (head && op.head) drawHead(ctx, head[0], head[1], op.rgb, op.head * Math.min(1, op.alpha * 1.4));
}

function drawPath(ctx: CanvasRenderingContext2D, p: Projector, op: PathOp) {
  const path = new Path2D();
  let pen = false;
  let last: [number, number] | null = null;
  for (const [lon, lat] of op.pts) {
    const [x, y, ok] = p.lngLat(lon, lat);
    if (!ok) {
      pen = false;
      last = null;
      continue;
    }
    if (!pen) path.moveTo(x, y);
    else path.lineTo(x, y);
    pen = true;
    last = [x, y];
  }
  ctx.strokeStyle = rgba(op.rgb, op.alpha);
  ctx.lineWidth = op.width;
  ctx.stroke(path);
  if (last && op.head) drawHead(ctx, last[0], last[1], op.rgb, op.head * Math.min(1, op.alpha * 1.4));
}

function drawScreenPath(ctx: CanvasRenderingContext2D, op: ScreenPathOp) {
  const n = op.xy.length / 2;
  if (n < 2) return;
  if (op.fillTo !== undefined && (op.fillAlpha ?? 0) > 0) {
    let top = Infinity;
    for (let i = 0; i < n; i++) top = Math.min(top, op.xy[i * 2 + 1]);
    const gradient = ctx.createLinearGradient(0, top, 0, op.fillTo);
    gradient.addColorStop(0, rgba(op.rgb, op.fillAlpha ?? 0));
    gradient.addColorStop(1, rgba(op.rgb, 0));
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(op.xy[0], op.fillTo);
    for (let i = 0; i < n; i++) ctx.lineTo(op.xy[i * 2], op.xy[i * 2 + 1]);
    ctx.lineTo(op.xy[(n - 1) * 2], op.fillTo);
    ctx.closePath();
    ctx.fill();
  }
  if (op.alpha > 0.002) {
    ctx.setLineDash(op.dash ?? []);
    ctx.strokeStyle = rgba(op.rgb, op.alpha);
    ctx.lineWidth = op.width;
    ctx.beginPath();
    ctx.moveTo(op.xy[0], op.xy[1]);
    for (let i = 1; i < n; i++) ctx.lineTo(op.xy[i * 2], op.xy[i * 2 + 1]);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  if (op.head) drawHead(ctx, op.xy[(n - 1) * 2], op.xy[(n - 1) * 2 + 1], op.rgb, op.head * Math.min(1, op.alpha * 1.4));
}

/** Vertical hairline; with terrain, the parts hidden by the relief are skipped. */
function drawStem(ctx: CanvasRenderingContext2D, p: Projector, op: StemOp) {
  const mx = mercX(op.at[0]);
  const my = mercY(op.at[1]);
  const scale = p.exaggeration > 0 ? p.exaggeration : 1;
  const top = p.ground ? p.ground(mx, my) : op.to * scale;
  const bottom = op.from * scale;
  if (top - bottom < 1) return;
  const out = new Float64Array(3);
  const project = (z: number) => (p.inAir ? p.inAir(mx, my, z, out, 1e7) !== 0 : p.merc(mx, my, z, out));
  if (!project(top)) return;
  const [xTop, yTop] = [out[0], out[1]];
  if (!project(bottom)) return;
  const [xBottom, yBottom] = [out[0], out[1]];
  if (op.fade) {
    const gradient = ctx.createLinearGradient(xTop, yTop, xBottom, yBottom);
    gradient.addColorStop(0, rgba(op.rgb, op.alpha));
    gradient.addColorStop(1, rgba(op.rgb, 0));
    ctx.strokeStyle = gradient;
  } else {
    ctx.strokeStyle = rgba(op.rgb, op.alpha);
  }
  ctx.lineWidth = op.width;
  ctx.beginPath();
  // The stem is a cut into the ground: ignore the relief right around it, but
  // let ridges between it and the camera hide it.
  const cutaway = (top - bottom) / scale + 80;
  const steps = 12;
  let pen = false;
  for (let i = 0; i <= steps; i++) {
    const z = top + ((bottom - top) * i) / steps;
    const visible = p.inAir ? p.inAir(mx, my, z, out, cutaway) === 1 : p.merc(mx, my, z, out);
    if (!visible) {
      pen = false;
      continue;
    }
    if (!pen) ctx.moveTo(out[0], out[1]);
    else ctx.lineTo(out[0], out[1]);
    pen = true;
  }
  ctx.stroke();
}

function drawPlate(ctx: CanvasRenderingContext2D, p: Projector, op: PlateOp) {
  ctx.beginPath();
  let ok = true;
  op.corners.forEach(([lon, lat], i) => {
    const [x, y, visible] = p.lngLat(lon, lat, op.lift);
    ok &&= visible;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  if (!ok) return;
  ctx.closePath();
  ctx.fillStyle = op.fill;
  ctx.fill();
  ctx.strokeStyle = op.stroke;
  ctx.lineWidth = op.strokeWidth;
  ctx.stroke();
}

function drawRing(ctx: CanvasRenderingContext2D, p: Projector, op: RingOp) {
  const path = new Path2D();
  let pen = false;
  for (let i = 0; i <= 180; i++) {
    const [lon, lat] = destination(op.center, i * 2, op.radius);
    const [x, y, ok] = p.lngLat(lon, lat);
    if (!ok) {
      pen = false;
      continue;
    }
    if (!pen) path.moveTo(x, y);
    else path.lineTo(x, y);
    pen = true;
  }
  ctx.setLineDash(op.dash ?? []);
  ctx.strokeStyle = rgba(op.rgb, op.alpha);
  ctx.lineWidth = op.width;
  ctx.stroke(path);
  ctx.setLineDash([]);
}

export function drawOps(ctx: CanvasRenderingContext2D, p: Projector, ops: DrawOp[], {clear = true} = {}) {
  if (clear) ctx.clearRect(0, 0, p.width, p.height);
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  for (const op of ops) {
    const fillOnly = op.kind === 'screen-path' && (op.fillAlpha ?? 0) > 0.002;
    if (op.kind !== 'plate' && op.alpha <= 0.002 && !fillOnly) continue;
    if (op.kind === 'track') drawTrack(ctx, p, op);
    else if (op.kind === 'path') drawPath(ctx, p, op);
    else if (op.kind === 'screen-path') drawScreenPath(ctx, op);
    else if (op.kind === 'stem') drawStem(ctx, p, op);
    else if (op.kind === 'plate') drawPlate(ctx, p, op);
    else if (op.kind === 'ring') drawRing(ctx, p, op);
    else if (op.kind === 'dot') {
      const visible = op.occlude && p.onRelief
        ? p.onRelief(mercX(op.at[0]), mercY(op.at[1]), op.lift ?? 0, tmp) === 1
        : p.merc(mercX(op.at[0]), mercY(op.at[1]), op.lift ?? 0, tmp);
      if (!visible) continue;
      ctx.fillStyle = rgba(op.rgb, op.alpha);
      ctx.beginPath();
      ctx.arc(tmp[0], tmp[1], op.radius, 0, Math.PI * 2);
      ctx.fill();
    } else if (op.kind === 'pulse') {
      if (op.age <= 0 || op.age >= 1) continue;
      // Ring around the summit on the relief, not at sea level under it.
      const mx = mercX(op.at[0]);
      const my = mercY(op.at[1]);
      const visible = p.onRelief ? p.onRelief(mx, my, 0, tmp) === 1 : p.merc(mx, my, 0, tmp);
      if (!visible) continue;
      const x = tmp[0];
      const y = tmp[1];
      const grown = 1 - (1 - op.age) ** 3;
      ctx.strokeStyle = rgba(op.rgb, op.alpha * (1 - op.age) ** 1.5);
      ctx.lineWidth = 1.5 * (1 - op.age * 0.6);
      ctx.beginPath();
      ctx.arc(x, y, 3 + grown * op.radius, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
  ctx.restore();
}

/** A screen box (px) under fixed text where drawn lines fade out. */
export type Knockout = {box: [number, number, number, number]; alpha: number};

/**
 * Erases whatever the ops drew under fixed text, with a soft edge: corner
 * counters and titles stay legible wherever the route happens to run.
 */
export function drawKnockouts(ctx: CanvasRenderingContext2D, knockouts: Knockout[], feather: number) {
  if (knockouts.length === 0) return;
  ctx.save();
  ctx.globalCompositeOperation = 'destination-out';
  ctx.filter = `blur(${Math.max(1, feather / 2)}px)`;
  for (const {box, alpha} of knockouts) {
    if (alpha <= 0.003) continue;
    ctx.fillStyle = `rgba(0,0,0,${Math.min(1, alpha)})`;
    const [x0, y0, x1, y1] = box;
    ctx.fillRect(x0 - feather / 2, y0 - feather / 2, x1 - x0 + feather, y1 - y0 + feather);
  }
  ctx.restore();
}
