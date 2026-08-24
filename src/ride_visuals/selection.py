"""Reusable activity selection for ingest, analysis, and visual output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Iterable


def parse_date(value: str | date | datetime | None, *, end: bool = False) -> datetime | None:
    """Parse an ISO date or timestamp and normalize it to UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.max if end else time.min)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if len(str(value).strip()) == 10:
            parsed = datetime.combine(parsed.date(), time.max if end else time.min)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ActivitySelection:
    """Optional filters shared by every collection-level operation.

    Filters are combined with AND. Empty fields mean "all activities".
    """

    start_date: datetime | None = None
    end_date: datetime | None = None
    years: tuple[int, ...] = ()
    months: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        years = tuple(sorted({int(value) for value in self.years}))
        months = tuple(sorted({int(value) for value in self.months}))
        if any(month < 1 or month > 12 for month in months):
            raise ValueError("Months must be between 1 and 12")
        start = parse_date(self.start_date)
        end = parse_date(self.end_date, end=True)
        if start and end and start > end:
            raise ValueError("start_date must not be after end_date")
        object.__setattr__(self, "years", years)
        object.__setattr__(self, "months", months)
        object.__setattr__(self, "start_date", start)
        object.__setattr__(self, "end_date", end)

    @classmethod
    def from_values(
        cls,
        *,
        start_date: str | date | datetime | None = None,
        end_date: str | date | datetime | None = None,
        years: Iterable[int] = (),
        months: Iterable[int] = (),
    ) -> "ActivitySelection":
        return cls(
            start_date=parse_date(start_date),
            end_date=parse_date(end_date, end=True),
            years=tuple(years),
            months=tuple(months),
        )

    def matches(self, value: datetime) -> bool:
        moment = parse_date(value)
        assert moment is not None
        return not (
            (self.start_date and moment < self.start_date)
            or (self.end_date and moment > self.end_date)
            or (self.years and moment.year not in self.years)
            or (self.months and moment.month not in self.months)
        )

    def sql(self, column: str = "start_date") -> tuple[str, list[object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if self.start_date:
            clauses.append(f"{column} >= ?")
            parameters.append(self.start_date)
        if self.end_date:
            clauses.append(f"{column} <= ?")
            parameters.append(self.end_date)
        if self.years:
            placeholders = ", ".join("?" for _ in self.years)
            clauses.append(f"year({column}) IN ({placeholders})")
            parameters.extend(self.years)
        if self.months:
            placeholders = ", ".join("?" for _ in self.months)
            clauses.append(f"month({column}) IN ({placeholders})")
            parameters.extend(self.months)
        return (" WHERE " + " AND ".join(clauses) if clauses else "", parameters)

    def slug(self) -> str:
        parts: list[str] = []
        if self.start_date:
            parts.append(f"from-{self.start_date.date().isoformat()}")
        if self.end_date:
            parts.append(f"to-{self.end_date.date().isoformat()}")
        if self.years:
            parts.append("years-" + "-".join(str(value) for value in self.years))
        if self.months:
            parts.append("months-" + "-".join(f"{value:02d}" for value in self.months))
        return "_".join(parts) or "all"

    def describe(self) -> str:
        return self.slug().replace("_", ", ")
