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

    def calculate_time_in_zones(
        self,
        hr_series: np.ndarray,
        dt_seconds: float | np.ndarray = 1.0,
    ) -> Dict[str, float]:
        """Calculate time in each zone using scalar or per-sample durations."""
        heart_rates = np.asarray(hr_series, dtype=float)
        if np.isscalar(dt_seconds):
            durations = np.full(len(heart_rates), float(dt_seconds), dtype=float)
        else:
            durations = np.asarray(dt_seconds, dtype=float)
            if durations.shape != heart_rates.shape:
                raise ValueError("Heart-rate samples and durations must have the same shape")
        valid = np.isfinite(heart_rates) & np.isfinite(durations) & (durations >= 0.0)
        valid_hrs = heart_rates[valid]
        valid_durations = durations[valid]
        if len(valid_hrs) == 0:
            return {
                "z1_recovery_s": 0.0,
                "z2_aerobic_s": 0.0,
                "z3_tempo_s": 0.0,
                "z4_threshold_s": 0.0,
                "z5_anaerobic_s": 0.0,
                **{f"z{i}_pct": 0.0 for i in range(1, 6)},
            }

        def weighted_seconds(lower: float, upper: float | None = None) -> float:
            in_zone = valid_hrs >= lower
            if upper is not None:
                in_zone &= valid_hrs <= upper
            return float(np.sum(valid_durations[in_zone]))

        z1 = weighted_seconds(*self.z1_recovery)
        z2 = weighted_seconds(*self.z2_aerobic)
        z3 = weighted_seconds(*self.z3_tempo)
        z4 = weighted_seconds(*self.z4_threshold)
        z5 = weighted_seconds(self.z5_anaerobic[0])

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
