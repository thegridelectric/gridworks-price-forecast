"""Settings for gridworks-price-forecast."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from gwpf.sema.property_format import LeftRightDot


class GwpfSettings(BaseSettings):
    """Reads from env (GWPF_*) and/or a `.env` file at the repo root."""

    # The service's registered GNode alias; the forecast's FromGNodeAlias.
    service_alias: LeftRightDot = "hw1.isone.price"

    # The pricing node the forecast covers and its ISO-NE location id.
    p_node_alias: LeftRightDot = "hw1.isone.ver.keene"
    isone_location_id: str = "43790"

    # The delivery tariff the DistList prices are drawn from.
    tariff_alias: LeftRightDot = "versant.a1.home.eco.bonus"

    # ISO-NE web services (https://webservices.iso-ne.com), basic auth.
    isone_user: str
    isone_api_pass: SecretStr

    # The last good forecast is kept here so a restart never waits on
    # ISO-NE and a failed fetch leaves the last forecast in place.
    data_dir: Path = Path.home() / ".local" / "share" / "gridworks" / "price-forecast"

    # The LTN fetches the forecast at this path (the party segment is a
    # legacy alias the LTN has hard-coded, kept so no LTN restarts).
    ltn_route: str = "/hw1-isone-me-versant-keene-ps/gw0-price-forecast"

    # The read façade binds loopback; TLS is the fronting proxy's job.
    api_host: str = "127.0.0.1"
    api_port: int = 8532

    model_config = SettingsConfigDict(
        env_prefix="GWPF_",
        env_nested_delimiter="__",
        extra="ignore",
    )


def load_settings() -> GwpfSettings:
    """Settings from the environment; the ISO-NE account has no default."""
    return GwpfSettings()  # type: ignore[call-arg]
