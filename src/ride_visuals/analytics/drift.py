"""Cálculo de desacoplamento aeróbio e drift cardíaco (Speed:HR)."""

from typing import Dict, Any
import numpy as np


class DriftAnalyzer:
    """Mede desacoplamento cardíaco comparando a eficiência na 1ª vs 2ª metade da atividade."""

    @staticmethod
    def calculate_aerobic_drift(speed_series: np.ndarray, hr_series: np.ndarray, min_points: int = 600) -> Dict[str, Any]:
        """Calcula o drift % entre a primeira e a segunda metade da atividade.
        
        Drift < 5%: Excelente estabilidade aeróbia.
        Drift > 5%: Fadiga cardiovascular / desacoplamento aeróbio perceptível.
        """
        valid = ~np.isnan(speed_series) & ~np.isnan(hr_series) & (speed_series > 1.0) & (hr_series > 60.0)
        v_speed = speed_series[valid]
        v_hr = hr_series[valid]

        if len(v_speed) < min_points:
            return {
                "valid": False,
                "reason": f"Amostra insuficiente de pontos contínuos ({len(v_speed)} < {min_points})",
                "drift_pct": 0.0,
            }

        mid = len(v_speed) // 2
        spd1, spd2 = v_speed[:mid], v_speed[mid:]
        hr1, hr2 = v_hr[:mid], v_hr[mid:]

        eff1 = np.mean(spd1) / max(np.mean(hr1), 1.0)
        eff2 = np.mean(spd2) / max(np.mean(hr2), 1.0)

        if eff1 <= 0:
            return {"valid": False, "reason": "Eficiência inicial nula", "drift_pct": 0.0}

        # Desacoplamento aeróbio: perda percentual de eficiência
        drift_pct = ((eff1 - eff2) / eff1) * 100.0

        return {
            "valid": True,
            "drift_pct": float(round(drift_pct, 2)),
            "efficiency_half1": float(round(eff1 * 1000.0, 2)),
            "efficiency_half2": float(round(eff2 * 1000.0, 2)),
            "avg_hr_half1": float(round(np.mean(hr1), 1)),
            "avg_hr_half2": float(round(np.mean(hr2), 1)),
            "avg_speed_half1_kmh": float(round(np.mean(spd1) * 3.6, 1)),
            "avg_speed_half2_kmh": float(round(np.mean(spd2) * 3.6, 1)),
        }
