import * as maplibregl from 'maplibre-gl';
import {EARTH_CIRCUMFERENCE, FOV_DEG, groundResolution, mercX, mercY} from './geo';

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
  /** Buildings standing in 3D, 0..1. */
  buildings: number;
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
  /** Ground resolution at the screen centre (m/px), finer when pitched (see groundResolution). */
  resolution: number;
  /** Mercator point raised `lift` metres; returns false when it cannot be drawn. */
  merc(mx: number, my: number, lift: number, out: Float64Array): boolean;
  lngLat(lon: number, lat: number, lift?: number): [number, number, boolean];
  /** Depth (clip w) of the camera centre, the reference for perspective tapering. */
  centerDepth: number;
  /** Where the camera is: Mercator x, y and metres above the map (flat views only). */
  eye?: {mx: number; my: number; z: number};
  /** 3D terrain only: a point on the rendered relief (+lift), with line-of-sight occlusion. */
  onRelief?: (mx: number, my: number, lift: number, out: Float64Array) => Visibility;
  /** 3D terrain only: a point at an absolute exaggerated height, with occlusion. */
  inAir?: (mx: number, my: number, z: number, out: Float64Array, cutaway?: number) => Visibility;
  /** 3D terrain only: rendered terrain height (exaggerated metres) under a point. */
  ground?: (mx: number, my: number) => number;
}

type Matrix = ArrayLike<number>;

interface InternalMap {
  painter?: {context: {gl: WebGL2RenderingContext; bindFramebuffer: {set: (fbo: WebGLFramebuffer | null) => void}}};
  terrain?: {
    /** Depth of the rendered relief (Terrain.getFramebuffer), drawn at the start of each paint. */
    _fbo?: {framebuffer: WebGLFramebuffer; width: number; height: number};
    getElevationForLngLat: (lngLat: maplibregl.LngLat, transform: unknown) => number;
    /** Rendered DEM tiles. */
    getCoverageIndex?: () => {zooms: number[]; samplerPerTile: Map<string, unknown>} | null;
    getElevationForLngLatZoom: (lngLat: maplibregl.LngLat, zoom: number) => number;
    tileManager: {minzoom: number; maxzoom: number};
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

type DepthMap = {data: Uint8Array; width: number; height: number};

/**
 * The relief's depth as MapLibre drew it for this paint: one value per CSS
 * pixel, rows bottom first, the clip-space depth packed into RGBA (its
 * terrainDepth shader), white where no land was drawn.
 */
let depthBuffer = new Uint8Array(0);

function terrainDepth(map: maplibregl.Map): DepthMap | null {
  const internal = map as unknown as InternalMap;
  const fbo = internal.terrain?._fbo;
  const context = internal.painter?.context;
  if (!fbo || !context) return null;
  const {width, height} = fbo;
  // One buffer for every frame: a projector only lives until the next paint.
  if (depthBuffer.length !== width * height * 4) depthBuffer = new Uint8Array(width * height * 4);
  const data = depthBuffer;
  context.bindFramebuffer.set(fbo.framebuffer);
  context.gl.readPixels(0, 0, width, height, context.gl.RGBA, context.gl.UNSIGNED_BYTE, data);
  context.bindFramebuffer.set(null);
  return {data, width, height};
}

/** RGBA bytes back to the depth they pack (MapLibre's unpack). */
const UNPACK = [1 / (255 * 256 * 256 * 256), 1 / (255 * 256 * 256), 1 / (255 * 256), 1 / 255];

/** Ground height error (m, before exaggeration) between the drawn mesh and the sampled DEM. */
const HEIGHT_SLACK_M = 8;

/**
 * Occlusion against the relief exactly as rendered: a point is hidden when
 * the land drawn at its pixel lies nearer the eye than the point itself, less
 * a margin, so a line lying on a slope never hides itself. Far out at grazing
 * angles that margin grows with what one pixel and the mesh's height error
 * span along the view ray.
 */
function makeRelief(
  map: maplibregl.Map,
  eye: NonNullable<Projector['eye']>,
  worldSize: number,
  width: number,
  height: number,
  matrix: Matrix,
  project: (mx: number, my: number, z: number, out: Float64Array) => boolean,
  readDepth: boolean,
  exaggeration: number,
) {
  const internal = map as unknown as InternalMap;
  const terrain = internal.terrain;
  const transform = internal._camera?.transform;
  if (!terrain || !transform) return {};
  const probe = new maplibregl.LngLat(0, 0);
  // Off the rendered tiles, getElevationForLngLat re-covers the screen on every
  // call (~0.2 ms); its fallback zoom only depends on the frame, so find it once.
  let fallbackZoom = -1;
  const fallbackZ = () => {
    if (fallbackZoom < 0) {
      const {minzoom, maxzoom} = terrain.tileManager;
      let zoom = 0;
      for (const tile of map.coveringTiles({maxzoom, minzoom, tileSize: 512, terrain} as never)) {
        if (tile.canonical.z > zoom) zoom = Math.min(tile.canonical.z, maxzoom);
      }
      fallbackZoom = zoom;
    }
    return fallbackZoom;
  };
  const ground = (mx: number, my: number) => {
    probe.lng = mx * 360 - 180;
    probe.lat = unmercLat(my);
    const index = terrain.getCoverageIndex?.();
    const merc = index ? maplibregl.MercatorCoordinate.fromLngLat(probe) : null;
    if (index && merc && merc.y >= 0 && merc.y < 1) {
      const wrap = Math.floor(merc.x);
      const wrappedX = merc.x - wrap;
      for (const z of index.zooms) {
        const scale = 1 << z;
        const key = `${wrap}/${z}/${Math.floor(wrappedX * scale)}/${Math.floor(merc.y * scale)}`;
        if (!index.samplerPerTile.has(key)) continue;
        if (index.samplerPerTile.get(key)) return terrain.getElevationForLngLat(probe, transform);
        break;
      }
    }
    return terrain.getElevationForLngLatZoom(probe, fallbackZ());
  };
  // Read back on first use only: many frames test nothing against the relief.
  let depth: DepthMap | null | undefined = readDepth ? undefined : null;
  const m = matrix;
  const metersPerWorldPx = (my: number) =>
    (EARTH_CIRCUMFERENCE * Math.cos((unmercLat(my) * Math.PI) / 180)) / worldSize;
  const margin = Math.max(width, height) * 0.25;
  const pixelAngle = (FOV_DEG * Math.PI) / 180 / height;
  const slack = HEIGHT_SLACK_M * Math.max(1, exaggeration);
  const eyeX = eye.mx * worldSize;
  const eyeY = eye.my * worldSize;
  const test = (mx: number, my: number, z: number, out: Float64Array, cutaway: number, g: number): Visibility => {
    if (!project(mx, my, z, out)) return 0;
    if (out[0] < -margin || out[0] > width + margin || out[1] < -margin || out[1] > height + margin) return 1;
    if (depth === undefined) depth = terrainDepth(map);
    if (depth && out[0] >= 0 && out[0] < depth.width && out[1] >= 0 && out[1] < depth.height) {
      // The point brought nearer the eye (90 m, the grazing slack or `cutaway`):
      // only land in front of that can hide it.
      const x = mx * worldSize;
      const y = my * worldSize;
      const lengthM = Math.hypot(x - eyeX, y - eyeY) * metersPerWorldPx(my);
      const rise = Math.max(1, eye.z - z);
      const grazing = ((slack + 1.5 * pixelAngle * Math.hypot(lengthM, rise)) * lengthM) / rise;
      const s = 1 - Math.min(0.9, Math.max(90, grazing, cutaway) / Math.max(1, lengthM));
      const qx = eyeX + (x - eyeX) * s;
      const qy = eyeY + (y - eyeY) * s;
      const qz = eye.z + (z - eye.z) * s;
      const near = (m[2] * qx + m[6] * qy + m[10] * qz + m[14]) / (m[3] * qx + m[7] * qy + m[11] * qz + m[15]);
      const i = ((depth.height - 1 - Math.floor(out[1])) * depth.width + Math.floor(out[0])) * 4;
      const land = depth.data[i] * UNPACK[0] + depth.data[i + 1] * UNPACK[1] + depth.data[i + 2] * UNPACK[2] + depth.data[i + 3] * UNPACK[3];
      if (near > 0 && land < near) return 2;
    }
    if (!cutaway && z < (Number.isNaN(g) ? ground(mx, my) : g) - 4) return 2;
    return 1;
  };
  const inAir = (mx: number, my: number, z: number, out: Float64Array, cutaway = 0) => test(mx, my, z, out, cutaway, NaN);
  const onRelief = (mx: number, my: number, lift: number, out: Float64Array) => {
    const g = ground(mx, my);
    return test(mx, my, g + lift, out, 0, g);
  };
  return {onRelief, inAir, ground};
}

/**
 * `painted`: the map was painted for this camera, so its relief depth can
 * hide points; otherwise points are only tested against the ground height.
 */
export function makeProjector(
  map: maplibregl.Map,
  camera: Camera,
  frame: number,
  matrix: Matrix | null,
  width: number,
  height: number,
  painted = true,
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
  // The eye, recovered from the inverse matrix (world pixels for x, y; metres for z).
  const inv = !camera.globe && matrix ? invert4(matrix) : null;
  const eye = inv ? {mx: inv[8] / inv[11] / worldSize, my: inv[9] / inv[11] / worldSize, z: inv[10] / inv[11]} : undefined;
  const relief = eye && matrix && camera.terrain > 0 ? makeRelief(map, eye, worldSize, width, height, matrix, project, painted, camera.terrain) : {};
  return {
    frame,
    camera,
    width,
    height,
    globe: camera.globe,
    exaggeration: camera.terrain,
    resolution: groundResolution(camera.zoom, camera.center[1], camera.pitch),
    centerDepth,
    eye,
    merc: project,
    lngLat(lon, lat, lift = 0) {
      const ok = project(mercX(lon), mercY(lat), lift, scratch);
      return [scratch[0], scratch[1], ok];
    },
    ...relief,
  };
}
