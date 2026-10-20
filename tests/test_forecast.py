"""The forecast built from a captured ISO-NE day, served through the API."""

from datetime import date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from gwpf.api import create_app
from gwpf.config import GwpfSettings
from gwpf.forecast import FORECAST_HOURS, ForecastKeeper, build_forecast
from gwpf.isone import HourlyLmp, parse_day_ahead
from gwpf.sema.types import StopgapPriceForecast
from gwpf.tariff import TARIFF_TZ

CAPTURE = Path(__file__).parent / "isone-da-keene-2026-10-20.xml"
# 09:10 ET on the captured day, before ISO-NE publishes tomorrow.
NOW_S = int(datetime(2026, 10, 20, 9, 10, tzinfo=TARIFF_TZ).timestamp())


class CapturedIsone:
    """Answers the captured day and nothing for any other."""

    def __init__(self) -> None:
        self.rows = parse_day_ahead(CAPTURE.read_text(), "43790")

    def day_ahead(self, day: date) -> list[HourlyLmp]:
        return self.rows if day == date(2026, 10, 20) else []


class FailingIsone:
    def day_ahead(self, day: date) -> list[HourlyLmp]:
        raise ConnectionError("iso-ne unreachable")


def settings(tmp_path: Path) -> GwpfSettings:
    return GwpfSettings(isone_user="u", isone_api_pass="p", data_dir=tmp_path)


def test_parse_captured_day() -> None:
    rows = parse_day_ahead(CAPTURE.read_text(), "43790")
    assert len(rows) == 24
    assert rows[0].hour_start_s == int(
        datetime(2026, 10, 20, 0, tzinfo=TARIFF_TZ).timestamp()
    )
    assert rows[0].lmp_usd_per_mwh == 29.24


def test_forecast_shape_and_hour_of_day_extension(tmp_path: Path) -> None:
    forecast = build_forecast(settings(tmp_path), CapturedIsone(), NOW_S)
    assert len(forecast.hour_start_s) == FORECAST_HOURS
    assert forecast.hour_start_s[0] == int(
        datetime(2026, 10, 20, 10, tzinfo=TARIFF_TZ).timestamp()
    )
    rows = {r.hour_start_s: r.lmp_usd_per_mwh for r in CapturedIsone().rows}
    # Published hours are served as they are.
    assert forecast.lmp_list[0] == rows[forecast.hour_start_s[0]]
    # Tomorrow 10:00 repeats today 10:00.
    assert forecast.lmp_list[24] == forecast.lmp_list[0]
    # The word's own axioms accept it, and it round-trips.
    assert StopgapPriceForecast.from_bytes(forecast.to_bytes()) == forecast


def test_keeper_serves_kept_forecast_when_isone_fails(tmp_path: Path) -> None:
    good = ForecastKeeper(settings(tmp_path), CapturedIsone())
    served = good.current(NOW_S)
    assert served is not None
    failing = ForecastKeeper(settings(tmp_path), FailingIsone())
    assert failing.forecast == served
    # An hour on, the kept forecast is served from its next hour.
    later = failing.current(NOW_S + 3600)
    assert later is not None
    assert later.hour_start_s == served.hour_start_s[1:]
    assert later.lmp_list == served.lmp_list[1:]
    assert later.price_uid == served.price_uid
    # Once too little of it remains, nothing is served.
    assert failing.current(served.hour_start_s[-12] + 1) is None


def test_api_serves_wire_form_on_both_routes(tmp_path: Path) -> None:
    s = settings(tmp_path)
    keeper = ForecastKeeper(s, CapturedIsone())
    keeper.current(NOW_S)
    keeper.client = FailingIsone()  # type: ignore[assignment]
    client = TestClient(create_app(s, keeper))
    assert client.get("/ping").json() == {"status": "ok"}
    expected = keeper.forecast.to_dict() if keeper.forecast else None
    assert client.get("/hw1-isone-price/latest-forecast").json() == expected
    assert client.get(s.ltn_route).json() == expected
