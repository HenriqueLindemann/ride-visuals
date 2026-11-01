import type * as maplibregl from 'maplibre-gl';
import {type RGB, rgba} from './draw';
import {lngLatsUpTo, type Track} from './track';

/**
 * A track the map draws itself, draped on the relief like its roads: the
 * land in front of it hides it exactly as it hides the land behind, in the
 * GPU's own depth, so it never flickers along a ridge.
 */
export type RouteDrape = {track: Track; to: number; rgb: RGB; alpha: number; width: number};

const ID = 'route';
/** Draped layers end here: anything standing in 3D goes over them. */
const BEFORE = 'buildings-3d';

/** What the map shows of the route, so an unchanged frame costs nothing. */
export type DrapeState = {track: Track | null; to: number; paint: string};

export const noDrape = (): DrapeState => ({track: null, to: -1, paint: ''});

const EMPTY: GeoJSON.Feature<GeoJSON.LineString> = {type: 'Feature', properties: {}, geometry: {type: 'LineString', coordinates: []}};

/** Shows `route` on the map, or hides it; new data loads asynchronously (see routeLoaded). */
export function applyDrape(map: maplibregl.Map, route: RouteDrape | null, state: DrapeState) {
  if (!route && !state.track) return;
  if (!map.getSource(ID)) {
    map.addSource(ID, {type: 'geojson', data: EMPTY});
    map.addLayer(
      {id: ID, type: 'line', source: ID, layout: {'line-cap': 'round', 'line-join': 'round'}, paint: {'line-color': '#000', 'line-opacity': 0}},
      map.getLayer(BEFORE) ? BEFORE : undefined,
    );
  }
  const visible = route && route.to > 1 && route.alpha > 0.002 ? route : null;
  const color = visible ? rgba(visible.rgb, 1) : '';
  const paint = visible ? `${color}|${visible.alpha.toFixed(3)}|${visible.width.toFixed(2)}` : 'none';
  if (paint !== state.paint) {
    map.setLayoutProperty(ID, 'visibility', visible ? 'visible' : 'none');
    if (visible) {
      map.setPaintProperty(ID, 'line-color', color);
      map.setPaintProperty(ID, 'line-opacity', Number(visible.alpha.toFixed(3)));
      map.setPaintProperty(ID, 'line-width', Number(visible.width.toFixed(2)));
    }
    state.paint = paint;
  }
  // A tenth of a metre more road is nothing on screen.
  const to = visible ? Math.round(visible.to * 10) / 10 : state.to;
  if (visible && (visible.track !== state.track || to !== state.to)) {
    (map.getSource(ID) as maplibregl.GeoJSONSource).setData({
      type: 'Feature',
      properties: {},
      geometry: {type: 'LineString', coordinates: lngLatsUpTo(visible.track, to)},
    });
    state.track = visible.track;
    state.to = to;
  }
}

/** Whether the route's latest data is in the map's tiles (true when there is no route). */
export const drapeLoaded = (map: maplibregl.Map) => !map.getSource(ID) || map.isSourceLoaded(ID);
