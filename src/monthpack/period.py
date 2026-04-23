"""Discrete monthly period primitives."""

from __future__ import annotations

from datetime import date
from datetime import datetime
from dataclasses import dataclass
import re


@dataclass(frozen=True, order=True)
class Period:
    """Monthly period value represented as ``YYYYMM``."""

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int):
            raise TypeError("period value must be an integer")
        year = self.value // 100
        month = self.value % 100
        if year < 1:
            raise ValueError("period year must be greater than or equal to 1")
        if not 1 <= month <= 12:
            raise ValueError("period month must be between 1 and 12")

    @classmethod
    def from_parts(cls, year: int, month: int) -> Period:
        """Build a period from explicit year and month components."""
        return cls(year * 100 + month)

    @classmethod
    def from_int(cls, value: int) -> Period:
        """Build a period from an integer in ``YYYYMM`` or short ``YYMM`` format."""
        if not isinstance(value, int):
            raise TypeError("period integer must be an integer")
        if 1000 <= value <= 9999:
            year = 2000 + (value // 100)
            month = value % 100
            return cls.from_parts(year, month)
        return cls(value)

    @classmethod
    def from_string(cls, value: str) -> Period:
        """Build a period from common string representations."""
        if not isinstance(value, str):
            raise TypeError("period string must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("period string cannot be empty")

        compact_match = re.fullmatch(r"(\d{4})(\d{2})", stripped)
        if compact_match is not None:
            return cls.from_parts(int(compact_match.group(1)), int(compact_match.group(2)))

        short_compact_match = re.fullmatch(r"(\d{2})(\d{2})", stripped)
        if short_compact_match is not None:
            return cls.from_parts(
                2000 + int(short_compact_match.group(1)),
                int(short_compact_match.group(2)),
            )

        separated_match = re.fullmatch(r"(\d{4})[-/](\d{2})(?:[-/]\d{2})?(?:[T\s].*)?", stripped)
        if separated_match is not None:
            return cls.from_parts(int(separated_match.group(1)), int(separated_match.group(2)))

        short_separated_match = re.fullmatch(r"(\d{2})[-/](\d{2})", stripped)
        if short_separated_match is not None:
            return cls.from_parts(
                2000 + int(short_separated_match.group(1)),
                int(short_separated_match.group(2)),
            )

        raise ValueError(
            "period string must use a supported format such as YYYYMM, YYMM, YYYY-MM, YY-MM, or YYYY-MM-DD"
        )

    @classmethod
    def from_date(cls, value: date | datetime) -> Period:
        """Build a period from a date-like instance such as ``date``, ``datetime``, or ``pandas.Timestamp``."""
        if not hasattr(value, "year") or not hasattr(value, "month"):
            raise TypeError("period date must provide year and month attributes")
        year = getattr(value, "year")
        month = getattr(value, "month")
        if not isinstance(year, int) or not isinstance(month, int):
            raise TypeError("period date must provide integer year and month values")
        return cls.from_parts(year, month)

    @classmethod
    def coerce(cls, value: int | str | date | datetime | Period) -> Period:
        """Normalize common input types into ``Period``."""
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls.from_int(value)
        if isinstance(value, str):
            return cls.from_string(value)
        if isinstance(value, date):
            return cls.from_date(value)
        if hasattr(value, "year") and hasattr(value, "month"):
            return cls.from_date(value)
        return cls.from_int(value)

    @classmethod
    def range(cls, start: int | Period, end: int | Period) -> tuple[Period, ...]:
        """Expand a monthly range from ``start`` to ``end``, inclusive."""
        start_period = cls.coerce(start)
        end_period = cls.coerce(end)
        if start_period == end_period:
            return (start_period,)

        step = 1 if start_period < end_period else -1
        periods = [start_period]
        current = start_period
        while current != end_period:
            current = current + step
            periods.append(current)
        return tuple(periods)

    @property
    def year(self) -> int:
        return self.value // 100

    @property
    def month(self) -> int:
        return self.value % 100

    def previous(self, months: int = 1) -> Period:
        """Return a prior monthly period."""
        return self - months

    def next(self, months: int = 1) -> Period:
        """Return a later monthly period."""
        return self + months

    def shift(self, months: int) -> Period:
        """Move the period forward or backward by a number of months."""
        if not isinstance(months, int):
            raise TypeError("months must be an integer")

        absolute_month = (self.year * 12) + (self.month - 1) + months
        year, month_index = divmod(absolute_month, 12)
        return type(self).from_parts(year, month_index + 1)

    def __int__(self) -> int:
        return self.value

    def __str__(self) -> str:
        return f"{self.value:06d}"

    def __add__(self, other: int) -> Period:
        if not isinstance(other, int):
            return NotImplemented
        return self.shift(other)

    def __sub__(self, other: int | Period) -> Period | int:
        if isinstance(other, int):
            return self.shift(-other)
        if isinstance(other, Period):
            return ((self.year - other.year) * 12) + (self.month - other.month)
        return NotImplemented
