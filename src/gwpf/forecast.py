"""Build one forecast per ISO-NE posting, keep it, and cut views of it.

A forecast document covers DOCUMENT_HOURS from the top of the hour after
it is built. Each hour's price is the ISO-NE day-ahead LMP plus the
tariff's delivery price. The hours ISO-NE has posted are used as they
are, and hours beyond the last posted one repeat the latest posted LMP
at the same local hour of day.

The document is built when ISO-NE posts and its id is minted then. The
view a caller pulls is cut from the kept document: the VIEW_HOURS from
the top of the next hour, under the document's id. A document is longer
than a view so that a view cut a day after the posting is still whole.

The watcher asks ISO-NE what it has posted, often in the window when
tomorrow's prices are expected and hourly otherwise, and builds a new
document when the posting has changed or the kept document can no
longer fill a view.

The kept document is a file in the data dir holding the word's JSON, so
a restart serves it at once. Beside it is the document's basis: the
ISO-NE posting it was built from and how many of its leading hours are
ISO-NE's own.
"""

import json
import logging
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import NamedTuple, Protocol

from gwpf.config import GwpfSettings
from gwpf.isone import HourlyLmp, Publication
from gwpf.sema.base import SemaError
from gwpf.sema.enums import MarketPriceUnit
from gwpf.sema.property_format import UTCSeconds, UUID4Str
from gwpf.sema.types import PriceForecast
from gwpf.tariff import TARIFF_TZ, delivery_price_times1000

DOCUMENT_HOURS = 72
VIEW_HOURS = 48
# A view with fewer hours than this is not served.
MIN_VIEW_HOURS = 12
HOUR_S = 3600
FORECAST_FILE = "price-forecast.json"
BASIS_FILE = "price-forecast-basis.json"

# ISO-NE posts tomorrow's prices around 13:00 on the tariff's wall
# clock. From this time until tomorrow is posted the watcher asks every
# EXPECTING_POLL_S; otherwise every IDLE_POLL_S.
EXPECTING_FROM = time(12, 30)
EXPECTING_POLL_S = 300
IDLE_POLL_S = 3600

logger = logging.getLogger(__name__)


class ForecastBasis(NamedTuple):
    """What one forecast document was built from: the time of the ISO-NE
    posting, and the number of leading slots whose LMP is ISO-NE's own;
    the slots after them repeat by hour of day. No sema word states a
    forecast's basis; a basis word keyed by ForecastUid retires this
    record."""

    forecast_uid: UUID4Str
    source_posted_s: UTCSeconds
    published_slot_count: int


class KeptForecast(NamedTuple):
    """A forecast document with its basis."""

    forecast: PriceForecast
    basis: ForecastBasis


class DayAheadSource(Protocol):
    """What the builder and the watcher need of ISO-NE."""

    def info(self) -> Publication: ...

    def day_ahead(self, day: date) -> list[HourlyLmp]: ...


def next_hour_start(now_s: float) -> UTCSeconds:
    return int(now_s // HOUR_S) * HOUR_S + HOUR_S


def local_date(time_s: float) -> date:
    return datetime.fromtimestamp(time_s, TARIFF_TZ).date()


def times1000(usd_per_mwh: float) -> int:
    return round(usd_per_mwh * 1000)


def extend_by_hour_of_day(
    published: list[HourlyLmp], slot_starts: list[UTCSeconds]
) -> list[HourlyLmp]:
    """A row for each requested hour: the published row where one exists,
    else the latest published row at the same local hour of day."""
    if not published:
        raise ValueError("no published day-ahead prices to forecast from")
    by_start = {row.hour_start_s: row for row in published}
    by_hour_of_day: dict[int, HourlyLmp] = {}
    for row in published:
        by_hour_of_day[datetime.fromtimestamp(row.hour_start_s, TARIFF_TZ).hour] = row
    rows: list[HourlyLmp] = []
    for start in slot_starts:
        if start in by_start:
            rows.append(by_start[start])
        else:
            local_hour = datetime.fromtimestamp(start, TARIFF_TZ).hour
            rows.append(by_hour_of_day.get(local_hour, published[-1]))
    return rows


def published_slot_count(
    published: list[HourlyLmp], slot_starts: list[UTCSeconds]
) -> int:
    """The number of leading slots ISO-NE has a posted price for."""
    posted = {row.hour_start_s for row in published}
    count = 0
    for start in slot_starts:
        if start not in posted:
            break
        count += 1
    return count


def build_forecast(
    settings: GwpfSettings,
    source: DayAheadSource,
    publication: Publication,
    now_s: float,
) -> KeptForecast:
    """A new forecast document from what ISO-NE has posted, starting at
    the top of the next hour."""
    first = next_hour_start(now_s)
    slot_starts = [first + i * HOUR_S for i in range(DOCUMENT_HOURS)]
    last_posted_day = local_date(publication.latest_begin_s)
    day = min(local_date(now_s), last_posted_day)
    published: list[HourlyLmp] = []
    while day <= last_posted_day:
        published += source.day_ahead(day)
        day += timedelta(days=1)
    rows = extend_by_hour_of_day(published, slot_starts)
    forecast = PriceForecast(
        from_g_node_alias=settings.service_alias,
        market_maker_alias=settings.market_maker_alias,
        product_name=settings.product_name,
        forecast_uid=str(uuid.uuid4()),
        created_ms=int(now_s * 1000),
        slot_start_s=slot_starts,
        price_unit=MarketPriceUnit.USDPerMWh,
        price_x1000_list=[
            times1000(row.lmp_usd_per_mwh) + delivery_price_times1000(start)
            for row, start in zip(rows, slot_starts, strict=True)
        ],
    )
    basis = ForecastBasis(
        forecast_uid=forecast.forecast_uid,
        source_posted_s=publication.posted_s,
        published_slot_count=published_slot_count(published, slot_starts),
    )
    return KeptForecast(forecast, basis)


def view(forecast: PriceForecast, now_s: float) -> PriceForecast | None:
    """The forecast's hours from the top of the next hour, VIEW_HOURS at
    most, under the same id; None when fewer than MIN_VIEW_HOURS remain."""
    first = next_hour_start(now_s)
    starts = forecast.slot_start_s
    skip = next((i for i, start in enumerate(starts) if start >= first), len(starts))
    end = min(skip + VIEW_HOURS, len(starts))
    if end - skip < MIN_VIEW_HOURS:
        return None
    return PriceForecast(
        from_g_node_alias=forecast.from_g_node_alias,
        market_maker_alias=forecast.market_maker_alias,
        product_name=forecast.product_name,
        forecast_uid=forecast.forecast_uid,
        created_ms=forecast.created_ms,
        slot_start_s=starts[skip:end],
        price_unit=forecast.price_unit,
        price_x1000_list=forecast.price_x1000_list[skip:end],
    )


class ForecastStore:
    """The kept forecast document and its basis, two files in the data
    dir."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / FORECAST_FILE
        self.basis_path = data_dir / BASIS_FILE

    def load(self) -> PriceForecast | None:
        if not self.path.exists():
            return None
        try:
            return PriceForecast.from_bytes(self.path.read_bytes())
        except (SemaError, ValueError) as e:
            logger.warning("ignoring unreadable forecast file %s: %s", self.path, e)
            return None

    def load_kept(self) -> KeptForecast | None:
        """The document with its basis; None when either is missing or
        the basis is another document's."""
        forecast = self.load()
        if forecast is None or not self.basis_path.exists():
            return None
        try:
            basis = ForecastBasis(**json.loads(self.basis_path.read_text()))
        except (ValueError, TypeError) as e:
            logger.warning("ignoring unreadable basis file %s: %s", self.basis_path, e)
            return None
        if basis.forecast_uid != forecast.forecast_uid:
            return None
        return KeptForecast(forecast, basis)

    def save(self, kept: KeptForecast) -> None:
        """Replace each file in one step, so a reader never sees a partly
        written one. The document goes last: a basis without its
        document is ignored."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        replace(self.basis_path, json.dumps(kept.basis._asdict()).encode())
        replace(self.path, kept.forecast.to_bytes())


def replace(path: Path, content: bytes) -> None:
    scratch = path.with_suffix(".tmp")
    scratch.write_bytes(content)
    scratch.replace(path)


def poll_interval_s(publication: Publication, now_s: float) -> int:
    """Seconds until ISO-NE is next asked what it has posted."""
    local = datetime.fromtimestamp(now_s, TARIFF_TZ)
    expecting_from = datetime.combine(local.date(), EXPECTING_FROM, TARIFF_TZ)
    if local < expecting_from:
        return min(IDLE_POLL_S, int((expecting_from - local).total_seconds()) + 1)
    tomorrow = local.date() + timedelta(days=1)
    if local_date(publication.latest_begin_s) < tomorrow:
        return EXPECTING_POLL_S
    return IDLE_POLL_S


class PublicationWatcher:
    """Asks ISO-NE what it has posted and builds a forecast document when
    the posting is new or the kept document cannot fill a view."""

    def __init__(
        self, settings: GwpfSettings, source: DayAheadSource, store: ForecastStore
    ) -> None:
        self.settings = settings
        self.source = source
        self.store = store
        self.kept: KeptForecast | None = store.load_kept()
        self.next_check_s: float = 0

    def kept_is_current(self, publication: Publication, now_s: float) -> bool:
        if self.kept is None:
            return False
        if self.kept.basis.source_posted_s != publication.posted_s:
            return False
        cut = view(self.kept.forecast, now_s)
        return cut is not None and len(cut.slot_start_s) == VIEW_HOURS

    def step(self, now_s: float) -> KeptForecast | None:
        """Check ISO-NE when a check is due. Returns the new forecast
        document when one was built, else None. A failed call is logged
        and tried again after EXPECTING_POLL_S."""
        if now_s < self.next_check_s:
            return None
        self.next_check_s = now_s + EXPECTING_POLL_S
        try:
            publication = self.source.info()
            if self.kept_is_current(publication, now_s):
                kept = None
            else:
                kept = build_forecast(self.settings, self.source, publication, now_s)
        except Exception as e:
            logger.error("could not check ISO-NE or build a forecast: %s", e)
            return None
        self.next_check_s = now_s + poll_interval_s(publication, now_s)
        if kept is not None:
            self.kept = kept
            self.store.save(kept)
        return kept
