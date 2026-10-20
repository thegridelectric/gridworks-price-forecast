# gridworks-price-forecast

The price-forecast service is the fleet's one source of forward
electricity prices: for each of the next 48 hours, the energy price at
the pricing node the houses settle against and the delivery price under
the tariff the houses are on. The LeafTransactiveNode actors read it to
run their forward-looking optimizers, so a missing forecast is a plan
not made.

Today the forecast is the stopgap one. Energy is ISO-NE's day-ahead
hourly locational marginal price for Keene Rd (location 43790): the
hours ISO-NE has published are served as they are, and hours beyond the
last published day repeat that day by hour of day. Delivery is the
Versant Rate A-1 "Home Eco Rate with Bonus Meter" total-delivery price
for each hour (`src/gwpf/tariff.py` has the table and the windows). The
service keeps the last good forecast on disk, so a restart serves at
once and an ISO-NE outage leaves the last forecast in place until its
first hour has passed.

## What it speaks

The one boundary is a Sema word, from the versioned vocabulary of
JSON-Schema contracts for GridWorks boundaries, canonical at
[`thegridelectric/sema`](https://github.com/thegridelectric/sema):
`gw.stopgap.price.forecast`, listed with its version in
`src/gwpf/sema_seed_request.yaml`. The word is a stopgap, named so, and
is replaced when the service's own forecast word exists.

Served over HTTP, read-only, the response byte-identical to the word's
wire form:

- `/<hyphenated service alias>/latest-forecast`, the house pattern.
- The legacy path the LTN calls, set by `GWPF_LTN_ROUTE`.
- `/ping`.

Interactive docs at `/docs` once running.

## Running

```
cp template.env .env     # fill in the ISO-NE account
uv sync --all-groups
uv run gwpf show         # print the forecast the service would serve now
uv run gwpf api          # serve on 127.0.0.1:8532
./ci.sh                  # what CI runs: lint, format, tests
```

`scripts/regen_sema_snapshot.sh` regenerates the vendored Sema snapshot
under `src/gwpf/sema` from a sibling `../sema` checkout; never edit the
snapshot by hand. `service/` has the systemd unit and the shell aliases
a box login uses.
