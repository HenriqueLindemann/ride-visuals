"""Training load computation using the Banister TRIMP (Training Impulse) method."""

import math
import numpy as np


class TRIMPAnalyzer:
    """Compute Banister training impulses and cardiovascular load."""

    def __init__(self, resting_hr: float = 60.0, max_hr: float = 190.0, gender: str = "neutral"):
        self.resting_hr = resting_hr
        self.max_hr = max_hr
        coefficients = {"male": 1.92, "female": 1.67, "neutral": 1.795}
        self.b_coeff = coefficients.get(gender.lower(), coefficients["neutral"])

    def calculate_activity_trimp(self, hr_series: np.ndarray, duration_min: float) -> float:
        """Compute the TRIMP score of an activity from its HR time series or average HR."""
        valid_hrs = hr_series[~np.isnan(hr_series)]
        if len(valid_hrs) == 0 or duration_min <= 0:
            return 0.0

        avg_hr = np.mean(valid_hrs)
        # Heart-rate reserve fraction
        delta_hr = (avg_hr - self.resting_hr) / max(self.max_hr - self.resting_hr, 1.0)
        delta_hr = max(0.0, min(1.0, delta_hr))

        trimp = duration_min * delta_hr * 0.64 * math.exp(self.b_coeff * delta_hr)
        return float(round(trimp, 1))
