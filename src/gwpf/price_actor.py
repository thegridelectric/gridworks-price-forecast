"""PriceActor: watches ISO-NE and broadcasts each new forecast document.

The actor's loop steps the publication watcher. When the watcher builds
a forecast document the actor broadcasts it once, on the radio channel
named for the forecast's market. The watcher has already written the
document to the data dir, where the read API finds it.
"""

import json
import threading
import time

from gwbase.gridworks_actor import GridworksActor
from gwbase.sema.enums import GwGNodeClass
from gwbase.sema.types.gridworks_header import GridworksHeader
from gwbase.transport_encoding import RoutingEnvelope

from gwpf.config import GwpfSettings
from gwpf.forecast import DayAheadSource, ForecastStore, PublicationWatcher
from gwpf.isone import IsoneClient
from gwpf.sema.types import PriceForecast

TICK_S = 5


def market_name(forecast: PriceForecast) -> str:
    """The forecast's market: the MarketSlotName of any of its slots
    without the slot start."""
    return f"e.{forecast.product_name.value}.{forecast.market_maker_alias}"


class PriceActor(GridworksActor):
    """Broadcasts a `gw.price.forecast` for each ISO-NE posting."""

    def __init__(
        self, settings: GwpfSettings, *, source: DayAheadSource | None = None
    ) -> None:
        super().__init__(
            settings=settings,
            g_node_class=GwGNodeClass.PriceForecastService,
            my_super_alias=settings.my_super_alias,
            my_time_coordinator_alias=settings.my_time_coordinator_alias,
        )
        self.settings: GwpfSettings = settings
        self.watcher = PublicationWatcher(
            settings,
            source
            or IsoneClient(
                settings.isone_user,
                settings.isone_api_pass.get_secret_value(),
                settings.isone_location_id,
            ),
            ForecastStore(settings.data_dir),
        )
        self.main_thread = threading.Thread(target=self.main, daemon=True)

    def local_start(self) -> None:
        self._main_loop_running = True
        self.main_thread.start()

    def local_stop(self) -> None:
        self._main_loop_running = False
        self.main_thread.join()

    def process_message(
        self,
        *,
        envelope: RoutingEnvelope,
        body: bytes,
        header: GridworksHeader | None,
    ) -> None:
        self.logger.debug(
            "Ignored unexpected %s from %s", envelope.type_name, envelope.from_alias
        )

    def main(self) -> None:
        while self._main_loop_running:
            try:
                kept = self.watcher.step(time.time())
                if kept is not None:
                    self.publish(kept.forecast)
            except Exception:  # noqa: BLE001 -- the loop must survive anything
                self.logger.exception("watcher step failed")
            time.sleep(TICK_S)

    def publish(self, forecast: PriceForecast) -> None:
        envelope = self.broadcast_envelope(
            type_name=forecast.type_name, radio_channel=market_name(forecast)
        )
        self.send(
            envelope=envelope, body=json.dumps(forecast.to_dict()).encode("utf-8")
        )
        self.logger.info(
            "published %s forecast %s", envelope.routing_key, forecast.forecast_uid
        )
