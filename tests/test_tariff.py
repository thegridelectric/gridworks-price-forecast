"""Versant A-1 delivery periods and prices, by local wall-clock hour."""

from datetime import date, datetime

from gwpf.tariff import (
    OFF_PEAK_USD_PER_MWH,
    ON_PEAK_NON_WINTER_USD_PER_MWH,
    ON_PEAK_WINTER_USD_PER_MWH,
    SHOULDER_USD_PER_MWH,
    TARIFF_TZ,
    delivery_usd_per_mwh,
    holidays,
)


def at(year: int, month: int, day: int, hour: int) -> int:
    return int(datetime(year, month, day, hour, tzinfo=TARIFF_TZ).timestamp())


def test_weekday_windows_in_winter() -> None:
    # Tuesday 2026-01-20.
    assert delivery_usd_per_mwh(at(2026, 1, 20, 6)) == OFF_PEAK_USD_PER_MWH
    assert delivery_usd_per_mwh(at(2026, 1, 20, 7)) == ON_PEAK_WINTER_USD_PER_MWH
    assert delivery_usd_per_mwh(at(2026, 1, 20, 11)) == ON_PEAK_WINTER_USD_PER_MWH
    assert delivery_usd_per_mwh(at(2026, 1, 20, 12)) == SHOULDER_USD_PER_MWH
    assert delivery_usd_per_mwh(at(2026, 1, 20, 15)) == SHOULDER_USD_PER_MWH
    assert delivery_usd_per_mwh(at(2026, 1, 20, 16)) == ON_PEAK_WINTER_USD_PER_MWH
    assert delivery_usd_per_mwh(at(2026, 1, 20, 19)) == ON_PEAK_WINTER_USD_PER_MWH
    assert delivery_usd_per_mwh(at(2026, 1, 20, 20)) == OFF_PEAK_USD_PER_MWH


def test_non_winter_on_peak_rate() -> None:
    # Tuesday 2026-10-20.
    assert delivery_usd_per_mwh(at(2026, 10, 20, 8)) == ON_PEAK_NON_WINTER_USD_PER_MWH


def test_weekend_has_no_peak() -> None:
    # Saturday 2026-01-24.
    assert delivery_usd_per_mwh(at(2026, 1, 24, 8)) == SHOULDER_USD_PER_MWH
    assert delivery_usd_per_mwh(at(2026, 1, 24, 18)) == SHOULDER_USD_PER_MWH
    assert delivery_usd_per_mwh(at(2026, 1, 24, 21)) == OFF_PEAK_USD_PER_MWH


def test_holiday_has_no_peak() -> None:
    # Thanksgiving 2026 is Thursday 2026-11-26.
    assert date(2026, 11, 26) in holidays(2026)
    assert delivery_usd_per_mwh(at(2026, 11, 26, 8)) == SHOULDER_USD_PER_MWH


def test_holiday_dates() -> None:
    assert holidays(2026) == frozenset({
        date(2026, 1, 1),
        date(2026, 2, 16),
        date(2026, 4, 20),
        date(2026, 5, 25),
        date(2026, 7, 4),
        date(2026, 9, 7),
        date(2026, 10, 12),
        date(2026, 11, 11),
        date(2026, 11, 26),
        date(2026, 12, 25),
    })
