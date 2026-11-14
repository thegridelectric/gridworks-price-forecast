"""Settings for gridworks-price-forecast."""

from pathlib import Path

from gwbase.config import GNodeSettings
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from gwpf.sema.enums import MarketProductName
from gwpf.sema.property_format import LeftRightDot


class GwpfSettings(GNodeSettings):
    """Reads from env (GWPF_*) and/or a `.env` file at the repo root.

    Inherits `rabbit`, `g_node_path`, `log_level` and the rest from
    `GNodeSettings`. `service_alias` MUST match the g.node.gt.json Alias;
    `GridworksActor` enforces the binding at boot.
    """

    service_alias: LeftRightDot = "d1.price"
    service_name: str = "price-forecast"  # XDG path segment for logs/state

    # The market the forecast is for: its MarketMaker and product. The
    # ISO-NE location is the node that MarketMaker prices.
    market_maker_alias: LeftRightDot = "d1.isone.me.versant.keene"
    product_name: MarketProductName = MarketProductName.rt60gate5
    isone_location_id: str = "43790"

    # ISO-NE web services (https://webservices.iso-ne.com), basic auth.
    isone_user: str
    isone_api_pass: SecretStr

    # The kept forecast document: written by the actor, read by the API.
    data_dir: Path = Path.home() / ".local" / "share" / "gridworks" / "price-forecast"

    # The LTN fetches the forecast at this path (the party segment is a
    # legacy alias the LTN has hard-coded, kept so no LTN restarts).
    ltn_route: str = "/hw1-isone-me-versant-keene-ps/gw0-price-forecast"

    # The read façade binds loopback; TLS is the fronting proxy's job.
    api_host: str = "127.0.0.1"
    api_port: int = 8532

    # Control-plane participants, required by GridworksActor.
    my_super_alias: str = "d1.super"
    my_time_coordinator_alias: str = "d1.time"

    model_config = SettingsConfigDict(
        env_prefix="GWPF_",
        env_nested_delimiter="__",
        extra="ignore",
    )


def load_settings() -> GwpfSettings:
    """Settings from the environment; the ISO-NE account has no default."""
    return GwpfSettings()  # type: ignore[call-arg]
