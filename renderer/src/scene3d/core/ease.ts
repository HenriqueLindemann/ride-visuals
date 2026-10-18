/** Easing curves and scalar helpers shared by every 3D scene. */

export type Ease = (t: number) => number;

export const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** Linear progress of `v` between `from` and `to`, clamped to 0..1. */
export const span = (v: number, from: number, to: number) =>
  to === from ? (v >= to ? 1 : 0) : clamp01((v - from) / (to - from));

export const outCubic: Ease = (t) => 1 - (1 - clamp01(t)) ** 3;
export const inOutCubic: Ease = (t) => {
  const u = clamp01(t);
  return u < 0.5 ? 4 * u * u * u : 1 - (-2 * u + 2) ** 3 / 2;
};
export const inOutSine: Ease = (t) => (1 - Math.cos(Math.PI * clamp01(t))) / 2;
/** Quintic smootherstep: zero speed and acceleration at both ends (the director's `travel`). */
export const smootherstep: Ease = (t) => {
  const u = clamp01(t);
  return u * u * u * (u * (u * 6 - 15) + 10);
};

/** CSS-style cubic-bezier easing (x1, y1, x2, y2). */
export function bezier(x1: number, y1: number, x2: number, y2: number): Ease {
  const cx = 3 * x1;
  const bx = 3 * (x2 - x1) - cx;
  const ax = 1 - cx - bx;
  const cy = 3 * y1;
  const by = 3 * (y2 - y1) - cy;
  const ay = 1 - cy - by;
  const sx = (t: number) => ((ax * t + bx) * t + cx) * t;
  const sy = (t: number) => ((ay * t + by) * t + cy) * t;
  const dsx = (t: number) => (3 * ax * t + 2 * bx) * t + cx;
  return (x) => {
    const u = clamp01(x);
    let t = u;
    for (let i = 0; i < 8; i++) {
      const err = sx(t) - u;
      if (Math.abs(err) < 1e-6) break;
      const d = dsx(t);
      if (Math.abs(d) < 1e-6) break;
      t -= err / d;
    }
    return sy(clamp01(t));
  };
}

/** Decisive start, long soft landing: the default for things arriving on screen. */
export const glide = bezier(0.16, 1, 0.3, 1);
/** Symmetric move with gentle ends, for things travelling between two states. */
export const travel = bezier(0.65, 0, 0.35, 1);

/** Opacity envelope: fades in over `fade` after `start`, out over `fade` before `end`. */
export const envelope = (v: number, start: number, end: number, fade: number) =>
  inOutSine(span(v, start, start + fade)) * (1 - inOutSine(span(v, end - fade, end)));
