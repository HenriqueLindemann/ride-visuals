"""Pure motion calculations for collection videos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ride_visuals.video.collection_data import ProjectedCollectionTrack


SUPPORTED_MOTIONS = frozenset({"chronological", "simultaneous", "elapsed", "comet"})


def smoothstep(progress: float) -> float:
    """Ease a normalized animation cursor while preserving its endpoints."""
    value = min(max(float(progress), 0.0), 1.0)
    return value * value * (3.0 - 2.0 * value)


def elapsed_point_count(elapsed_seconds: np.ndarray, cursor_seconds: float) -> int:
    """Return the number of samples visible at an elapsed-time cursor."""
    if len(elapsed_seconds) == 0 or cursor_seconds < 0:
        return 0
    return int(np.searchsorted(elapsed_seconds, cursor_seconds, side="right"))


def visible_distance_m(track: ProjectedCollectionTrack, point_count: int) -> float:
    """Return visible distance with the catalog total as a missing-data fallback."""
    if point_count <= 0:
        return 0.0
    distances = np.asarray(track.point_distances_m, dtype=float)
    if point_count >= len(distances):
        return track.dist_km * 1000.0
    finite = distances[:point_count][np.isfinite(distances[:point_count])]
    if len(finite):
        return float(finite[-1])
    return track.dist_km * 1000.0 * point_count / max(len(distances), 1)


def visible_ascent_m(track: ProjectedCollectionTrack, point_count: int) -> float:
    """Return visible ascent with the catalog total as a missing-data fallback."""
    if point_count <= 0:
        return 0.0
    ascents = np.asarray(track.point_ascents_m, dtype=float)
    if point_count >= len(ascents):
        return track.elev_m
    finite = ascents[:point_count][np.isfinite(ascents[:point_count])]
    if len(finite):
        return float(finite[-1])
    return track.elev_m * max(point_count - 1, 0) / max(len(ascents) - 1, 1)


def maximum_elapsed_seconds(tracks: Sequence[ProjectedCollectionTrack]) -> float:
    return max(
        (float(track.point_elapsed_s[-1]) for track in tracks if len(track.point_elapsed_s)),
        default=0.0,
    )


def parallel_point_counts(
    tracks: Sequence[ProjectedCollectionTrack],
    progress: float,
    *,
    elapsed: bool,
    max_elapsed_s: float | None = None,
) -> tuple[int, ...]:
    """Resolve per-route cursors for normalized or real-elapsed playback."""
    value = min(max(float(progress), 0.0), 1.0)
    if elapsed:
        maximum = maximum_elapsed_seconds(tracks) if max_elapsed_s is None else max_elapsed_s
        cursor = maximum * value
        return tuple(elapsed_point_count(track.point_elapsed_s, cursor) for track in tracks)
    return tuple(
        min(int(round(len(track.pixel_points) * value)), len(track.pixel_points))
        for track in tracks
    )


@dataclass(frozen=True)
class ParallelMotionState:
    progress: float
    point_counts: tuple[int, ...]
    distances_km: tuple[float, ...]
    finished_count: int
    routes_in_motion: int
    combined_distance_km: float
    combined_ascent_m: float
    cursor_elapsed_s: float


def parallel_motion_state(
    tracks: Sequence[ProjectedCollectionTrack],
    progress: float,
    *,
    elapsed: bool,
    max_elapsed_s: float | None = None,
) -> ParallelMotionState:
    """Calculate every metric needed to paint one parallel-motion frame."""
    value = min(max(float(progress), 0.0), 1.0)
    maximum = maximum_elapsed_seconds(tracks) if max_elapsed_s is None else max_elapsed_s
    counts = parallel_point_counts(
        tracks,
        value,
        elapsed=elapsed,
        max_elapsed_s=maximum,
    )
    distances = tuple(
        visible_distance_m(track, count) / 1000.0
        for track, count in zip(tracks, counts)
    )
    finished = sum(
        count >= len(track.pixel_points)
        for track, count in zip(tracks, counts)
        if len(track.pixel_points)
    )
    return ParallelMotionState(
        progress=value,
        point_counts=counts,
        distances_km=distances,
        finished_count=finished,
        routes_in_motion=len(tracks) - finished,
        combined_distance_km=float(sum(distances)),
        combined_ascent_m=sum(
            visible_ascent_m(track, count)
            for track, count in zip(tracks, counts)
        ),
        cursor_elapsed_s=maximum * value,
    )


def normalized_distance_profile(
    tracks: Sequence[ProjectedCollectionTrack],
    axis: np.ndarray,
) -> np.ndarray:
    """Return combined route distance along a normalized progress axis."""
    return np.asarray(
        [
            parallel_motion_state(tracks, value, elapsed=False).combined_distance_km
            for value in axis
        ],
        dtype=float,
    )
