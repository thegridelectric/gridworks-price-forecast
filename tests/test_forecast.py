"""Forecast documents built from a captured ISO-NE day, the watcher
that decides when to build one, and the view served through the API."""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gwpf import api
from gwpf.config import GwpfSettings
from gwpf.forecast import (
    DOCUMENT_HOURS,
    EXPECTING_POLL_S,
    IDLE_POLL_S,
    VIEW_HOURS,
    ForecastStore,
    PublicationWatcher,
    build_forecast,
    poll_interval_s,
    view,
)
from gwpf.isone import HourlyLmp, Publication, parse_day_ahead, parse_info
from gwpf.sema.types import PriceForecast
from gwpf.tariff import OFF_PEAK_TIMES1000, ON_PEAK_NON_WINTER_TIMES1000, TARIFF_TZ

TESTS = Path(__file__).parent
CAPTURE = TESTS / "isone-da-keene-2026-10-20.xml"
INFO_CAPTURE = TESTS / "isone-da-info-2026-11-12.xml"
CAPTURED_DAY = date(2026, 10, 20)


def at(day: date, hour: int, minute: int = 0) -> int:
    return int(
        datetime(
            day.year, day.month, day.day, hour, minute, tzinfo=TARIFF_TZ
        ).timestamp()
    )


# 09:10 on the captured day, before ISO-NE posts tomorrow.
NOW_S = at(CAPTURED_DAY, 9, 10)
POSTED_S = at(CAPTURED_DAY - timedelta(days=1), 13)


class CapturedIsone:
    """ISO-NE with the captured day posted, and optionally the day after
    it posted as a copy shifted by 24 hours."""

    def __init__(self) -> None:
        self.rows = parse_day_ahead(CAPTURE.read_text(), "43790")
        self.tomorrow_posted_s: int | None = None

    def post_tomorrow(self, posted_s: int) -> None:
        self.tomorrow_posted_s = posted_s

    def info(self) -> Publication:
        if self.tomorrow_posted_s is None:
            return Publication(at(CAPTURED_DAY, 23), POSTED_S)
        return Publication(
            at(CAPTURED_DAY + timedelta(days=1), 23), self.tomorrow_posted_s
        )

    def day_ahead(self, day: date) -> list[HourlyLmp]:
        if day == CAPTURED_DAY:
            return self.rows
        if day == CAPTURED_DAY + timedelta(days=1) and self.tomorrow_posted_s:
            return [
                row._replace(hour_start_s=row.hour_start_s + 86400) for row in self.rows
            ]
        return []


class FailingIsone:
    def info(self) -> Publication:
        raise ConnectionError("iso-ne unreachable")

    def day_ahead(self, day: date) -> list[HourlyLmp]:
        raise ConnectionError("iso-ne unreachable")


def settings(tmp_path: Path) -> GwpfSettings:
    return GwpfSettings(isone_user="u", isone_api_pass="p", data_dir=tmp_path)


def test_parse_captured_day() -> None:
    rows = parse_day_ahead(CAPTURE.read_text(), "43790")
    assert len(rows) == 24
    assert rows[0] == HourlyLmp(at(CAPTURED_DAY, 0), 29.24)


def test_parse_info() -> None:
    assert parse_info(INFO_CAPTURE.read_text()) == Publication(
        latest_begin_s=at(date(2026, 11, 13), 23),
        posted_s=at(date(2026, 11, 12), 13) + 3,
    )


def test_document_prices_and_basis(tmp_path: Path) -> None:
    source = CapturedIsone()
    forecast, basis = build_forecast(settings(tmp_path), source, source.info(), NOW_S)
    assert len(forecast.slot_start_s) == DOCUMENT_HOURS
    assert forecast.slot_start_s[0] == at(CAPTURED_DAY, 10)
    prices = forecast.price_x1000_list
    # 10:00 on the captured day: ISO-NE's LMP of -5.30 plus on-peak delivery.
    assert prices[0] == -5300 + ON_PEAK_NON_WINTER_TIMES1000
    # Midnight, past the posted day, repeats the posted midnight's LMP.
    assert prices[14] == 29240 + OFF_PEAK_TIMES1000
    # The 14 hours from 10:00 through 23:00 are ISO-NE's own.
    assert basis == (forecast.forecast_uid, POSTED_S, 14)
    assert PriceForecast.from_bytes(forecast.to_bytes()) == forecast


def test_view_is_a_cut_of_the_document_under_its_id(tmp_path: Path) -> None:
    source = CapturedIsone()
    forecast, _ = build_forecast(settings(tmp_path), source, source.info(), NOW_S)
    first = view(forecast, NOW_S)
    assert first is not None
    assert first.slot_start_s == forecast.slot_start_s[:VIEW_HOURS]
    later = view(forecast, NOW_S + 20 * 3600)
    assert later is not None
    assert later.forecast_uid == forecast.forecast_uid
    assert later.created_ms == forecast.created_ms
    assert later.slot_start_s == forecast.slot_start_s[20 : 20 + VIEW_HOURS]
    assert later.price_x1000_list == forecast.price_x1000_list[20:68]
    # Once too little of the document remains, there is no view.
    assert view(forecast, forecast.slot_start_s[-12] + 1) is None


def test_poll_interval() -> None:
    today_only = Publication(at(CAPTURED_DAY, 23), POSTED_S)
    with_tomorrow = Publication(at(CAPTURED_DAY + timedelta(days=1), 23), POSTED_S)
    assert poll_interval_s(today_only, at(CAPTURED_DAY, 9)) == IDLE_POLL_S
    # A check at 12:10 is followed by one just after 12:30.
    assert poll_interval_s(today_only, at(CAPTURED_DAY, 12, 10)) == 20 * 60 + 1
    assert poll_interval_s(today_only, at(CAPTURED_DAY, 12, 45)) == EXPECTING_POLL_S
    assert poll_interval_s(today_only, at(CAPTURED_DAY, 20)) == EXPECTING_POLL_S
    assert poll_interval_s(with_tomorrow, at(CAPTURED_DAY, 13, 5)) == IDLE_POLL_S


def test_watcher_builds_once_per_posting(tmp_path: Path) -> None:
    source = CapturedIsone()
    store = ForecastStore(tmp_path)
    watcher = PublicationWatcher(settings(tmp_path), source, store)
    first = watcher.step(NOW_S)
    assert first is not None
    assert store.load_kept() == first
    # Not due, then due with the same posting: nothing new.
    assert watcher.step(NOW_S + 60) is None
    assert watcher.step(NOW_S + IDLE_POLL_S) is None
    # ISO-NE posts tomorrow at 12:58; the watcher is polling by then.
    posted_s = at(CAPTURED_DAY, 12, 58)
    source.post_tomorrow(posted_s)
    second = watcher.step(at(CAPTURED_DAY, 13))
    assert second is not None
    assert second.forecast.forecast_uid != first.forecast.forecast_uid
    assert second.basis == (second.forecast.forecast_uid, posted_s, 34)
    assert store.load_kept() == second
    # A restart finds the kept document and builds nothing.
    restarted = PublicationWatcher(settings(tmp_path), source, store)
    assert restarted.step(at(CAPTURED_DAY, 13, 30)) is None
    assert restarted.kept == second


def test_watcher_rebuilds_when_the_document_cannot_fill_a_view(
    tmp_path: Path,
) -> None:
    source = CapturedIsone()
    watcher = PublicationWatcher(settings(tmp_path), source, ForecastStore(tmp_path))
    first = watcher.step(NOW_S)
    assert first is not None
    late = NOW_S + (DOCUMENT_HOURS - VIEW_HOURS + 1) * 3600
    second = watcher.step(late)
    assert second is not None
    assert second.forecast.forecast_uid != first.forecast.forecast_uid
    assert second.basis.source_posted_s == first.basis.source_posted_s
    assert second.basis.published_slot_count == 0


def test_watcher_keeps_its_document_when_isone_fails(tmp_path: Path) -> None:
    store = ForecastStore(tmp_path)
    good = PublicationWatcher(settings(tmp_path), CapturedIsone(), store)
    kept = good.step(NOW_S)
    failing = PublicationWatcher(settings(tmp_path), FailingIsone(), store)
    assert failing.step(NOW_S + 3600) is None
    assert failing.kept == kept
    assert store.load_kept() == kept
    # The failed check is tried again soon.
    assert failing.next_check_s == NOW_S + 3600 + EXPECTING_POLL_S


def test_a_document_without_its_basis_is_rebuilt(tmp_path: Path) -> None:
    source = CapturedIsone()
    store = ForecastStore(tmp_path)
    first = PublicationWatcher(settings(tmp_path), source, store).step(NOW_S)
    assert first is not None
    store.basis_path.unlink()
    assert store.load() == first.forecast
    second = PublicationWatcher(settings(tmp_path), source, store).step(NOW_S)
    assert second is not None
    assert second.forecast.forecast_uid != first.forecast.forecast_uid


def test_api_serves_the_view_on_both_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = settings(tmp_path)
    store = ForecastStore(tmp_path)
    client = TestClient(api.create_app(s, store))
    assert client.get("/ping").json() == {"status": "ok"}
    assert client.get("/d1-price/latest-forecast").status_code == 503
    source = CapturedIsone()
    kept = build_forecast(s, source, source.info(), NOW_S)
    store.save(kept)
    served_at = NOW_S + 2 * 3600
    monkeypatch.setattr(api.time, "time", lambda: served_at)
    cut = view(kept.forecast, served_at)
    assert cut is not None
    assert client.get("/d1-price/latest-forecast").json() == cut.to_dict()
    assert client.get(s.ltn_route).json() == cut.to_dict()


def test_a_kept_file_in_another_shape_is_ignored(tmp_path: Path) -> None:
    store = ForecastStore(tmp_path)
    store.path.write_text('{"TypeName": "gw.price.forecast", "Version": "000"}')
    store.basis_path.write_text('{"forecast_uid": "x"}')
    assert store.load() is None
    assert store.load_kept() is None
    kept = PublicationWatcher(settings(tmp_path), CapturedIsone(), store).step(NOW_S)
    assert kept is not None
    assert store.load_kept() == kept
