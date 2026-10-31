import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {useEffect, useRef, useState} from 'react';
import {continueRender, delayRender, staticFile} from 'remotion';
import type {SceneSpec} from '../schema';
import {type Camera, makeProjector, type Projector} from './projector';
import {buildStyle, contourPaint, contourSource, hillshadePaint, satelliteMixPaint} from './style';
import {smootherstep, span} from './ease';
import {exactDrape, setExaggeration, type TileLod} from './terrain';

// The ESM worker cannot be resolved from inside the bundle; the Python engine
// stages it into public/scene3d (see stage_scene3d_assets).
maplibregl.setWorkerUrl(staticFile('scene3d/maplibre-gl-worker.mjs'));

const MAP_TIMEOUT_MS = 120_000;
/**
 * How many zoom levels a source's tiles span on screen, at up to how many
 * times the tiles of a flat view (mirrored in prefetch.py). MapLibre's
 * defaults (about 9 levels) sweep bands of detail across the land as the
 * camera moves, so rasters (relief, imagery, the terrain's own tiles) keep a
 * few levels and vector tiles one. Buildings only exist from 13: while a city
 * stands, more of them keep it to the horizon.
 */
const TILE_LOD = {raster: [3, 10], vector: [1, 12], city: [1, 30]} as const;
/**
 * Raster levels at a pitch. Few levels make a steep view ask for far more
 * tiles than the ratio allows, and MapLibre then coarsens all of it, the
 * foreground too: from RASTER_OPEN_PITCH the far land may drop away instead
 * (it is a few pixels under the fog), so the near land keeps its detail.
 */
const RASTER_OPEN_PITCH = [55, 75];
const RASTER_OPEN_LEVELS = 6;
const RASTER_SOURCES = ['dem', 'terrain', 'satellite'];
const rasterLevels = (pitch: number) =>
  TILE_LOD.raster[0] + (RASTER_OPEN_LEVELS - TILE_LOD.raster[0]) * smootherstep(span(pitch, RASTER_OPEN_PITCH[0], RASTER_OPEN_PITCH[1]));
/** Vector sources: lines and fills draped at any level, so all of one level (style.ts). */
const VECTORS = ['omt', 'contours', 'buildings'];
/**
 * Draped texels per terrain tile pixel, times the device pixel ratio. Tiles
 * keep near their own size on screen, so twice is already finer than the
 * screen: more measured no difference and cost four times the fill.
 */
const DRAPE_TEXELS = 2;

type Props = {
  spec: SceneSpec;
  frame: number;
  camera: Camera;
  width: number;
  height: number;
  onProjector: (projector: Projector) => void;
};

/** Keys of the map state applied incrementally, so unchanged values cost nothing. */
type Applied = {globe: boolean | null; terrain: number; opacity: number; contours: number; satellite: number; shade: number; buildings: number; city: boolean; levels: number};

/**
 * One MapLibre instance per render tab, driven frame by frame: jumpTo(camera),
 * wait until every tile is loaded and painted, then hand the overlays a
 * projector built from the exact matrix of that paint.
 */
export const MapStage = ({spec, frame, camera, width, height, onProjector}: Props) => {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const matrixRef = useRef<Float64Array | null>(null);
  const applied = useRef<Applied>({globe: null, terrain: -1, opacity: -1, contours: -1, satellite: -1, shade: -1, buildings: 0, city: false, levels: 0});
  const lodRef = useRef<TileLod | null>(null);
  const paintedRef = useRef(false);
  const [ready, setReady] = useState(false);
  const [initHandle] = useState(() => delayRender('map init', {timeoutInMilliseconds: MAP_TIMEOUT_MS}));

  useEffect(() => {
    contourSource(spec.tiles).setupMaplibre(maplibregl);
    const map = new maplibregl.Map({
      container: container.current!,
      style: buildStyle(spec.look, spec.tiles),
      interactive: false,
      attributionControl: false,
      canvasContextAttributes: {preserveDrawingBuffer: true, antialias: true},
      fadeDuration: 0,
      pixelRatio: window.devicePixelRatio || 1,
      center: camera.center,
      zoom: camera.zoom,
      pitch: camera.pitch,
      bearing: camera.bearing,
      maxPitch: 85,
      maxZoom: 18,
      maxTileCacheSize: 2000,
      refreshExpiredTiles: false,
      renderWorldCopies: false,
      // The director passes an explicit, smoothed centre elevation; clamping to
      // the relief under the centre would make the camera bob over every hill.
      centerClampedToGround: false,
    });
    mapRef.current = map;
    map.on('error', (event) => console.warn(`map error: ${event.error?.message ?? event}`));
    // The first paint is this frame's own: projection, LOD and camera are set
    // before it asks for a single tile (the style starts on the globe, at the ground).
    map.once('style.load', () => {
      for (const id of VECTORS) map.setSourceTileLodParams(...TILE_LOD.vector, id);
      setRasterLevels(map, camera.pitch, applied.current);
      map.setProjection({type: camera.globe ? 'globe' : 'mercator'});
      applied.current.globe = camera.globe;
      map.jumpTo({center: camera.center, zoom: camera.zoom, pitch: camera.pitch, bearing: camera.bearing, elevation: camera.elevation});
    });
    map.on('load', () => {
      // The drape follows the terrain source's rule, whatever its levels are now.
      const terrain = map.getSource('terrain') as unknown as {calculateTileZoom: TileLod};
      lodRef.current = (...args) => terrain.calculateTileZoom(...args);
      map.addLayer({
        id: 'capture',
        type: 'custom',
        renderingMode: '3d',
        render: (_gl, args) => {
          matrixRef.current = Float64Array.from(args.modelViewProjectionMatrix as ArrayLike<number>);
        },
      });
      setReady(true);
      continueRender(initHandle);
    });
    return () => map.remove();
    // The map lives for the whole tab; per-frame changes are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const handle = delayRender(`map frame ${frame}`, {timeoutInMilliseconds: MAP_TIMEOUT_MS});
    applyState(map, spec, camera, applied.current, lodRef.current!);
    if (camera.mapOpacity <= 0 && !camera.globe && paintedRef.current) {
      // Nothing of the map shows: no paint and no tiles to wait for. The
      // overlays project with this camera's own matrix over the last paint.
      onProjector(makeProjector(map, camera, frame, cameraMatrix(map, camera), width, height, false));
      continueRender(handle);
      return;
    }

    let done = false;
    let rendered = false;
    let poll: ReturnType<typeof setTimeout> | undefined;
    const settled = () => map.isStyleLoaded() && map.areTilesLoaded() && matrixRef.current !== null;
    const finish = () => {
      if (done) return;
      done = true;
      map.off('idle', finish);
      map.off('render', onRender);
      if (poll) clearTimeout(poll);
      paintedRef.current = true;
      onProjector(makeProjector(map, camera, frame, matrixRef.current, width, height));
      continueRender(handle);
    };
    // `idle` is the normal path, but it never fires when nothing needs a
    // repaint; also accept any paint after this jumpTo with every tile in
    // place, and poll as a last resort.
    const onRender = () => {
      rendered = true;
      if (settled()) finish();
    };
    const started = Date.now();
    const check = () => {
      if (done) return;
      if (settled() && (rendered || Date.now() - started > 400)) return finish();
      if (Date.now() - started > MAP_TIMEOUT_MS / 2) {
        reportUnsettled(spec, frame);
        return finish();
      }
      map.triggerRepaint();
      poll = setTimeout(check, 50);
    };
    map.once('idle', finish);
    map.jumpTo({
      center: camera.center,
      zoom: camera.zoom,
      pitch: camera.pitch,
      bearing: camera.bearing,
      // Also without relief: a stack of plates is orbited around its middle.
      elevation: camera.elevation,
    });
    map.on('render', onRender);
    map.triggerRepaint();
    poll = setTimeout(check, 50);
    return () => {
      if (done) return;
      done = true;
      map.off('idle', finish);
      map.off('render', onRender);
      if (poll) clearTimeout(poll);
      continueRender(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame, ready]);

  return <div ref={container} style={{position: 'absolute', left: 0, top: 0, width, height}} />;
};

type Transform = {
  clone: () => Transform;
  setCenter: (center: maplibregl.LngLat) => void;
  setZoom: (zoom: number) => void;
  setElevation: (elevation: number) => void;
  setBearing: (bearing: number) => void;
  setPitch: (pitch: number) => void;
  modelViewProjectionMatrix: ArrayLike<number>;
};

/** The matrix a paint for `camera` would hand the custom layers (mercator), without painting. */
function cameraMatrix(map: maplibregl.Map, camera: Camera): Float64Array {
  const tr = (map as unknown as {_camera: {transform: Transform}})._camera.transform.clone();
  tr.setCenter(new maplibregl.LngLat(camera.center[0], camera.center[1]));
  tr.setZoom(camera.zoom);
  tr.setElevation(camera.elevation);
  tr.setBearing(camera.bearing);
  tr.setPitch(camera.pitch);
  return Float64Array.from(tr.modelViewProjectionMatrix);
}

/**
 * Tell the tile server (which also serves the tiles) that a frame was painted
 * before all of its tiles arrived, so the render reports it instead of
 * shipping a frame with holes in silence.
 */
function reportUnsettled(spec: SceneSpec, frame: number) {
  console.warn(`map frame ${frame}: painted before every tile loaded`);
  try {
    const origin = new URL(spec.tiles.dem).origin;
    fetch(`${origin}/unsettled/frame/${frame}`, {keepalive: true}).catch(() => undefined);
  } catch {
    // A relative or custom tile URL (Studio): the console warning has to do.
  }
}

function setRasterLevels(map: maplibregl.Map, pitch: number, state: Applied) {
  const levels = Math.round(rasterLevels(pitch) * 20) / 20;
  if (state.levels === levels) return;
  for (const id of RASTER_SOURCES) if (map.getSource(id)) map.setSourceTileLodParams(levels, TILE_LOD.raster[1], id);
  state.levels = levels;
}

function applyState(map: maplibregl.Map, spec: SceneSpec, camera: Camera, state: Applied, lod: TileLod) {
  setRasterLevels(map, camera.pitch, state);
  if (state.globe !== camera.globe) {
    map.setProjection({type: camera.globe ? 'globe' : 'mercator'});
    state.globe = camera.globe;
  }
  const terrain = Math.round(camera.terrain * 1000) / 1000;
  if (state.terrain !== terrain) {
    if (!(terrain > 0 && state.terrain > 0 && setExaggeration(map, terrain))) {
      map.setTerrain(terrain > 0 ? {source: 'terrain', exaggeration: terrain} : null);
      exactDrape(map, lod, DRAPE_TEXELS * (window.devicePixelRatio || 1));
    }
    state.terrain = terrain;
  }
  const shade = Math.round(camera.shade * 100) / 100;
  if (state.shade !== shade) {
    for (const [prop, value] of Object.entries(hillshadePaint(shade))) {
      map.setPaintProperty('hillshade', prop as 'hillshade-exaggeration', value as number);
    }
    state.shade = shade;
  }
  const opacity = Math.round(camera.mapOpacity * 1000) / 1000;
  if (state.opacity !== opacity) {
    map.getCanvas().style.opacity = String(opacity);
    state.opacity = opacity;
  }
  const satellite = spec.look === 'satellite' && spec.tiles.satellite ? Math.round(camera.satellite * 100) / 100 : 0;
  // Contours need less ink over imagery.
  const contours = Math.round(camera.contours * (1 - 0.35 * satellite) * 100) / 100;
  if (state.contours !== contours) {
    if ((state.contours > 0) !== (contours > 0)) {
      map.setLayoutProperty('contours', 'visibility', contours > 0 ? 'visible' : 'none');
    }
    for (const [prop, value] of Object.entries(contourPaint(contours))) {
      map.setPaintProperty('contours', prop as 'line-opacity', value as number);
    }
    state.contours = contours;
  }
  const buildings = Math.round(camera.buildings * 100) / 100;
  if (state.buildings !== buildings) {
    // Fully off: hidden, so flat scenes pay nothing for it.
    map.setLayoutProperty('buildings-3d', 'visibility', buildings > 0 ? 'visible' : 'none');
    map.setPaintProperty('buildings-3d', 'fill-extrusion-opacity', buildings);
    state.buildings = buildings;
  }
  if (state.city !== buildings > 0) {
    const [levels, ratio] = TILE_LOD[buildings > 0 ? 'city' : 'vector'];
    map.setSourceTileLodParams(levels, ratio, 'buildings');
    state.city = buildings > 0;
  }
  if (spec.look === 'satellite' && spec.tiles.satellite && state.satellite !== satellite) {
    // Fully off: hide the imagery so its tiles are not even requested.
    map.setLayoutProperty('satellite', 'visibility', satellite > 0 ? 'visible' : 'none');
    for (const [layer, prop, value] of satelliteMixPaint(satellite)) {
      map.setPaintProperty(layer, prop as 'raster-opacity', value as number);
    }
    state.satellite = satellite;
  }
}
