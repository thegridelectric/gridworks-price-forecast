# gridworks-price-forecast

The price-forecast service is the fleet's one source of forward
electricity prices. For each coming hour it forecasts the price a
MarketMaker will publish for one market: the whole price a bidder in
that market faces. The LeafTransactiveNode actors read it to run their
forward-looking optimizers, so a missing forecast is a plan not made.

Today an hour's forecast price is ISO-NE's day-ahead locational marginal
price for Keene Rd (location 43790) plus the Versant Rate A-1 "Home Eco
Rate with Bonus Meter" total-delivery price (`src/gwpf/tariff.py` has
the table and the windows). The hours ISO-NE has posted are used as they
are, and hours beyond the last posted one repeat the latest posted LMP
at the same hour of day.

The service builds one forecast per ISO-NE posting. It asks ISO-NE what
has been posted, every five minutes from 12:30 Eastern until tomorrow's
prices appear and hourly otherwise, and builds a 72-hour forecast with a
new id when the posting changes. That forecast is broadcast once and
kept on disk, with a note beside it of the ISO-NE posting it was built
from and how many of its hours are ISO-NE's own. What a caller pulls over HTTP is the kept forecast's next
48 hours under the same id, so every pulled value is in the broadcast
forecast with that id.

## What it speaks

The one boundary is a Sema word, from the versioned vocabulary of
JSON-Schema contracts for GridWorks boundaries, canonical at
[`thegridelectric/sema`](https://github.com/thegridelectric/sema):
`gw.price.forecast`, listed in `src/gwpf/sema_seed_request.yaml`.

Broadcast on RabbitMQ by the actor, once per forecast, on the radio
channel named for the market (`e.<product>.<MarketMaker alias>`).

Served over HTTP, read-only, the response byte-identical to the word's
wire form:

- `/<hyphenated service alias>/latest-forecast`, the house pattern.
- The legacy path the LTN calls, set by `GWPF_LTN_ROUTE`.
- `/ping`.

Interactive docs at `/docs` once running.

## Running

Two processes share the data dir. `gwpf rabbit` is the actor: it watches
ISO-NE, writes the kept forecast and broadcasts it. `gwpf api` serves
views of the kept forecast and never calls ISO-NE.

```
cp template.env .env     # fill in the ISO-NE account
uv sync --all-groups
uv run gwpf rabbit       # watch ISO-NE, keep and broadcast forecasts
uv run gwpf api          # serve on 127.0.0.1:8532
uv run gwpf show         # print the forecast view served now
./ci.sh                  # what CI runs: lint, format, tests
```

The defaults are a dev run in the `d1` universe on a local broker, with
the GNode record in `scripts/dev-g.node.gt.json`.

`scripts/regen_sema_snapshot.sh` regenerates the vendored Sema snapshot
under `src/gwpf/sema` from a sibling `../sema` checkout; never edit the
snapshot by hand; `ALLOW_STAGED=1` admits words still in staging.
`service/` has the systemd units and the shell aliases a box login uses.
