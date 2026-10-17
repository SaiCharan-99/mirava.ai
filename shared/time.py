"""Sim-time helpers: t = integer sim minutes since the world epoch (Day 1 = Monday 00:00)."""

from __future__ import annotations

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MIN_PER_DAY = 1440


def day_of(t: int) -> int:
    """1-based sim day."""
    return t // MIN_PER_DAY + 1


def minute_of_day(t: int) -> int:
    """Minutes since midnight of the current sim day."""
    return t % MIN_PER_DAY


def weekday(t: int) -> str:
    """Three-letter weekday name."""
    return DAYS[(t // MIN_PER_DAY) % 7]


def hhmm(t: int) -> str:
    """Clock time as HH:MM."""
    m = minute_of_day(t)
    return f"{m // 60:02d}:{m % 60:02d}"


def fmt(t: int) -> str:
    """Human label, e.g. 'Day 23 · Tue 08:40'."""
    return f"Day {day_of(t)} · {weekday(t)} {hhmm(t)}"


def at(day: int, hour: float) -> int:
    """Sim minute for a 1-based day and fractional hour."""
    return (day - 1) * MIN_PER_DAY + round(hour * 60)
