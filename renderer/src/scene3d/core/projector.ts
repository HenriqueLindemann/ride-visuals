import * as maplibregl from 'maplibre-gl';
import {mercX, mercY, metersPerPixel} from './geo';

/** One frame's camera and map state, as the Python director wrote it. */
export interface Camera {
  center: [number, number];
  zoom: number;
  pitch: number;
  bearing: number;
  elevation: number;
  terrain: number;
  globe: boolean;
  mapOpacity: number;
  contours: number;
  satellite: number;
  /** Hillshade contrast multiplier. */
  shade: number;
}

/** Visibility of a projected point: off-screen/behind, visible, or hidden by the relief. */
export type Visibility = 0 | 1 | 2;

/**
 * Projects geographic points to CSS pixels for exactly the frame the map just
 * painted, using the matrix MapLibre handed to its custom layers.
 */
export interface Projector {
  frame: number;
  camera: Camera;
  width: number;
  height: number;
  globe: boolean;
  exaggeration: number;
  /** Ground resolution at the screen centre (m/px), finer when pitched. */
  resolution: number;
  /** Mercator point raised `lift` metres; returns false when it cannot be drawn. */
  merc(mx: number, my: number, lift: number, out: Float64Array): boolean;
  lngLat(lon: number, lat: number, lift?: number): [number, number, boolean];
  /** Depth (clip w) of the camera centre, the reference for perspective tapering. */
  centerDepth: number;
  /** 3D terrain only: a point on the rendered relief (+lift), with line-of-sight occlusion. */
  onRelief?: (mx: number, my: number, lift: number, out: Float64Array) => Visibility;
  /** 3D terrain only: a point at an absolute exaggerated height, with occlusion. */
  inAir?: (mx: number, my: number, z: number, out: Float64Array, cutaway?: number) => Visibility;
  /** 3D terrain only: rendered terrain height (exaggerated metres) under a point. */
  ground?: (mx: number, my: number) => number;
}

type Matrix = ArrayLike<number>;

interface InternalMap {
  terrain?: {
    getElevationForLngLat: (lngLat: maplibregl.LngLat, transform: unknown) => number;
    /** Rendered DEM tiles; `maxElevation` is exaggerated metres plus a small pad. */
    getCoverageIndex?: () => {maxElevation: number} | null;
  };
  _camera?: {transform?: {isLocationOccluded?: (lngLat: maplibregl.LngLat) => boolean}};
}

const unmercLat = (my: number) => (360 / Math.PI) * Math.atan(Math.exp((180 - my * 360) * (Math.PI / 180))) - 90;

export function invert4(m: Matrix): Float64Array | null {
  const a = Array.from(m);
  const inv = new Float64Array(16);
  inv[0] = a[5] * a[10] * a[15] - a[5] * a[11] * a[14] - a[9] * a[6] * a[15] + a[9] * a[7] * a[14] + a[13] * a[6] * a[11] - a[13] * a[7] * a[10];
  inv[4] = -a[4] * a[10] * a[15] + a[4] * a[11] * a[14] + a[8] * a[6] * a[15] - a[8] * a[7] * a[14] - a[12] * a[6] * a[11] + a[12] * a[7] * a[10];
  inv[8] = a[4] * a[9] * a[15] - a[4] * a[11] * a[13] - a[8] * a[5] * a[15] + a[8] * a[7] * a[13] + a[12] * a[5] * a[11] - a[12] * a[7] * a[9];
  inv[12] = -a[4] * a[9] * a[14] + a[4] * a[10] * a[13] + a[8] * a[5] * a[14] - a[8] * a[6] * a[13] - a[12] * a[5] * a[10] + a[12] * a[6] * a[9];
  inv[1] = -a[1] * a[10] * a[15] + a[1] * a[11] * a[14] + a[9] * a[2] * a[15] - a[9] * a[3] * a[14] - a[13] * a[2] * a[11] + a[13] * a[3] * a[10];
  inv[5] = a[0] * a[10] * a[15] - a[0] * a[11] * a[14] - a[8] * a[2] * a[15] + a[8] * a[3] * a[14] + a[12] * a[2] * a[11] - a[12] * a[3] * a[10];
  inv[9] = -a[0] * a[9] * a[15] + a[0] * a[11] * a[13] + a[8] * a[1] * a[15] - a[8] * a[3] * a[13] - a[12] * a[1] * a[11] + a[12] * a[3] * a[9];
  inv[13] = a[0] * a[9] * a[14] - a[0] * a[10] * a[13] - a[8] * a[1] * a[14] + a[8] * a[2] * a[13] + a[12] * a[1] * a[10] - a[12] * a[2] * a[9];
  inv[2] = a[1] * a[6] * a[15] - a[1] * a[7] * a[14] - a[5] * a[2] * a[15] + a[5] * a[3] * a[14] + a[13] * a[2] * a[7] - a[13] * a[3] * a[6];
  inv[6] = -a[0] * a[6] * a[15] + a[0] * a[7] * a[14] + a[4] * a[2] * a[15] - a[4] * a[3] * a[14] - a[12] * a[2] * a[7] + a[12] * a[3] * a[6];
  inv[10] = a[0] * a[5] * a[15] - a[0] * a[7] * a[13] - a[4] * a[1] * a[15] + a[4] * a[3] * a[13] + a[12] * a[1] * a[7] - a[12] * a[3] * a[5];
  inv[14] = -a[0] * a[5] * a[14] + a[0] * a[6] * a[13] + a[4] * a[1] * a[14] - a[4] * a[2] * a[13] - a[12] * a[1] * a[6] + a[12] * a[2] * a[5];
  inv[3] = -a[1] * a[6] * a[11] + a[1] * a[7] * a[10] + a[5] * a[2] * a[11] - a[5] * a[3] * a[10] - a[9] * a[2] * a[7] + a[9] * a[3] * a[6];
  inv[7] = a[0] * a[6] * a[11] - a[0] * a[7] * a[10] - a[4] * a[2] * a[11] + a[4] * a[3] * a[10] + a[8] * a[2] * a[7] - a[8] * a[3] * a[6];
  inv[11] = -a[0] * a[5] * a[11] + a[0] * a[7] * a[9] + a[4] * a[1] * a[11] - a[4] * a[3] * a[9] - a[8] * a[1] * a[7] + a[8] * a[3] * a[5];
  inv[15] = a[0] * a[5] * a[10] - a[0] * a[6] * a[9] - a[4] * a[1] * a[10] + a[4] * a[2] * a[9] + a[8] * a[1] * a[6] - a[8] * a[2] * a[5];
  const det = a[0] * inv[0] + a[1] * inv[4] + a[2] * inv[8] + a[3] * inv[12];
  if (Math.abs(det) < 1e-30) return null;
  for (let i = 0; i < 16; i++) inv[i] /= det;
  return inv;
}

/**
 * Line-of-sight occlusion against the rendered relief. The eye is recovered
 * from the inverse matrix; a point is hidden when the ray from the eye dips
 * under the terrain anywhere before reaching it.
 */
function makeRelief(
  map: maplibregl.Map,
  matrix: Matrix,
  worldSize: number,
  width: number,
  height: number,
  project: (mx: number, my: number, z: number, out: Float64Array) => boolean,
) {
  const internal = map as unknown as InternalMap;
  const terrain = internal.terrain;
  const transform = internal._camera?.transform;
  const inv = invert4(matrix);
  if (!terrain || !transform || !inv) return {};
  const ew = inv[11];
  const eyeX = inv[8] / ew;
  const eyeY = inv[9] / ew;
  const eyeZ = inv[10] / ew;
  const probe = new maplibregl.LngLat(0, 0);
  const ground = (mx: number, my: number) => {
    probe.lng = mx * 360 - 180;
    probe.lat = unmercLat(my);
    return terrain.getElevationForLngLat(probe, transform);
  };
  const metersPerWorldPx = (my: number) =>
    (40_075_016.686 * Math.cos((unmercLat(my) * Math.PI) / 180)) / worldSize;
  const margin = Math.max(width, height) * 0.25;
  // Every point of a ray from the eye to an on-screen target is itself on
  // screen, so only the rendered tiles can block it: the stretch of the ray
  // above their highest point is never tested. (Those samples, far up under
  // the eye, also fall outside the rendered tiles, where each lookup costs a
  // full tile-covering pass.)
  const ceiling = terrain.getCoverageIndex?.()?.maxElevation ?? Infinity;
  const inAir = (mx: number, my: number, z: number, out: Float64Array, cutaway = 0): Visibility => {
    if (!project(mx, my, z, out)) return 0;
    if (out[0] < -margin || out[0] > width + margin || out[1] < -margin || out[1] > height + margin) return 1;
    const x = mx * worldSize;
    const y = my * worldSize;
    const dx = x - eyeX;
    const dy = y - eyeY;
    const dz = z - eyeZ;
    const lengthM = Math.hypot(dx, dy) * metersPerWorldPx(my);
    // Ignore the last ~90 m so a line lying on a slope does not shadow itself.
    const sMax = 1 - Math.min(0.9, Math.max(90, cutaway) / Math.max(1, lengthM));
    const steps = 40;
    // Ray fraction where it comes down to the relief's ceiling.
    const sTop = eyeZ > ceiling && dz < 0 ? (ceiling - eyeZ) / dz : 0;
    // From the point back towards the eye: samples crowd near the point,
    // where the ridges that matter usually are, so a hidden point exits early.
    for (let k = steps; k >= 1; k--) {
      const s = sMax * Math.sqrt(k / steps);
      if (s < sTop) break;
      if (eyeZ + dz * s < ground((eyeX + dx * s) / worldSize, (eyeY + dy * s) / worldSize) - 2) return 2;
    }
    if (!cutaway && z < ground(mx, my) - 4) return 2;
    return 1;
  };
  const onRelief = (mx: number, my: number, lift: number, out: Float64Array) => inAir(mx, my, ground(mx, my) + lift, out);
  return {onRelief, inAir, ground};
}

export function makeProjector(
  map: maplibregl.Map,
  camera: Camera,
  frame: number,
  matrix: Matrix | null,
  width: number,
  height: number,
): Projector {
  const worldSize = 512 * 2 ** camera.zoom;
  const internal = map as unknown as InternalMap;
  const project = (mx: number, my: number, z: number, out: Float64Array): boolean => {
    if (camera.globe || !matrix) {
      const lon = mx * 360 - 180;
      const lat = unmercLat(my);
      const p = map.project([lon, lat]);
      out[0] = p.x;
      out[1] = p.y;
      out[2] = 1;
      return !internal._camera?.transform?.isLocationOccluded?.(new maplibregl.LngLat(lon, lat));
    }
    // MapLibre v6 hands custom layers a matrix taking world pixels for x/y and
    // metres for z (it already scales z by pixels-per-metre).
    const m = matrix;
    const x = mx * worldSize;
    const y = my * worldSize;
    const cx = m[0] * x + m[4] * y + m[8] * z + m[12];
    const cy = m[1] * x + m[5] * y + m[9] * z + m[13];
    const cw = m[3] * x + m[7] * y + m[11] * z + m[15];
    if (cw <= 1e-9) return false;
    out[0] = (cx / cw + 1) * 0.5 * width;
    out[1] = (1 - (cy / cw + 1) * 0.5) * height;
    out[2] = cw;
    return true;
  };
  const scratch = new Float64Array(3);
  project(mercX(camera.center[0]), mercY(camera.center[1]), camera.elevation, scratch);
  const centerDepth = scratch[2] || 1;
  const relief = !camera.globe && matrix && camera.terrain > 0
    ? makeRelief(map, matrix, worldSize, width, height, project)
    : {};
  return {
    frame,
    camera,
    width,
    height,
    globe: camera.globe,
    exaggeration: camera.terrain,
    resolution: metersPerPixel(camera.zoom, camera.center[1]) * (camera.pitch > 30 ? 0.55 : 1),
    centerDepth,
    merc: project,
    lngLat(lon, lat, lift = 0) {
      const ok = project(mercX(lon), mercY(lat), lift, scratch);
      return [scratch[0], scratch[1], ok];
    },
    ...relief,
  };
}
