"""Build the forecast the service serves and keep the last good one.

The forecast is the 48 hours from the top of the next hour. Energy is
ISO-NE day-ahead LMP: the hours ISO-NE has published are used as they
are, and hours beyond the last published day repeat the last published
day by hour of day, the same estimate the hand-built forecasts used.
Delivery is the tariff's price for each hour.

The last good forecast is written to the data dir as the word's JSON,
so a restart serves it at once and a failed ISO-NE call leaves it in
place with its past hours trimmed, until fewer than MIN_KEPT_HOURS of
it remain.
"""

import logging
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from gwpf.config import GwpfSettings
from gwpf.isone import HourlyLmp, IsoneClient
from gwpf.sema.property_format import UTCSeconds
from gwpf.sema.types import StopgapPriceForecast
from gwpf.tariff import TARIFF_TZ, delivery_usd_per_mwh

FORECAST_HOURS = 48
HOUR_S = 3600
FORECAST_FILE = "stopgap-price-forecast.json"
# A kept forecast with fewer future hours than this is not served.
MIN_KEPT_HOURS = 12

logger = logging.getLogger(__name__)


def next_hour_start(now_s: float) -> UTCSeconds:
    return int(now_s // HOUR_S) * HOUR_S + HOUR_S


def extend_by_hour_of_day(
    published: list[HourlyLmp], hour_starts: list[UTCSeconds]
) -> list[float]:
    """LMP for each requested hour: the published value where one exists,
    else the latest published value at the same local hour of day."""
    by_start = {row.hour_start_s: row.lmp_usd_per_mwh for row in published}
    by_hour_of_day: dict[int, float] = {}
    for row in published:
        by_hour_of_day[datetime.fromtimestamp(row.hour_start_s, TARIFF_TZ).hour] = (
            row.lmp_usd_per_mwh
        )
    if not by_hour_of_day:
        raise ValueError("no published day-ahead prices to forecast from")
    values: list[float] = []
    for start in hour_starts:
        if start in by_start:
            values.append(by_start[start])
        else:
            local_hour = datetime.fromtimestamp(start, TARIFF_TZ).hour
            values.append(by_hour_of_day.get(local_hour, published[-1].lmp_usd_per_mwh))
    return values


def build_forecast(
    settings: GwpfSettings, client: IsoneClient, now_s: float
) -> StopgapPriceForecast:
    """Fetch what ISO-NE has published for today and tomorrow and lay the
    tariff over the next 48 hours."""
    first = next_hour_start(now_s)
    hour_starts = [first + i * HOUR_S for i in range(FORECAST_HOURS)]
    today: date = datetime.fromtimestamp(now_s, TARIFF_TZ).date()
    published = client.day_ahead(today) + client.day_ahead(today + timedelta(days=1))
    return StopgapPriceForecast(
        from_g_node_alias=settings.service_alias,
        p_node_alias=settings.p_node_alias,
        tariff_alias=settings.tariff_alias,
        hour_start_s=hour_starts,
        lmp_list=extend_by_hour_of_day(published, hour_starts),
        dist_list=[delivery_usd_per_mwh(start) for start in hour_starts],
        price_uid=str(uuid.uuid4()),
        forecast_created_s=int(now_s),
    )


class ForecastKeeper:
    """The forecast the service serves, refreshed hourly and kept on disk."""

    def __init__(self, settings: GwpfSettings, client: IsoneClient) -> None:
        self.settings = settings
        self.client = client
        self.path: Path = settings.data_dir / FORECAST_FILE
        self.forecast: StopgapPriceForecast | None = self.load()

    def load(self) -> StopgapPriceForecast | None:
        if not self.path.exists():
            return None
        try:
            return StopgapPriceForecast.from_bytes(self.path.read_bytes())
        except ValueError as e:
            logger.warning("ignoring unreadable forecast file %s: %s", self.path, e)
            return None

    def save(self, forecast: StopgapPriceForecast) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(forecast.to_bytes())

    def fresh(self, now_s: float) -> bool:
        """True when the kept forecast starts at the next hour."""
        return self.forecast is not None and self.forecast.hour_start_s[
            0
        ] == next_hour_start(now_s)

    def current(self, now_s: float | None = None) -> StopgapPriceForecast | None:
        """The forecast for now, rebuilt when the hour has moved on. When
        ISO-NE cannot be reached, the kept forecast with its past hours
        trimmed off, as long as enough of it remains."""
        now_s = time.time() if now_s is None else now_s
        if self.fresh(now_s):
            return self.forecast
        try:
            forecast = build_forecast(self.settings, self.client, now_s)
        except Exception as e:
            logger.error("could not build a forecast: %s", e)
        else:
            self.forecast = forecast
            self.save(forecast)
            return forecast
        if self.forecast is None:
            return None
        return trimmed_to_future(self.forecast, now_s)


def trimmed_to_future(
    forecast: StopgapPriceForecast, now_s: float
) -> StopgapPriceForecast | None:
    """The forecast from the next hour on, or None when fewer than
    MIN_KEPT_HOURS of it remain."""
    first = next_hour_start(now_s)
    keep = [i for i, start in enumerate(forecast.hour_start_s) if start >= first]
    if len(keep) < MIN_KEPT_HOURS:
        return None
    if len(keep) == len(forecast.hour_start_s):
        return forecast
    return StopgapPriceForecast(
        from_g_node_alias=forecast.from_g_node_alias,
        p_node_alias=forecast.p_node_alias,
        tariff_alias=forecast.tariff_alias,
        hour_start_s=[forecast.hour_start_s[i] for i in keep],
        lmp_list=[forecast.lmp_list[i] for i in keep],
        dist_list=[forecast.dist_list[i] for i in keep],
        price_uid=forecast.price_uid,
        forecast_created_s=forecast.forecast_created_s,
    )
