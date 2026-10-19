"""Elevation sampling from Terrarium tiles (the same relief the renderer drapes).

Used where the director needs the ground without a browser: filling the
altitude of recordings that have none, and keeping the camera above the
relief with a centre height that follows the lie of the land, not each ridge.
"""

from __future__ import annotations

import io
import math

import numpy as np
from PIL import Image

from ride_visuals.scene3d.tiles import TILE_SOURCES, TileCache


def decode_terrarium(data: bytes) -> np.ndarray:
    """Metres from a Terrarium PNG: (R * 256 + G + B / 256) - 32768."""
    rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float64)
    return rgb[..., 0] * 256.0 + rgb[..., 1] + rgb[..., 2] / 256.0 - 32768.0


def _tile_xy(lon: np.ndarray, lat: np.ndarray, zoom: int) -> tuple[np.ndarray, np.ndarray]:
    n = 2.0**zoom
    lat = np.clip(lat, -85.05, 85.05)
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2.0 * n
    return x, y


class DemSampler:
    """Bilinear elevation lookups at one zoom; tiles are fetched through the cache."""

    def __init__(self, cache: TileCache, zoom: int = 12) -> None:
        self.cache = cache
        self.zoom = zoom
        self._tiles: dict[tuple[int, int], np.ndarray | None] = {}

    def _tile(self, x: int, y: int) -> np.ndarray | None:
        limit = 2**self.zoom
        if y < 0 or y >= limit:
            return None
        key = (x % limit, y)
        if key not in self._tiles:
            data = self.cache.get(TILE_SOURCES["dem"], self.zoom, key[0], key[1])
            try:
                self._tiles[key] = decode_terrarium(data) if data else None
            except (OSError, ValueError):
                self._tiles[key] = None
        return self._tiles[key]

    def sample(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        """Elevation (m) at each point; NaN where no tile could be read."""
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        out = np.full(lon.shape, np.nan)
        flat_lon = lon.ravel()
        flat_lat = lat.ravel()
        valid = np.flatnonzero(np.isfinite(flat_lon) & np.isfinite(flat_lat))
        if len(valid) == 0:
            return out
        fxr, fyr = _tile_xy(flat_lon[valid], flat_lat[valid], self.zoom)
        tx = np.floor(fxr).astype(np.int64)
        ty = np.floor(fyr).astype(np.int64)
        flat = out.ravel()
        # Group points by tile in one sort instead of one mask per tile.
        keys = tx * (1 << 31) + ty
        order = np.argsort(keys, kind="stable")
        bounds = np.flatnonzero(np.diff(keys[order])) + 1
        for group in np.split(order, bounds):
            if len(group) == 0:
                continue
            x, y = int(tx[group[0]]), int(ty[group[0]])
            tile = self._tile(x, y)
            if tile is None:
                continue
            size = tile.shape[0]
            px = np.clip((fxr[group] - x) * size - 0.5, 0, size - 1.001)
            py = np.clip((fyr[group] - y) * size - 0.5, 0, size - 1.001)
            x0 = np.floor(px).astype(int)
            y0 = np.floor(py).astype(int)
            u = px - x0
            v = py - y0
            top = tile[y0, x0] * (1 - u) + tile[y0, x0 + 1] * u
            bottom = tile[y0 + 1, x0] * (1 - u) + tile[y0 + 1, x0 + 1] * u
            flat[valid[group]] = top * (1 - v) + bottom * v
        return flat.reshape(out.shape)

    def sample_blurred(self, lon: np.ndarray, lat: np.ndarray, radius_m: float) -> np.ndarray:
        """Mean elevation over a 5x5 neighbourhood spanning ±radius_m around each point."""
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        offsets = np.linspace(-radius_m, radius_m, 5)
        dlat = offsets / 110_540.0
        acc = np.zeros(lon.shape)
        count = np.zeros(lon.shape)
        for oy in dlat:
            for ox in offsets:
                dlon = ox / (111_320.0 * np.maximum(0.05, np.cos(np.radians(lat))))
                values = self.sample(lon + dlon, lat + oy)
                valid = np.isfinite(values)
                acc[valid] += values[valid]
                count[valid] += 1
        with np.errstate(invalid="ignore"):
            return np.where(count > 0, acc / np.maximum(count, 1), np.nan)
