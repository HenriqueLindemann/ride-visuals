import * as maplibregl from 'maplibre-gl';
import {groundResolution, mercX, mercY} from './geo';

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
  /** Where the camera is: Mercator x, y and metres above the map (flat views only). */
  eye?: {mx: number; my: number; z: number};
  /** 3D terrain only: rendered terrain height (exaggerated metres) under a point. */
  ground?: (mx: number, my: number) => number;
}

type Matrix = ArrayLike<number>;

interface InternalMap {
  terrain?: {
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

/**
 * The height of the relief as MapLibre renders it, read off the DEM tiles it
 * drew (exaggerated metres), so a line laid on it sits on the land in view.
 */
function reliefGround(map: maplibregl.Map): Projector['ground'] {
  const internal = map as unknown as InternalMap;
  const terrain = internal.terrain;
  const transform = internal._camera?.transform;
  if (!terrain || !transform) return undefined;
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
  return (mx: number, my: number) => {
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
  // The eye, recovered from the inverse matrix (world pixels for x, y; metres for z).
  const inv = !camera.globe && matrix ? invert4(matrix) : null;
  const eye = inv ? {mx: inv[8] / inv[11] / worldSize, my: inv[9] / inv[11] / worldSize, z: inv[10] / inv[11]} : undefined;
  return {
    frame,
    camera,
    width,
    height,
    globe: camera.globe,
    exaggeration: camera.terrain,
    resolution: groundResolution(camera.zoom, camera.center[1], camera.pitch),
    eye,
    merc: project,
    lngLat(lon, lat, lift = 0) {
      const ok = project(mercX(lon), mercY(lat), lift, scratch);
      return [scratch[0], scratch[1], ok];
    },
    ground: !camera.globe && camera.terrain > 0 ? reliefGround(map) : undefined,
  };
}
