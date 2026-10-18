import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {useEffect, useRef, useState} from 'react';
import {continueRender, delayRender, staticFile} from 'remotion';
import type {SceneSpec} from '../schema';
import {type Camera, makeProjector, type Projector} from './projector';
import {buildStyle, contourPaint, contourSource, hillshadePaint, satelliteMixPaint} from './style';

// The ESM worker cannot be resolved from inside the bundle; the Python engine
// stages it into public/scene3d (see stage_scene3d_assets).
maplibregl.setWorkerUrl(staticFile('scene3d/maplibre-gl-worker.mjs'));

// MapLibre resets a DEM tile's "border backfilled" flags when a load starts,
// not when the new DEM arrives. A tile reloaded (projection or terrain switch)
// while a neighbour finishes gets its old DEM backfilled and flagged, and the
// fresh one keeps clamped borders: a flat 1 px edge the hillshade turns into a
// dark line along every such tile seam. Reset the flags once the DEM is in.
const loadDemTile = maplibregl.RasterDEMTileSource.prototype.loadTile;
maplibregl.RasterDEMTileSource.prototype.loadTile = async function (tile) {
  await loadDemTile.call(this, tile);
  if (tile.dem) tile.neighboringTiles = this._getNeighboringTiles(tile.tileID);
};

const MAP_TIMEOUT_MS = 120_000;

type Props = {
  spec: SceneSpec;
  frame: number;
  camera: Camera;
  width: number;
  height: number;
  onProjector: (projector: Projector) => void;
};

/** Keys of the map state applied incrementally, so unchanged values cost nothing. */
type Applied = {globe: boolean | null; terrain: number; opacity: number; contours: number; satellite: number; shade: number};

/**
 * One MapLibre instance per render tab, driven frame by frame: jumpTo(camera),
 * wait until every tile is loaded and painted, then hand the overlays a
 * projector built from the exact matrix of that paint.
 */
export const MapStage = ({spec, frame, camera, width, height, onProjector}: Props) => {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const matrixRef = useRef<Float64Array | null>(null);
  const applied = useRef<Applied>({globe: null, terrain: -1, opacity: -1, contours: -1, satellite: -1, shade: -1});
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
    map.on('load', () => {
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
    applyState(map, spec, camera, applied.current);

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
      if (Date.now() - started > MAP_TIMEOUT_MS / 2) return finish();
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame, ready]);

  return <div ref={container} style={{position: 'absolute', left: 0, top: 0, width, height}} />;
};

function applyState(map: maplibregl.Map, spec: SceneSpec, camera: Camera, state: Applied) {
  if (state.globe !== camera.globe) {
    map.setProjection({type: camera.globe ? 'globe' : 'mercator'});
    state.globe = camera.globe;
  }
  const terrain = Math.round(camera.terrain * 1000) / 1000;
  if (state.terrain !== terrain) {
    map.setTerrain(terrain > 0 ? {source: 'terrain', exaggeration: terrain} : null);
    state.terrain = terrain;
  }
  // Quantised: hillshade repaint is cheap, but not free on every frame.
  const shade = Math.round(camera.shade * 20) / 20;
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
  if (spec.look === 'satellite' && spec.tiles.satellite && state.satellite !== satellite) {
    // Fully off: hide the imagery so its tiles are not even requested.
    map.setLayoutProperty('satellite', 'visibility', satellite > 0 ? 'visible' : 'none');
    for (const [layer, prop, value] of satelliteMixPaint(satellite)) {
      map.setPaintProperty(layer, prop as 'raster-opacity', value as number);
    }
    state.satellite = satellite;
  }
}
