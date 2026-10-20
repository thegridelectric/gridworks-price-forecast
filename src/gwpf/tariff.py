"""Delivery price per hour under Versant Rate A-1, "Home Eco Rate with
Bonus Meter" (Bangor Hydro District, effective 2025-07-01).

The total-delivery price (distribution, transmission, stranded cost and
conservation energy charges) by period, in USD/MWh:

| period   | winter (Nov-Feb) | non-winter (Mar-Oct) |
|----------|------------------|----------------------|
| on-peak  | 612.10           | 597.28               |
| shoulder | 70.34            | 70.34                |
| off-peak | 64.26            | 64.26                |

Weekdays: on-peak 07:00-12:00 and 16:00-20:00, shoulder 12:00-16:00,
off-peak 20:00-07:00. Weekends and the tariff's ten holidays: shoulder
07:00-20:00, off-peak 20:00-07:00. All on the America/New_York wall
clock. The tariff's DST-bracketing schedule (the two weeks around each
transition) is not modelled; those hours take the standard windows.
"""

from datetime import date, datetime, timedelta
from enum import Enum, auto
from zoneinfo import ZoneInfo

from gwpf.sema.property_format import UTCSeconds

TARIFF_TZ = ZoneInfo("America/New_York")
WINTER_MONTHS = frozenset({11, 12, 1, 2})

ON_PEAK_WINTER_USD_PER_MWH = 612.10
ON_PEAK_NON_WINTER_USD_PER_MWH = 597.28
SHOULDER_USD_PER_MWH = 70.34
OFF_PEAK_USD_PER_MWH = 64.26


class Period(Enum):
    OnPeak = auto()
    Shoulder = auto()
    OffPeak = auto()


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th (1-based) given weekday (Monday=0) of the month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    """The last given weekday (Monday=0) of the month."""
    following = date(year + (month == 12), month % 12 + 1, 1)
    last = following - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def holidays(year: int) -> frozenset[date]:
    """The tariff's holidays: New Year's, Washington's, Patriot's,
    Memorial, Independence, Labor, Columbus, Veterans, Thanksgiving and
    Christmas, on the dates the tariff names them."""
    return frozenset({
        date(year, 1, 1),
        nth_weekday(year, 2, 0, 3),
        nth_weekday(year, 4, 0, 3),
        last_weekday(year, 5, 0),
        date(year, 7, 4),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 10, 0, 2),
        date(year, 11, 11),
        nth_weekday(year, 11, 3, 4),
        date(year, 12, 25),
    })


def period_at(local: datetime) -> Period:
    """The tariff period of the hour starting at a local wall-clock time."""
    hour = local.hour
    if hour < 7 or hour >= 20:
        return Period.OffPeak
    if local.weekday() >= 5 or local.date() in holidays(local.year):
        return Period.Shoulder
    if 12 <= hour < 16:
        return Period.Shoulder
    return Period.OnPeak


def delivery_usd_per_mwh(hour_start_s: UTCSeconds) -> float:
    """Total-delivery price for the hour starting at the given time."""
    local = datetime.fromtimestamp(hour_start_s, TARIFF_TZ)
    period = period_at(local)
    if period is Period.OffPeak:
        return OFF_PEAK_USD_PER_MWH
    if period is Period.Shoulder:
        return SHOULDER_USD_PER_MWH
    if local.month in WINTER_MONTHS:
        return ON_PEAK_WINTER_USD_PER_MWH
    return ON_PEAK_NON_WINTER_USD_PER_MWH
