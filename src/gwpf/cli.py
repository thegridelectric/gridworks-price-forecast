"""gwpf console entry point: `gwpf {rabbit,api,show}`.

The systemd units run the services (`price-rabbit.service` runs
`gwpf rabbit`, `price-api.service` runs `gwpf api`); `gwpf show` prints
the forecast view the API would serve right now, for a check from the
shell.
"""

import argparse
import json
import logging
import time

import dotenv
import uvicorn

from gwpf.config import load_settings
from gwpf.forecast import ForecastStore, view
from gwpf.price_actor import PriceActor


def run_rabbit() -> None:
    actor = PriceActor(load_settings())
    actor.start()
    try:
        while actor.main_loop_running:
            time.sleep(1)
    except KeyboardInterrupt:
        actor.stop()


def run_api() -> None:
    settings = load_settings()
    uvicorn.run(
        "gwpf.api:app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
    )


def run_show() -> None:
    kept = ForecastStore(load_settings().data_dir).load()
    cut = None if kept is None else view(kept, time.time())
    if cut is None:
        raise SystemExit("no price forecast available")
    print(json.dumps(cut.to_dict(), indent=2))


def main(argv: list[str] | None = None) -> None:
    dotenv.load_dotenv(dotenv.find_dotenv())
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="gwpf")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "rabbit", help="watch ISO-NE and broadcast each new forecast"
    )
    subcommands.add_parser(
        "api", help="serve the read façade (loopback; TLS at the proxy)"
    )
    subcommands.add_parser("show", help="print the forecast view served now")
    args = parser.parse_args(argv)
    {"rabbit": run_rabbit, "api": run_api, "show": run_show}[args.command]()
