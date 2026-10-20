"""gwpf console entry point — `gwpf {api,show}`.

`price-api.service` runs `gwpf api`; `gwpf show` prints the forecast
the service would serve right now, for a check from the shell.
"""

import argparse
import json
import logging

import dotenv
import uvicorn

from gwpf.config import load_settings
from gwpf.forecast import ForecastKeeper
from gwpf.isone import IsoneClient


def run_api() -> None:
    settings = load_settings()
    uvicorn.run(
        "gwpf.api:app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
    )


def run_show() -> None:
    settings = load_settings()
    client = IsoneClient(
        settings.isone_user,
        settings.isone_api_pass.get_secret_value(),
        settings.isone_location_id,
    )
    forecast = ForecastKeeper(settings, client).current()
    if forecast is None:
        raise SystemExit("no price forecast available")
    print(json.dumps(forecast.to_dict(), indent=2))


def main(argv: list[str] | None = None) -> None:
    dotenv.load_dotenv(dotenv.find_dotenv())
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="gwpf")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "api", help="serve the read façade (loopback; TLS at the proxy)"
    )
    subcommands.add_parser("show", help="print the forecast the service serves now")
    args = parser.parse_args(argv)
    if args.command == "api":
        run_api()
    else:
        run_show()
