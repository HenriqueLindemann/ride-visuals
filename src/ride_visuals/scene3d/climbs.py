"""Climb detection on a distance-resampled, smoothed altitude profile.

A climb runs from a valley to the next summit of a hysteresis zig-zag (small
dips do not end it). A false flat is not a summit either: when the road dips
and then climbs past the previous high point, the two rises are one climb as
long as the dip is small next to the whole climb (a 30 m descent half way up a
450 m mountain road). A climb is kept when it gains enough height at a grade a
rider would call a climb, starting where the climbing starts: a long gentle
valley road leading to a steep finish is trimmed to the start that maximises
the climb's score (a lead-in at a lower grade only dilutes it). Scores follow
the usual length x grade logic of climb categories (proportional to the FIETS
index), so a long steady road outranks a short ramp of equal gain.
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


def _rises(
    dist: np.ndarray,
    alt: np.ndarray,
    pivots: list[int],
    *,
    min_grade_pct: float,
    max_dip: float,
    max_gap: float,
) -> list[tuple[int, int]]:
    """Rising legs of the zig-zag, joined across false summits.

    The rise after a dip continues the climb before it when both are steep
    enough to be climbing (a rolling approach is not part of the climb), the
    new rise ends higher than that climb's summit, the dip loses at most
    ``max_dip`` of the joined gain, and the way down and back takes at most
    ``max_gap`` of its length.
    """

    def steep(a: int, b: int) -> bool:
        return 100.0 * (alt[b] - alt[a]) >= min_grade_pct * max(dist[b] - dist[a], 1.0)

    rises: list[tuple[int, int]] = []
    for a, b in zip(pivots[:-1], pivots[1:], strict=True):
        if alt[b] <= alt[a]:
            continue
        if rises:
            start, summit = rises[-1]
            gain = alt[b] - alt[start]
            if (
                steep(start, summit)
                and steep(a, b)
                and alt[b] > alt[summit]
                and alt[summit] - alt[a] <= max_dip * gain
                and dist[a] - dist[summit] <= max_gap * (dist[b] - dist[start])
            ):
                rises[-1] = (start, b)
                continue
        rises.append((a, b))
    return rises


def _climbing_start(dist: np.ndarray, alt: np.ndarray, a: int, b: int, min_gain_m: float) -> int:
    """Start of the rise ``a..b`` that maximises gain^2 / length up to the summit ``b``."""
    gain = alt[b] - alt[a:b]
    length = np.maximum(dist[b] - dist[a:b], 1.0)
    score = np.where(gain >= min_gain_m, gain * gain / length, -np.inf)
    return a + int(np.argmax(score)) if np.isfinite(score).any() else a


def detect_climbs(
    dist: np.ndarray,
    alt: np.ndarray,
    *,
    min_gain_m: float = 40.0,
    min_grade_pct: float = 2.5,
    dip_m: float = 15.0,
    false_flat_dip: float = 0.15,
    false_flat_gap: float = 0.25,
) -> list[Climb]:
    """Climbs along a profile sampled at increasing distances (metres)."""
    dist = np.asarray(dist, dtype=float)
    alt = np.asarray(alt, dtype=float)
    if len(dist) < 3 or not np.isfinite(alt).all():
        return []
    pivots = _zigzag(alt, dip_m)
    climbs: list[Climb] = []
    rises = _rises(
        dist, alt, pivots, min_grade_pct=min_grade_pct, max_dip=false_flat_dip, max_gap=false_flat_gap
    )
    for a, b in rises:
        a = _climbing_start(dist, alt, a, b, min_gain_m)
        climb = Climb(float(dist[a]), float(dist[b]), float(alt[a]), float(alt[b]))
        if climb.gain_m >= min_gain_m and climb.grade_pct >= min_grade_pct:
            climbs.append(climb)
    return climbs


def hero_climb(climbs: list[Climb], min_gain_m: float = 100.0) -> Climb | None:
    """The climb of the day: the one that gains the most height, if it is a real climb.

    Scores rank climbs for difficulty, where a short wall can tie a mountain;
    the story is told by the road that climbs the most.
    """
    best = max(climbs, key=lambda climb: (climb.gain_m, climb.score), default=None)
    return best if best is not None and best.gain_m >= min_gain_m else None


def featured_climbs(climbs: list[Climb], limit: int = 3, *, include: Climb | None = None) -> list[Climb]:
    """The most significant climbs (always ``include``), in the order they are ridden."""
    ranked = sorted(climbs, key=lambda climb: climb.score, reverse=True)
    if include is not None:
        ranked = [include, *(climb for climb in ranked if climb != include)]
    return sorted(ranked[:limit], key=lambda climb: climb.start_m)
