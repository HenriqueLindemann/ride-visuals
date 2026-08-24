"""Detecção de subidas significativas e cálculo de VAM (Vertical Ascent Meters/hour)."""

from typing import Dict, List, Any
import numpy as np


class ClimbAnalyzer:
    """Identifica trechos de subida contínua e calcula velocidade de ascensão vertical (VAM)."""

    @staticmethod
    def calculate_climb_vam(altitudes: np.ndarray, timestamps_sec: np.ndarray, min_gain_m: float = 30.0) -> List[Dict[str, Any]]:
        """Identifica segmentos de subida e calcula VAM (m/h)."""
        valid = ~np.isnan(altitudes)
        if np.sum(valid) < 20:
            return []

        v_alt = altitudes[valid]
        v_time = timestamps_sec[valid]

        climbs = []
        in_climb = False
        start_idx = 0

        for i in range(1, len(v_alt)):
            d_alt = v_alt[i] - v_alt[i - 1]
            if d_alt > 0:
                if not in_climb:
                    in_climb = True
                    start_idx = i - 1
            else:
                if in_climb:
                    gain = v_alt[i - 1] - v_alt[start_idx]
                    dt = v_time[i - 1] - v_time[start_idx]
                    if gain >= min_gain_m and dt > 10:
                        vam = (gain / dt) * 3600.0
                        climbs.append({
                            "gain_m": float(round(gain, 1)),
                            "duration_s": float(round(dt, 1)),
                            "vam_mh": float(round(vam, 1)),
                            "start_alt": float(round(v_alt[start_idx], 1)),
                            "end_alt": float(round(v_alt[i - 1], 1)),
                        })
                    in_climb = False

        if in_climb:
            gain = v_alt[-1] - v_alt[start_idx]
            dt = v_time[-1] - v_time[start_idx]
            if gain >= min_gain_m and dt > 10:
                vam = (gain / dt) * 3600.0
                climbs.append({
                    "gain_m": float(round(gain, 1)),
                    "duration_s": float(round(dt, 1)),
                    "vam_mh": float(round(vam, 1)),
                    "start_alt": float(round(v_alt[start_idx], 1)),
                    "end_alt": float(round(v_alt[-1], 1)),
                })

        return climbs
