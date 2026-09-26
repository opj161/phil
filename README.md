# Phil the self-improving trader

[![CI](https://github.com/opj161/phil/actions/workflows/ci.yml/badge.svg)](https://github.com/opj161/phil/actions/workflows/ci.yml)

<img src=".github/phil.png" alt="Phil, a groundhog peeking over a rising price chart" width="100" align="left"/>

**Phil is a self-improving trader: an AI agent that trades short-term
prediction markets and rewrites its own strategy and tools as bets
resolve.** Paper trading is the learning engine. Real money runs alongside
it, deliberately small: capped stakes through
[Pearl Connect](https://github.com/valory-xyz/connect), and only in lanes
whose forward record has earned it.

The name honors the man who relived the same day until he'd learned enough
to win it, and the groundhog who makes forecasts.

This is a fork of [bennyjo/phil](https://github.com/bennyjo/phil). v2
(2026-09-26) rebuilt it around what 58 days of v1 journals showed:

- the LLM's own probabilities were slightly worse than the market's
  (875 settled forecasts, Brier delta +0.008);
- mechanical methods (barrier/touch models, de-vigged bookmaker lines,
  counted base rates) matched or beat the market.

## How v2 works

- **Lanes.** A lane is a method with a pricing tool (`config/lanes.json`):
  - `barrier`: price-path and price-level markets on crypto, commodities
    and indices, 3+ days out, priced by a lognormal model with sourced
    implied vol;
  - `devig`: sports vs de-vigged bookmaker consensus from
    [the-odds-api](https://the-odds-api.com);
  - `mention`: say-the-word markets from counted transcript base rates;
  - `explore`: everything else, forecast-only.

  `strategy/tools/lanes.py` routes the scanned market universe into lanes and
  prices it.
- **The agent forecasts; the engine trades.** Every priced market becomes a
  recorded forecast tagged with its lane. `core/ledger.py place
  --forecast-id` then runs `core/decision.py`, the single protected engine
  that replay and real twins also use:
  1. it shrinks the estimate toward the market mid by the lane's weight λ,
     fitted only from outcomes known at that moment;
  2. it walks both outcome books;
  3. it subtracts the market's taker fee;
  4. it buys only when the net edge clears the bar, or logs why not.
- **Self-improvement** is the agent editing its lane tools, series mappings
  and a capped playbook from settled evidence. A daily deep retro audits
  every edit, prunes the playbook, and grades each lane.
- **Real money** follows lanes, not stories. `core/gate.py` judges each
  lane's paper record since registration: 30+ events, a positive
  event-clustered net ROI lower bound, and no single event dominating. The
  operator promotes a PASS to `live`, and only then do $1 real twins run
  through `core/real.py`.

## Honest-simulation rules

- Paper fills walk the live CLOB ask book for the stake (VWAP) and pay the
  market's taker fee (Polymarket: shares × rate × p × (1 − p), per-market
  terms). P&L is net of fees.
- Entry prices are recorded at bet time; resolutions are Polymarket's own.
- Evaluation is point-in-time and event-clustered. Sibling markets count as
  one observation.
- The agent cannot edit the engine (`core/`, `config/`). `loop.sh` reverts
  any attempt, and CI fails any agent commit that touches protected files.
- Caps:
  - $10 per bet and 60 open positions;
  - $10 per event;
  - 15 new positions an hour;
  - no market resolving under 20 minutes out;
  - no entries outside 5¢ to 95¢;
  - shrunk edges above 15¢ are rejected as probable mapping errors.

## Run

```bash
cp .env.example .env         # optional: ODDS_API_KEY for the devig lane
./loop.sh 100000 60          # tick hourly, 24/7 (LIGHT ticks use no LLM)
./loop.sh 1                  # one tick now
python3 core/score.py        # P&L and calibration by lane
python3 core/gate.py         # forward-test verdict per lane
python3 core/replay.py       # point-in-time engine replay over all forecasts
python3 core/test_engine.py  # engine tests (CI runs them)
./loop.sh 1 60 --real        # a tick with real twins via Pearl Connect
```

Requires [Claude Code](https://claude.com/claude-code) (`claude` on your
PATH) and Python 3. Market data needs no API key: it comes from
Polymarket's public gamma/CLOB endpoints, Coinbase, Deribit and Yahoo.

Models are set by environment variables:
- `PHIL_MODEL` for cycles (default `claude-sonnet-5`);
- `PHIL_DEEP_MODEL` for the daily deep retro (default `claude-opus-5-5`).

Every LLM tick's cost is logged to `journal/costs.jsonl`.

## Disclaimer

This is a research experiment in agent self-improvement. Most trading is
simulated. A small real-money leg runs through Pearl Connect only when the
operator deliberately enables it: per-bet and daily stakes are capped in
`config/protected.json`, and the wallet holds only what the operator funds.
Nothing here is financial, investment, or betting advice. Past performance,
paper or real, predicts nothing. Prediction-market trading is restricted or
unlawful in some jurisdictions. Know your own rules before running any of
this with real funds.

## License

[Apache-2.0](LICENSE). The journal and strategy files are part of the
experiment's record and are covered by the same license.
