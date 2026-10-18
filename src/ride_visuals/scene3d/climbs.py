"""Climb detection on a distance-resampled, smoothed altitude profile.

A climb runs from a valley to the next summit of a hysteresis zig-zag (small
dips do not end it), and is kept when it gains enough height at a grade a rider
would call a climb. Scores follow the usual length x grade logic of climb
categories, so a long steady road outranks a short ramp of equal gain.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Climb:
    start_m: float
    end_m: float
    start_alt: float
    end_alt: float

    @property
    def gain_m(self) -> float:
        return self.end_alt - self.start_alt

    @property
    def length_m(self) -> float:
        return self.end_m - self.start_m

    @property
    def grade_pct(self) -> float:
        return 100.0 * self.gain_m / max(self.length_m, 1.0)

    @property
    def score(self) -> float:
        return self.length_m * self.grade_pct**2 / 100.0


def _zigzag(alt: np.ndarray, threshold: float) -> list[int]:
    """Indices of alternating extrema that differ by at least ``threshold``."""
    n = len(alt)
    if n < 2:
        return [0]
    # Until the first swing of `threshold`, follow both extremes: whichever came
    # first becomes the opening pivot, the other the running candidate.
    low = high = 0
    i = 1
    while i < n and alt[high] - alt[low] < threshold:
        if alt[i] > alt[high]:
            high = i
        if alt[i] < alt[low]:
            low = i
        i += 1
    if alt[high] - alt[low] < threshold:
        return [0, n - 1]
    rising = high > low
    first, candidate = (low, high) if rising else (high, low)
    pivots = [0] if first == 0 else [0, first]
    for j in range(i, n):
        if rising:
            if alt[j] > alt[candidate]:
                candidate = j
            elif alt[candidate] - alt[j] >= threshold:
                pivots.append(candidate)
                rising, candidate = False, j
        elif alt[j] < alt[candidate]:
            candidate = j
        elif alt[j] - alt[candidate] >= threshold:
            pivots.append(candidate)
            rising, candidate = True, j
    pivots.append(candidate)
    return pivots


def detect_climbs(
    dist: np.ndarray,
    alt: np.ndarray,
    *,
    min_gain_m: float = 40.0,
    min_grade_pct: float = 2.5,
    dip_m: float = 15.0,
) -> list[Climb]:
    """Climbs along a profile sampled at increasing distances (metres)."""
    dist = np.asarray(dist, dtype=float)
    alt = np.asarray(alt, dtype=float)
    if len(dist) < 3 or not np.isfinite(alt).all():
        return []
    pivots = _zigzag(alt, dip_m)
    climbs: list[Climb] = []
    for a, b in zip(pivots[:-1], pivots[1:], strict=True):
        if alt[b] <= alt[a]:
            continue
        climb = Climb(float(dist[a]), float(dist[b]), float(alt[a]), float(alt[b]))
        if climb.gain_m >= min_gain_m and climb.grade_pct >= min_grade_pct:
            climbs.append(climb)
    return climbs


def featured_climbs(climbs: list[Climb], limit: int = 3) -> list[Climb]:
    """The most significant climbs, in the order they are ridden."""
    best = sorted(climbs, key=lambda climb: climb.score, reverse=True)[:limit]
    return sorted(best, key=lambda climb: climb.start_m)
