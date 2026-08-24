"""Gerenciador e compositor de basemaps raster externos."""

import io
import math
import os
import urllib.request
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote
from PIL import Image, ImageEnhance


TILE_PROVIDERS = {
    "satellite": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "ext": "jpg",
        "subdomains": [],
        "attribution": "Sources: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    },
    "topo": {
        "url": "https://tile.opentopomap.org/{z}/{x}/{y}.png",
        "ext": "png",
        "subdomains": ["a", "b", "c"],
        "attribution": "Map data: © OpenStreetMap contributors, SRTM · Map style: © OpenTopoMap (CC-BY-SA)",
    },
    "osm": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "ext": "png",
        "subdomains": ["a", "b", "c"],
        "attribution": "© OpenStreetMap contributors",
    },
    "dark": {
        "url": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "ext": "png",
        "subdomains": ["a", "b", "c", "d"],
        "attribution": "© OpenStreetMap contributors · © CARTO",
    },
}


def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> Tuple[float, float]:
    """Converte coordenadas geográficas para coordenadas de tile fracionárias."""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = (lon_deg + 180.0) / 360.0 * n
    ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def num2deg(xtile: float, ytile: float, zoom: int) -> Tuple[float, float]:
    """Converte coordenadas de tile para coordenadas geográficas."""
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return lat_deg, lon_deg


class TileManager:
    """Baixa, gerencia cache e costura tiles para compor o fundo de mapas e vídeos."""

    def __init__(self, cache_dir: Path = Path("data/cache/tiles")):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.carto_api_key = os.environ.get("CARTO_API_KEY", "").strip()

    def _tile_url(self, provider: str, z: int, x: int, y: int) -> str:
        url = TILE_PROVIDERS[provider]["url"].format(z=z, x=x, y=y)
        if provider == "dark" and self.carto_api_key:
            return f"{url}?key={quote(self.carto_api_key, safe='')}"
        return url

    def fetch_tile(self, provider: str, z: int, x: int, y: int) -> Optional[Image.Image]:
        """Recupera tile do cache ou faz download via HTTP com headers padrão."""
        if provider not in TILE_PROVIDERS:
            return None

        p_info = TILE_PROVIDERS[provider]
        ext = p_info["ext"]
        cache_provider = (
            "dark-authenticated"
            if provider == "dark" and self.carto_api_key
            else provider
        )
        cached_file = self.cache_dir / cache_provider / str(z) / f"{x}_{y}.{ext}"

        if cached_file.exists():
            try:
                return Image.open(cached_file).convert("RGB")
            except Exception:
                pass

        cached_file.parent.mkdir(parents=True, exist_ok=True)
        url = self._tile_url(provider, z, x, y)

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "RideVisuals/2.0 (Lossless Cycling Cartography)"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                img = Image.open(io.BytesIO(data)).convert("RGB")
                img.save(cached_file)
                return img
        except Exception:
            # Fallback elegante caso a rede esteja indisponível
            return None

    @staticmethod
    def optimal_zoom(min_lon: float, min_lat: float, max_lon: float, max_lat: float,
                     target_w: int, target_h: int, detail_scale: int = 1) -> int:
        """Choose source-tile zoom; detail 2 requests one extra zoom level.

        The target dimensions describe the actual raster being composed, while
        ``detail_scale`` controls oversampling of the source tiles. The final
        crop is always reduced with Lanczos, so geographic registration and
        output dimensions stay unchanged.
        """
        if detail_scale not in {1, 2}:
            raise ValueError("Map detail scale must be 1 (standard) or 2 (high)")
        lat_span = max(max_lat - min_lat, 0.001)
        lon_span = max(max_lon - min_lon, 0.001)
        z_lon = math.log2(360.0 / lon_span * (target_w / 256.0))
        z_lat = math.log2(180.0 / lat_span * (target_h / 256.0))
        zoom = int(math.floor(min(z_lon, z_lat))) + int(math.log2(detail_scale))
        return max(6, min(16, zoom))

    def render_basemap_layer(self,
                             min_lon: float, min_lat: float,
                             max_lon: float, max_lat: float,
                             target_w: int, target_h: int,
                             provider: str = "satellite",
                             dim_pct: float = 0.25,
                             detail_scale: int = 1) -> Image.Image:
        """Gera uma imagem perfeitamente alinhada com as coordenadas geográficas fornecidas."""
        if provider not in TILE_PROVIDERS or provider == "dark_plain":
            return Image.new("RGB", (target_w, target_h), color="#080c14")

        # 1. Calcular nível de zoom ótimo. High detail deliberately fetches
        # one additional zoom level (4x source pixels) before downsampling.
        zoom = self.optimal_zoom(
            min_lon, min_lat, max_lon, max_lat,
            target_w, target_h, detail_scale,
        )

        # 2. Coordenadas de tiles
        x0_f, y0_f = deg2num(max_lat, min_lon, zoom)
        x1_f, y1_f = deg2num(min_lat, max_lon, zoom)

        t_x0, t_y0 = int(math.floor(x0_f)), int(math.floor(y0_f))
        t_x1, t_y1 = int(math.ceil(x1_f)), int(math.ceil(y1_f))

        num_tiles_x = max(1, t_x1 - t_x0)
        num_tiles_y = max(1, t_y1 - t_y0)

        stitch_w = num_tiles_x * 256
        stitch_h = num_tiles_y * 256
        stitched = Image.new("RGB", (stitch_w, stitch_h), color="#080c14")

        # 3. Costurar tiles
        fetched_tiles = 0
        expected_tiles = num_tiles_x * num_tiles_y
        for tx in range(t_x0, t_x1):
            for ty in range(t_y0, t_y1):
                t_img = self.fetch_tile(provider, zoom, tx, ty)
                if t_img:
                    fetched_tiles += 1
                    px = (tx - t_x0) * 256
                    py = (ty - t_y0) * 256
                    stitched.paste(t_img, (px, py))

        # High-detail output must never masquerade as a valid empty basemap.
        # If the extra zoom level is unavailable offline, fall back atomically
        # to the standard cached layer rather than mixing imagery with holes.
        if detail_scale == 2 and fetched_tiles < expected_tiles:
            return self.render_basemap_layer(
                min_lon, min_lat, max_lon, max_lat, target_w, target_h,
                provider=provider, dim_pct=dim_pct, detail_scale=1,
            )

        # 4. Recortar exatamente os limites geográficos
        crop_x0 = int((x0_f - t_x0) * 256)
        crop_y0 = int((y0_f - t_y0) * 256)
        crop_x1 = int((x1_f - t_x0) * 256)
        crop_y1 = int((y1_f - t_y0) * 256)

        crop_w = max(10, crop_x1 - crop_x0)
        crop_h = max(10, crop_y1 - crop_y0)

        cropped = stitched.crop((crop_x0, crop_y0, crop_x0 + crop_w, crop_y0 + crop_h))
        resized = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)

        # 5. Aplicar escurecimento suave para manter a legibilidade máxima do traçado da atividade
        if dim_pct > 0.0:
            enhancer = ImageEnhance.Brightness(resized)
            resized = enhancer.enhance(1.0 - dim_pct)

        return resized
