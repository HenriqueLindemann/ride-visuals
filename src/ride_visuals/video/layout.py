"""Sistema estrito de layout particionado para vídeos.

Regra inquebrável: A telemetria NUNCA cobre ou intercepta o traçado da rota ou os rótulos do mapa.
"""

from dataclasses import dataclass
from typing import Tuple, Dict, Any
import numpy as np


@dataclass(frozen=True)
class Rect:
    """Retângulo delimitador em pixels inteiros: (x0, y0, width, height)."""
    x0: int
    y0: int
    w: int
    h: int

    @property
    def x1(self) -> int:
        return self.x0 + self.w

    @property
    def y1(self) -> int:
        return self.y0 + self.h

    def intersects(self, other: "Rect") -> bool:
        """Verifica se há sobreposição entre dois retângulos."""
        return not (
            self.x1 <= other.x0 or
            self.x0 >= other.x1 or
            self.y1 <= other.y0 or
            self.y0 >= other.y1
        )


@dataclass
class VideoPartitionLayout:
    """Define a partição física do canvas do vídeo em área de mapa e área de telemetria."""
    canvas_w: int
    canvas_h: int
    aspect_ratio: str  # "16:9", "9:16", "clean"
    map_rect: Rect
    telemetry_rect: Rect
    safe_margin_px: int = 24

    @classmethod
    def create(cls, width: int, height: int, mode: str = "16:9") -> "VideoPartitionLayout":
        """Calcula a partição do canvas antes de qualquer enquadramento geográfico."""
        if mode == "16:9":
            # 70% à esquerda para mapa, 30% à direita para telemetria
            map_w = int(width * 0.70)
            telem_w = width - map_w
            map_r = Rect(0, 0, map_w, height)
            telem_r = Rect(map_w, 0, telem_w, height)
            return cls(width, height, "16:9", map_r, telem_r)

        elif mode == "9:16":
            # 60% no topo para mapa, 40% na base para telemetria
            map_h = int(height * 0.60)
            telem_h = height - map_h
            map_r = Rect(0, 0, width, map_h)
            telem_r = Rect(0, map_h, width, telem_h)
            return cls(width, height, "9:16", map_r, telem_r)

        elif mode == "clean":
            # 100% mapa com safe margin
            map_r = Rect(0, 0, width, height)
            telem_r = Rect(0, 0, 0, 0)
            return cls(width, height, "clean", map_r, telem_r)

        else:
            raise ValueError(f"Modo de layout desconhecido: {mode}")

    def project_route_to_map(self, xs_mercator: np.ndarray, ys_mercator: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Projeta coordenadas Mercator mantendo 1:1 isometric scale ($scale_x = scale_y$) dentro de map_rect."""
        valid = ~np.isnan(xs_mercator) & ~np.isnan(ys_mercator)
        if not np.any(valid):
            return xs_mercator, ys_mercator

        vx = xs_mercator[valid]
        vy = ys_mercator[valid]

        min_x, max_x = np.min(vx), np.max(vx)
        min_y, max_y = np.min(vy), np.max(vy)

        dx = max(max_x - min_x, 1.0)
        dy = max(max_y - min_y, 1.0)

        # Margem útil dentro do retângulo do mapa
        margin = self.safe_margin_px
        usable_w = max(self.map_rect.w - 2 * margin, 10)
        usable_h = max(self.map_rect.h - 2 * margin, 10)

        # Escala isométrica
        scale = min(usable_w / dx, usable_h / dy)

        x_center_geo = (min_x + max_x) / 2.0
        y_center_geo = (min_y + max_y) / 2.0

        x_center_pix = self.map_rect.x0 + self.map_rect.w / 2.0
        y_center_pix = self.map_rect.y0 + self.map_rect.h / 2.0

        # Y invertido no canvas de pixels (topo = 0)
        px = x_center_pix + (xs_mercator - x_center_geo) * scale
        py = y_center_pix - (ys_mercator - y_center_geo) * scale

        return px, py
