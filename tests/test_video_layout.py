"""Testes unitários para regras de layout particionado e ausência de colisão."""

import unittest
import numpy as np

from ride_visuals.video.layout import VideoPartitionLayout


class TestVideoLayout(unittest.TestCase):
    def test_layout_16_9_partition(self):
        layout = VideoPartitionLayout.create(1920, 1080, mode="16:9")
        self.assertEqual(layout.map_rect.w, int(1920 * 0.70))
        self.assertEqual(layout.telemetry_rect.w, 1920 - int(1920 * 0.70))
        self.assertEqual(layout.map_rect.h, 1080)
        self.assertEqual(layout.telemetry_rect.h, 1080)
        self.assertFalse(layout.map_rect.intersects(layout.telemetry_rect))

    def test_layout_9_16_partition(self):
        layout = VideoPartitionLayout.create(1080, 1920, mode="9:16")
        self.assertEqual(layout.map_rect.h, int(1920 * 0.60))
        self.assertEqual(layout.telemetry_rect.h, 1920 - int(1920 * 0.60))
        self.assertEqual(layout.map_rect.w, 1080)
        self.assertEqual(layout.telemetry_rect.w, 1080)
        self.assertFalse(layout.map_rect.intersects(layout.telemetry_rect))

    def test_projected_route_stays_within_map_rect(self):
        layout = VideoPartitionLayout.create(1920, 1080, mode="16:9")
        # Simular coordenadas geográficas de uma rota
        xs = np.linspace(100000, 200000, 50)
        ys = np.linspace(500000, 600000, 50)

        px, py = layout.project_route_to_map(xs, ys)

        # Todos os pontos de pixel devem estar estritamente dentro de map_rect
        self.assertTrue(np.all(px >= layout.map_rect.x0))
        self.assertTrue(np.all(px <= layout.map_rect.x1))
        self.assertTrue(np.all(py >= layout.map_rect.y0))
        self.assertTrue(np.all(py <= layout.map_rect.y1))

        # Nenhum ponto pode invadir telemetry_rect
        self.assertTrue(np.all(px < layout.telemetry_rect.x0))


if __name__ == "__main__":
    unittest.main()
