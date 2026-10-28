import * as maplibregl from 'maplibre-gl';

/**
 * MapLibre's 3D terrain, made frame-exact for a renderer that jumps the camera
 * once per frame and paints when every tile is in. These reach into internals
 * of the pinned maplibre-gl (6.11).
 */

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

/** A source tile's zoom for its distance from the camera (CalculateTileZoomFunction). */
export type TileLod = (requestedCenterZoom: number, distanceToTile2D: number, distanceToTileZ: number, distanceToCenter3D: number, fov: number) => number;

type DrapedTile = {releaseRTT: (painter: unknown) => void};

type RenderToTexture = {
  painter: unknown;
  rttSize: number;
  needsFollowUpFrame: boolean;
  _renderableTiles: DrapedTile[];
  _textureDifference: (tile: DrapedTile) => string;
  prepareForRender: (style: unknown, zoom: number) => void;
  exact?: boolean;
};

type OverscaledTileID = {key: string; terrainRttPosMatrix32f?: Float32Array};

/** The terrain's own tiles: one draped texture and one mesh each. */
type DrapeTiles = {
  tileManager: {update: (transform: unknown, terrain: unknown) => void; map: {painter: unknown; coveringTiles: (options: object) => OverscaledTileID[]}};
  tileSize: number;
  minzoom: number;
  maxzoom: number;
  _tiles: Record<string, DrapedTile>;
  _renderableTilesKeys: string[];
  _lastTilesetChange: number;
  update: (transform: unknown, terrain: unknown) => boolean;
  lod?: TileLod;
  patched?: boolean;
};

type Internals = {terrain?: {tileManager: DrapeTiles} | null; painter: {renderToTexture?: RenderToTexture | null}};

/** Orthographic tile-to-texture matrix (gl-matrix ortho(0, EXTENT, EXTENT, 0, 0, 1)). */
const RTT_MATRIX = new Float32Array([2 / maplibregl.EXTENT, 0, 0, 0, 0, -2 / maplibregl.EXTENT, 0, 0, 0, 0, -2, 0, -1, 1, -1, 1]);

/**
 * While the map moves, MapLibre keeps a draped texture when only the zoom or
 * the source tiles under it changed, and redraws such textures one per repaint
 * afterwards. A frame is taken on its first settled paint, so it would show
 * stale patches catching up a tile at a time, frames later. Redraw every
 * texture that differs in the frame that needs it.
 */
function redrawStaleDrapes(rtt: RenderToTexture) {
  const proto = Object.getPrototypeOf(rtt) as RenderToTexture;
  if (proto.exact) return;
  const prepare = proto.prepareForRender;
  proto.prepareForRender = function (this: RenderToTexture, style, zoom) {
    prepare.call(this, style, zoom);
    for (const tile of this._renderableTiles) if (this._textureDifference(tile) !== 'none') tile.releaseRTT(this.painter);
    this.needsFollowUpFrame = false;
  };
  proto.exact = true;
}

/**
 * MapLibre picks the terrain's tiles with its default spread of zoom levels,
 * whatever setSourceTileLodParams says for the sources draped on them. Pick
 * them with the sources' own rule, so the relief's texture and mesh step
 * between levels together with the hillshade, contours and land under them.
 */
function drapeTilesAt(tiles: DrapeTiles, lod: TileLod) {
  tiles.lod = lod;
  const proto = Object.getPrototypeOf(tiles) as DrapeTiles;
  if (proto.patched) return;
  const update = proto.update;
  proto.update = function (this: DrapeTiles, transform, terrain) {
    // The tile class is internal: borrow it from the tiles MapLibre made itself.
    const Tile = Object.values(this._tiles)[0]?.constructor as (new (id: OverscaledTileID, size: number) => DrapedTile) | undefined;
    if (!this.lod || !Tile) return update.call(this, transform, terrain);
    this.tileManager.update(transform, terrain);
    const map = this.tileManager.map;
    const keys = new Set<string>();
    let changed = false;
    this._renderableTilesKeys = [];
    const ids = map.coveringTiles({tileSize: this.tileSize, minzoom: this.minzoom, maxzoom: this.maxzoom, reparseOverscaled: false, terrain, calculateTileZoom: this.lod});
    for (const id of ids) {
      keys.add(id.key);
      this._renderableTilesKeys.push(id.key);
      if (this._tiles[id.key]) continue;
      id.terrainRttPosMatrix32f = RTT_MATRIX.slice();
      this._tiles[id.key] = new Tile(id, this.tileSize);
      this._lastTilesetChange = performance.now();
      changed = true;
    }
    for (const key in this._tiles) {
      if (keys.has(key)) continue;
      this._tiles[key].releaseRTT(map.painter);
      delete this._tiles[key];
      changed = true;
    }
    return changed;
  };
  proto.patched = true;
}

/**
 * Applies the above to the map's terrain once it is set: draped textures
 * redrawn in the frame they change, terrain tiles chosen by `lod`, and each
 * texture `texels` times the tile's own size, so the drape is always finer
 * than the screen and filtered down, whatever level its tile is at.
 */
export function exactDrape(map: maplibregl.Map, lod: TileLod, texels: number) {
  const internals = map as unknown as Internals;
  const rtt = internals.painter.renderToTexture;
  const tiles = internals.terrain?.tileManager;
  if (!rtt || !tiles) return;
  redrawStaleDrapes(rtt);
  drapeTilesAt(tiles, lod);
  rtt.rttSize = tiles.tileSize * texels;
}
