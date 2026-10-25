"""Where one ride stands among the others: one closing line, or nothing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from ride_visuals.i18n import Translator

Metric = Literal["distance", "ascent"]

#: Below this many other rides, a record says little.
MIN_HISTORY = 8
#: Round marks a ride can be the first to pass (km, m).
DISTANCE_MARKS_KM = (50, 100, 150, 200, 250, 300, 400)
ASCENT_MARKS_M = (500, 1000, 1500, 2000, 2500, 3000, 4000, 5000)
#: Values within this share of each other count as a tie, never a record.
TIE = 0.002


@dataclass(frozen=True)
class RideRecord:
    """One ride of the archive, as compared here."""

    activity_id: int
    start_date: date | datetime | None
    distance_m: float
    ascent_m: float


@dataclass(frozen=True)
class Highlight:
    """The closing line, and which totals it is about (their values take the accent)."""

    text: str
    metrics: tuple[Metric, ...]


def _value(ride: RideRecord, metric: Metric) -> float:
    return ride.distance_m if metric == "distance" else ride.ascent_m


def _year(ride: RideRecord) -> int | None:
    return ride.start_date.year if isinstance(ride.start_date, (date, datetime)) else None


def _beats(value: float, others: Sequence[float]) -> bool:
    """Strictly above every other value, with a margin so a rounding tie is not a record."""
    return value > 0 and all(value > other * (1.0 + TIE) for other in others)


def _rank(value: float, others: Sequence[float]) -> int:
    return 1 + sum(other * (1.0 - TIE) >= value for other in others)


def ride_highlight(ride: RideRecord, archive: Sequence[RideRecord], i18n: Translator) -> Highlight | None:
    """The strongest true statement about ``ride`` against ``archive`` (which may include it).

    In order: a record over the whole archive (both measures read as one
    line), the first ride past a round mark, the best of its year, then
    second or third over the whole archive. Distance and ascent only: they
    are the totals on screen, so the line always points at a figure.
    """
    others = [r for r in archive if r.activity_id != ride.activity_id]
    if len(others) < MIN_HISTORY:
        return None
    metrics: tuple[Metric, ...] = ("ascent", "distance")

    best = tuple(m for m in metrics if _beats(_value(ride, m), [_value(o, m) for o in others]))
    if len(best) == 2:
        return Highlight(i18n.text("scene3d.highlight.best_both"), best)
    if best:
        return Highlight(i18n.text(f"scene3d.highlight.best_{best[0]}"), best)

    earlier = [o for o in others if _is_before(o, ride)]
    for metric, marks, unit in (("ascent", ASCENT_MARKS_M, 1.0), ("distance", DISTANCE_MARKS_KM, 1000.0)):
        value = _value(ride, metric)
        passed = [mark for mark in marks if value >= mark * unit]
        if not passed or len(earlier) < MIN_HISTORY:
            continue
        mark = passed[-1]
        if all(_value(o, metric) < mark * unit for o in earlier):
            return Highlight(i18n.text(f"scene3d.highlight.first_{metric}", mark=i18n.number(mark)), (metric,))

    year = _year(ride)
    same_year = [o for o in others if year is not None and _year(o) == year]
    if len(same_year) >= MIN_HISTORY:
        for metric in metrics:
            if _beats(_value(ride, metric), [_value(o, metric) for o in same_year]):
                return Highlight(i18n.text(f"scene3d.highlight.year_{metric}", year=year), (metric,))

    for metric in metrics:
        rank = _rank(_value(ride, metric), [_value(o, metric) for o in others])
        if rank in (2, 3):
            return Highlight(i18n.text(f"scene3d.highlight.rank{rank}_{metric}"), (metric,))
    return None


def _is_before(a: RideRecord, b: RideRecord) -> bool:
    if a.start_date is None or b.start_date is None:
        return False
    return _as_datetime(a.start_date) < _as_datetime(b.start_date)


def _as_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime(value.year, value.month, value.day)
