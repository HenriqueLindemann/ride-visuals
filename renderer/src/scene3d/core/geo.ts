/** Spherical and Web Mercator helpers (MapLibre conventions: 512 px tiles). */

export type LngLat = [number, number];

/** Mean Earth radius (authalic): for great-circle distance and bearing. */
const R = 6_371_008.8;
const RAD = Math.PI / 180;
/**
 * Web Mercator ground scale uses the equatorial (WGS84 semi-major)
 * circumference — the same constant MapLibre and the Python director use — not
 * 2*pi times the mean radius, which would drift the metres-per-pixel estimate.
 */
export const EARTH_CIRCUMFERENCE = 40_075_016.686;

export const mercX = (lon: number) => (lon + 180) / 360;

export function mercY(lat: number): number {
  const s = Math.sin(Math.max(-85.05, Math.min(85.05, lat)) * RAD);
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
}

export const unmercX = (x: number) => x * 360 - 180;
export const unmercY = (y: number) => (360 / Math.PI) * Math.atan(Math.exp((180 - y * 360) * RAD)) - 90;

/** Great-circle interpolation between two points (t in 0..1). */
export function greatCircle(a: LngLat, b: LngLat, t: number): LngLat {
  const p1 = a[1] * RAD;
  const l1 = a[0] * RAD;
  const p2 = b[1] * RAD;
  const l2 = b[0] * RAD;
  const cosD = Math.sin(p1) * Math.sin(p2) + Math.cos(p1) * Math.cos(p2) * Math.cos(l2 - l1);
  const d = Math.acos(Math.max(-1, Math.min(1, cosD)));
  if (d < 1e-9) return a;
  const A = Math.sin((1 - t) * d) / Math.sin(d);
  const B = Math.sin(t * d) / Math.sin(d);
  const x = A * Math.cos(p1) * Math.cos(l1) + B * Math.cos(p2) * Math.cos(l2);
  const y = A * Math.cos(p1) * Math.sin(l1) + B * Math.cos(p2) * Math.sin(l2);
  const z = A * Math.sin(p1) + B * Math.sin(p2);
  return [Math.atan2(y, x) / RAD, Math.atan2(z, Math.sqrt(x * x + y * y)) / RAD];
}

/** Point at `meters` along the great circle leaving `origin` with `bearing` (degrees). */
export function destination(origin: LngLat, bearing: number, meters: number): LngLat {
  const d = meters / R;
  const b = bearing * RAD;
  const p1 = origin[1] * RAD;
  const l1 = origin[0] * RAD;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [((l2 / RAD + 540) % 360) - 180, p2 / RAD];
}

/** Ground metres per CSS pixel at a zoom level and latitude. */
export const metersPerPixel = (zoom: number, lat: number) =>
  (EARTH_CIRCUMFERENCE * Math.cos(lat * RAD)) / (512 * 2 ** zoom);
