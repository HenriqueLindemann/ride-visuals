import {mercX, mercY} from './geo';

/**
 * Polylines as the Python pipeline encodes them: integer deltas of
 * micro-degrees (x, y), decimetres of distance (d) and decimetres of altitude
 * (a). Delta coding keeps a 20k-vertex ride to a few hundred kilobytes of JSON.
 */
export type EncodedTrack = {
  x: number[];
  y: number[];
  d: number[];
  a?: number[] | null;
};

/** A decoded polyline with per-vertex data and precomputed simplifications. */
export interface Track {
  n: number;
  lon: Float64Array;
  lat: Float64Array;
  /** Web Mercator coordinates (0..1). */
  mx: Float64Array;
  my: Float64Array;
  /** Cumulative distance along the line, metres (strictly increasing). */
  d: Float64Array;
  /** Altitude per vertex, metres (zeros when the recording has none). */
  alt: Float64Array;
  /** Vertex subsets for coarser zooms: tolerance (m) -> indices. */
  lod: {tol: number; idx: Uint32Array}[];
  length: number;
}

function undelta(values: number[] | null | undefined, n: number, scale: number): Float64Array {
  const out = new Float64Array(n);
  if (!values) return out;
  let acc = 0;
  for (let i = 0; i < n; i++) {
    acc += values[i];
    out[i] = acc * scale;
  }
  return out;
}

/** Ramer–Douglas–Peucker on local metric coordinates; returns kept indices. */
function simplify(xs: Float64Array, ys: Float64Array, tol: number): Uint32Array {
  const n = xs.length;
  if (n < 3) return Uint32Array.from({length: n}, (_, i) => i);
  const keep = new Uint8Array(n);
  keep[0] = 1;
  keep[n - 1] = 1;
  const stack: number[] = [0, n - 1];
  while (stack.length) {
    const b = stack.pop()!;
    const a = stack.pop()!;
    if (b <= a + 1) continue;
    const sx = xs[b] - xs[a];
    const sy = ys[b] - ys[a];
    const len = Math.hypot(sx, sy);
    let best = -1;
    let bestD = 0;
    for (let i = a + 1; i < b; i++) {
      const px = xs[i] - xs[a];
      const py = ys[i] - ys[a];
      const dist = len < 1e-9 ? Math.hypot(px, py) : Math.abs(sx * py - sy * px) / len;
      if (dist > bestD) {
        bestD = dist;
        best = i;
      }
    }
    if (bestD > tol && best > 0) {
      keep[best] = 1;
      stack.push(a, best, best, b);
    }
  }
  const out: number[] = [];
  for (let i = 0; i < n; i++) if (keep[i]) out.push(i);
  return Uint32Array.from(out);
}

const LOD_TOLERANCES = [4, 12, 40, 140, 500, 2000];

export function decodeTrack(enc: EncodedTrack): Track {
  const n = enc.x.length;
  const lon = undelta(enc.x, n, 1e-6);
  const lat = undelta(enc.y, n, 1e-6);
  const d = undelta(enc.d, n, 0.1);
  const alt = undelta(enc.a, n, 0.1);
  const mx = new Float64Array(n);
  const my = new Float64Array(n);
  // Local metric frame for simplification (equirectangular around the mean latitude).
  let latSum = 0;
  for (let i = 0; i < n; i++) latSum += lat[i];
  const k = Math.cos(((latSum / Math.max(1, n)) * Math.PI) / 180);
  const xs = new Float64Array(n);
  const ys = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    mx[i] = mercX(lon[i]);
    my[i] = mercY(lat[i]);
    xs[i] = lon[i] * 111_320 * k;
    ys[i] = lat[i] * 110_540;
  }
  // Slicing by distance needs strictly increasing values.
  for (let i = 1; i < n; i++) if (d[i] <= d[i - 1]) d[i] = d[i - 1] + 0.01;
  const lod: {tol: number; idx: Uint32Array}[] = [{tol: 0, idx: Uint32Array.from({length: n}, (_, i) => i)}];
  for (const tol of LOD_TOLERANCES) lod.push({tol, idx: simplify(xs, ys, tol)});
  return {n, lon, lat, mx, my, d, alt, lod, length: n ? d[n - 1] : 0};
}

/** Index of the last vertex whose distance is <= dist (binary search). */
export function indexAtDistance(track: Track, dist: number): number {
  const d = track.d;
  if (dist <= d[0]) return 0;
  if (dist >= d[track.n - 1]) return track.n - 1;
  let lo = 0;
  let hi = track.n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (d[mid] <= dist) lo = mid;
    else hi = mid;
  }
  return lo;
}

/** Interpolated position and altitude at a distance along a track. */
export function pointAtDistance(track: Track, dist: number) {
  const i = indexAtDistance(track, dist);
  const j = Math.min(track.n - 1, i + 1);
  const spanM = track.d[j] - track.d[i];
  const f = spanM > 0 ? Math.min(1, Math.max(0, (dist - track.d[i]) / spanM)) : 0;
  const mix = (a: Float64Array) => a[i] + (a[j] - a[i]) * f;
  return {lon: mix(track.lon), lat: mix(track.lat), mx: mix(track.mx), my: mix(track.my), alt: mix(track.alt), i, f};
}

/** The coarsest simplification still finer than ~0.6 px at this ground resolution. */
export function lodFor(track: Track, metersPerPx: number): Uint32Array {
  let best = track.lod[0].idx;
  for (const level of track.lod) if (level.tol <= metersPerPx * 0.6) best = level.idx;
  return best;
}

/** Running extent of a track from its start: per vertex, the min and max lon and lat so far. */
type Extent = {lon0: Float64Array; lon1: Float64Array; lat0: Float64Array; lat1: Float64Array};
const extents = new WeakMap<Track, Extent>();

/** [west, south, east, north] of a track's first `dist` metres. */
export function extentUpTo(track: Track, dist: number): [number, number, number, number] {
  let e = extents.get(track);
  if (!e) {
    const n = track.n;
    e = {lon0: new Float64Array(n), lon1: new Float64Array(n), lat0: new Float64Array(n), lat1: new Float64Array(n)};
    for (let i = 0; i < n; i++) {
      e.lon0[i] = i ? Math.min(e.lon0[i - 1], track.lon[i]) : track.lon[i];
      e.lon1[i] = i ? Math.max(e.lon1[i - 1], track.lon[i]) : track.lon[i];
      e.lat0[i] = i ? Math.min(e.lat0[i - 1], track.lat[i]) : track.lat[i];
      e.lat1[i] = i ? Math.max(e.lat1[i - 1], track.lat[i]) : track.lat[i];
    }
    extents.set(track, e);
  }
  const i = indexAtDistance(track, dist);
  const j = Math.min(track.n - 1, i + 1);
  const span = track.d[j] - track.d[i];
  const f = span > 0 ? Math.min(1, Math.max(0, (dist - track.d[i]) / span)) : 0;
  const lon = track.lon[i] + (track.lon[j] - track.lon[i]) * f;
  const lat = track.lat[i] + (track.lat[j] - track.lat[i]) * f;
  return [Math.min(e.lon0[i], lon), Math.min(e.lat0[i], lat), Math.max(e.lon1[i], lon), Math.max(e.lat1[i], lat)];
}
