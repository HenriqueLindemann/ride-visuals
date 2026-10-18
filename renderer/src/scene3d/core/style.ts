import mlcontour from 'maplibre-contour';
import type {StyleSpecification} from 'maplibre-gl';
import type {SceneSpec} from '../schema';

export type Look = SceneSpec['look'];
export type TileSet = SceneSpec['tiles'];

/** Hillshade paint for a relief contrast multiplier (boosted for close 3D shots). */
export function hillshadePaint(relief: number) {
  const k = (v: number) => Math.round(v * relief * 1000) / 1000;
  return {
    'hillshade-method': 'igor' as const,
    'hillshade-illumination-direction': 315,
    'hillshade-illumination-anchor': 'map' as const,
    'hillshade-highlight-color': `rgba(243,239,232,${Math.min(0.4, 0.09 * relief).toFixed(3)})`,
    'hillshade-shadow-color': `rgba(0,0,0,${Math.min(0.85, 0.5 + 0.12 * (relief - 1)).toFixed(3)})`,
    'hillshade-accent-color': 'rgba(0,0,0,0)',
    'hillshade-exaggeration': [
      'interpolate', ['linear'], ['zoom'],
      2, k(0.8), 7, k(0.5), 10, k(0.35), 13, k(0.3), 14.5, k(0.42),
    ] as unknown as number,
  };
}

let demSource: InstanceType<typeof mlcontour.DemSource> | null = null;
let demSourceKey = '';

/** Map zoom from which contours are overzoomed: where the relief is locked. */
const contourLock = (tiles: TileSet) => Math.max(10, Math.min(tiles.demMaxZoom - 2, 14));

/** Contour lines computed in a worker from the same DEM tiles the relief uses. */
export function contourSource(tiles: TileSet) {
  const key = `${tiles.dem}@${tiles.demMaxZoom}`;
  if (!demSource || demSourceKey !== key) {
    demSource = new mlcontour.DemSource({
      url: tiles.dem,
      encoding: 'terrarium',
      maxzoom: Math.min(tiles.demMaxZoom, 14),
      worker: true,
      cacheSize: 200,
    });
    demSourceKey = key;
  }
  return demSource;
}

/** Contour paint for an intensity 0..1: hairlines, with a firmer index line. */
export function contourPaint(k: number) {
  return {
    'line-opacity': ['match', ['get', 'level'], 1, 0.3 * k, 0.085 * k] as unknown as number,
    'line-width': ['match', ['get', 'level'], 1, 0.9, 0.6] as unknown as number,
  };
}

/** Dark, slightly desaturated imagery grade, so the accent stays the brightest thing. */
const SATELLITE_PAINT = {
  'raster-brightness-max': 0.62,
  'raster-brightness-min': 0.0,
  'raster-saturation': -0.3,
  'raster-contrast': 0.1,
  'raster-fade-duration': 0,
  'raster-resampling': 'linear' as const,
};

/** Paint for a satellite mix 0..1: imagery fades in while the carbon water fades out. */
export function satelliteMixPaint(mix: number): [string, string, unknown][] {
  const k = 1 - mix;
  return [
    ['satellite', 'raster-opacity', mix],
    ['water', 'fill-opacity', k],
    ['rivers', 'line-opacity', ['interpolate', ['linear'], ['zoom'], 6, 0.0, 8, 0.6 * k, 13, 0.75 * k]],
  ];
}

/**
 * Carbon cartography: near-black land, fields and towns a breath lighter so
 * forests read as dark masses, water deeper still, rivers and borders as
 * hairlines. No labels and no roads: the rides are the only bright thing.
 * The satellite look keeps the whole carbon map underneath and lays imagery
 * over its fills, below the relief shading, so a scene can cross-fade.
 */
export function buildStyle(look: Look, tiles: TileSet): StyleSpecification {
  const contours = contourSource(tiles);
  const style: StyleSpecification = {
    version: 8,
    projection: {type: 'globe'},
    sources: {
      // Declared 128 px (the files are 256): MapLibre loads two levels above
      // the map zoom, so the relief keeps its fine detail at chase distance.
      dem: {type: 'raster-dem', tiles: [tiles.dem], encoding: 'terrarium', tileSize: 128, maxzoom: tiles.demMaxZoom},
      // The same tiles again for the 3D mesh: terrain and hillshade pick tiles
      // differently, and sharing one source costs the hillshade its finest level.
      // demMaxZoom is locked per scene (relief_max_zoom in spec.py), so the
      // relief does not change detail as the camera zooms.
      terrain: {type: 'raster-dem', tiles: [tiles.dem], encoding: 'terrarium', tileSize: 128, maxzoom: tiles.demMaxZoom},
      omt: {type: 'vector', tiles: [tiles.vector], maxzoom: tiles.vectorMaxZoom},
      contours: {
        type: 'vector',
        tiles: [
          // Wider spacing only further out than the relief lock (demMaxZoom - 2
          // as a map zoom); from there on every line comes from the same tiles.
          contours.contourProtocolUrl({
            thresholds: {10: [50, 200], [contourLock(tiles)]: [25, 100]},
            contourLayer: 'contours',
            elevationKey: 'ele',
            levelKey: 'level',
            // Each contour tile from the DEM tile of its own level (the finest lines).
            overzoom: 0,
          }),
        ],
        minzoom: 10,
        // Locked with the relief (demMaxZoom is per scene): closer is overzoom.
        maxzoom: contourLock(tiles),
      },
    },
    sky: {
      'sky-color': '#000000',
      'horizon-color': '#0d0d0c',
      'fog-color': '#0A0A09',
      'fog-ground-blend': 0.3,
      'horizon-fog-blend': 0.6,
      'sky-horizon-blend': 0.6,
      'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 0.55, 4, 0.25, 7, 0],
    },
    layers: [
      {
        id: 'land',
        type: 'background',
        paint: {'background-color': ['interpolate', ['linear'], ['zoom'], 1, '#1b1a18', 5, '#121210', 8, '#0c0c0b']},
      },
      {
        id: 'fields',
        type: 'fill',
        source: 'omt',
        'source-layer': 'landcover',
        filter: ['in', ['get', 'class'], ['literal', ['farmland', 'grass']]],
        paint: {
          'fill-color': '#f3efe8',
          'fill-opacity': ['interpolate', ['linear'], ['zoom'], 6, 0, 8, 0.028, 12, 0.036],
          'fill-antialias': false,
        },
      },
      {
        id: 'built',
        type: 'fill',
        source: 'omt',
        'source-layer': 'landuse',
        filter: ['in', ['get', 'class'], ['literal', ['residential', 'suburb', 'neighbourhood', 'commercial', 'industrial', 'retail']]],
        paint: {
          'fill-color': '#f3efe8',
          'fill-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0.0, 12, 0.03],
          'fill-antialias': false,
        },
      },
      {
        id: 'buildings',
        type: 'fill',
        source: 'omt',
        'source-layer': 'building',
        minzoom: 13,
        paint: {'fill-color': '#f3efe8', 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0, 14, 0.05]},
      },
      {id: 'hillshade', type: 'hillshade', source: 'dem', paint: hillshadePaint(1)},
      {
        id: 'contours',
        type: 'line',
        source: 'contours',
        'source-layer': 'contours',
        layout: {visibility: 'none', 'line-join': 'round'},
        paint: {'line-color': '#f3efe8', ...contourPaint(0)},
      },
      {
        id: 'water',
        type: 'fill',
        source: 'omt',
        'source-layer': 'water',
        filter: ['!=', ['get', 'class'], 'swimming_pool'],
        paint: {'fill-color': '#030404', 'fill-opacity': 1},
      },
      {
        id: 'rivers',
        type: 'line',
        source: 'omt',
        'source-layer': 'waterway',
        filter: ['in', ['get', 'class'], ['literal', ['river', 'canal']]],
        layout: {'line-cap': 'round', 'line-join': 'round'},
        paint: {
          'line-color': '#3a4c58',
          'line-opacity': ['interpolate', ['linear'], ['zoom'], 6, 0.0, 8, 0.6, 13, 0.75],
          'line-width': ['interpolate', ['exponential', 1.6], ['zoom'], 7, 0.5, 10, 1.0, 14, 2.4],
        },
      },
      {
        id: 'countries',
        type: 'line',
        source: 'omt',
        'source-layer': 'boundary',
        filter: ['all', ['==', ['get', 'admin_level'], 2], ['!=', ['get', 'maritime'], 1]],
        paint: {
          'line-color': '#f3efe8',
          'line-opacity': ['interpolate', ['linear'], ['zoom'], 1, 0.12, 5, 0.18, 9, 0.28],
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.5, 9, 1.0],
          'line-dasharray': [2, 2.5],
        },
      },
    ],
  };
  if (look === 'satellite' && tiles.satellite) {
    style.sources.satellite = {type: 'raster', tiles: [tiles.satellite], tileSize: 256, maxzoom: tiles.satelliteMaxZoom};
    const at = style.layers.findIndex((layer) => layer.id === 'hillshade');
    style.layers.splice(at, 0, {id: 'satellite', type: 'raster', source: 'satellite', paint: SATELLITE_PAINT});
  }
  return style;
}
