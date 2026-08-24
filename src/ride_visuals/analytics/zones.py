"""Cálculo de zonas de frequência cardíaca e tempo sob esforço."""

from dataclasses import dataclass
from typing import Dict
import numpy as np


@dataclass
class HRZoneProfile:
    """Perfil de zonas cardíacas do ciclista."""
    resting_hr: float = 60.0
    max_hr: float = 190.0
    lthr: float = 170.0

    # Zonas [min_bpm, max_bpm]
    z1_recovery: (float, float) = (100.0, 131.0)
    z2_aerobic: (float, float) = (132.0, 149.0)
    z3_tempo: (float, float) = (150.0, 164.0)
    z4_threshold: (float, float) = (165.0, 175.0)
    z5_anaerobic: (float, float) = (176.0, 195.0)

    def calculate_time_in_zones(self, hr_series: np.ndarray, dt_seconds: float = 1.0) -> Dict[str, float]:
        """Calcula o tempo gasto (em segundos e %) em cada zona cardíaca."""
        valid_hrs = hr_series[~np.isnan(hr_series)]
        if len(valid_hrs) == 0:
            return {f"z{i}": 0.0 for i in range(1, 6)}

        z1 = np.sum((valid_hrs >= self.z1_recovery[0]) & (valid_hrs <= self.z1_recovery[1])) * dt_seconds
        z2 = np.sum((valid_hrs >= self.z2_aerobic[0]) & (valid_hrs <= self.z2_aerobic[1])) * dt_seconds
        z3 = np.sum((valid_hrs >= self.z3_tempo[0]) & (valid_hrs <= self.z3_tempo[1])) * dt_seconds
        z4 = np.sum((valid_hrs >= self.z4_threshold[0]) & (valid_hrs <= self.z4_threshold[1])) * dt_seconds
        z5 = np.sum(valid_hrs >= self.z5_anaerobic[0]) * dt_seconds

        tot = max(z1 + z2 + z3 + z4 + z5, 1.0)
        return {
            "z1_recovery_s": float(z1),
            "z2_aerobic_s": float(z2),
            "z3_tempo_s": float(z3),
            "z4_threshold_s": float(z4),
            "z5_anaerobic_s": float(z5),
            "z1_pct": float(z1 / tot * 100.0),
            "z2_pct": float(z2 / tot * 100.0),
            "z3_pct": float(z3 / tot * 100.0),
            "z4_pct": float(z4 / tot * 100.0),
            "z5_pct": float(z5 / tot * 100.0),
        }
