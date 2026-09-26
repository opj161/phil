# Trading Cycle Procedure (Phil v2)

You are the trading agent. Follow this procedure once, then stop. Work from
this directory. `loop.sh` has already synced with origin and will push after
you exit: never fetch, pull or push yourself.

## Hard rules

- NEVER edit `core/`, `config/`, `.github/` or the operator's top-level files
  (`CYCLE.md`, `DEEP.md`, `REAL.md`, `loop.sh`, `CLAUDE.md`, `LICENSE`,
  `README.md`, `.gitignore`). If a protected rule looks wrong, append the
  evidence to `journal/proposals.md` instead. CI fails any non-`operator:`
  commit that touches them.
- You may edit `strategy/`, write `journal/retros/` and use `work/`
  (gitignored scratch). Only `core/` scripts write the ledgers.
- `est_prob` is your honest probability for the named outcome, produced by the
  lane's method. Never tune it to get a trade: the engine measures every lane
  against the market and weighs it by its own record, so a gamed estimate
  only corrupts the lane's weight.
- Every strategy edit cites settled evidence (bets, forecasts, retro
  findings). No speculative rewrites.

## How Phil v2 trades

- **Lanes** (`config/lanes.json`) are methods with a pricing tool:
  `barrier` (crypto/commodity/index price-path and level markets, 3+ days
  out), `barrier_equity` (the same for single stocks and ETFs, with its own
  λ), `devig` (sports vs de-vigged bookmaker consensus) and `mention`
  (say-the-word base rates) trade on paper. `explore` (anything else) and
  `latency` are forecast-only.
- **You forecast; the engine trades.** `core/ledger.py place --forecast-id`
  refetches both books and the market's taker fee, shrinks your estimate
  toward the mid by the lane's weight `lam`, walks the ask book and buys the
  side whose net edge (after fee) clears `min_net_edge`, or says why not. A
  skip is the normal outcome, not an error.
- `lam` is fitted per lane from settled forecasts known before now. Below 20
  settled events a paper lane trades at the cold-start prior 0.5, so its
  forward record can begin. After that the fit rules, and a fitted `lam` of
  0 stops the lane.
- Real money follows only lanes that pass `core/gate.py` (an operator act).

## Procedure

1. **Settle**: `python3 core/resolve.py`
2. **Score**: `python3 core/score.py --skip-mtm` and `python3 core/gate.py`.
   Read the by-method table first.
3. **Retro** (only if bets or forecasts settled since the last retro): write
   `journal/retros/RETRO-<UTC YYYYMMDD-HHMM>.md`, short. For each settled bet:
   estimate wrong, mapping wrong, fill/fee, or variance? Grade settled
   forecasts by lane. Encode concrete lessons where they act:
   - a pricing or parsing error: fix `strategy/tools/lanes.py` or
     `strategy/tools/touch.py`;
   - a resolution-rule mismatch: fix or remove the series in
     `strategy/lane-maps.json`;
   - a judgment rule: `strategy/playbook.md`, which stays under 40 KB.
     Replace or merge rules; never append a diary.

   Mind small n: one event is an anecdote. Commit:
   `git add -A && git commit -m "retro: <one-line lesson>"`.
4. **Lanes**:
   ```
   python3 core/scan.py --hours 720 --limit 800 2>work/scan.err \
     | python3 strategy/tools/lanes.py run --odds > work/lanes.jsonl
   python3 strategy/tools/lanes.py summary < work/lanes.jsonl
   python3 strategy/tools/lanes.py plan --verified-only < work/lanes.jsonl > work/plan.jsonl
   ```
   `--odds` spends one the-odds-api credit on the sport with the most games
   in the next 36h. `core/odds.py` enforces the monthly budget; if it reports
   the key missing or the budget spent, rerun without `--odds` and note it.
   Read `summary`'s unpriced reasons. A recurring reason that loses real
   candidates, such as an unmapped league or underlying, is a tool fix for
   step 3 of a later cycle, not something to price by hand.
5. **Verify new series** (the judgment step: this is where mistakes cost
   money). `plan` prints `unverified_series` on stderr. For up to 6 of them
   per cycle, largest markets first:
   - Read one market's rules: `python3 core/pmapi.py rules <market_id>`
     (`python3 core/pmapi.py book <market_id>` shows the books).
   - Check that the model's inputs match the resolution: price source, window
     and timezone, touch vs close, trading-hours rules, and which outcome.
     For devig, check the teams, the date, and whether a draw is possible.
   - For `barrier_equity`, also check for an earnings release inside the
     window (WebSearch). If there is one, add the series to `excluded` with
     the reason and an `until` date instead: realized vol misses earnings
     jumps.
   - If the rules match, add the series to `strategy/lane-maps.json`
     `series` (source, window, mode, checked_at). If they don't, add it to
     `excluded` and fix the tool in a later retro.

   Then rerun the `plan --verified-only` command. `plan` holds back rows
   with a `warn` (a large model-vs-mid gap). Check each one by hand: if the
   inputs are right, record it with the single-row command below and
   `--confirm-extreme` when forecast.py asks for it.
6. **Record and place** (mechanical):
   ```
   python3 core/forecast.py record-batch < work/plan.jsonl
   python3 core/ledger.py place-batch --strategy-rev $(git rev-parse --short HEAD) < work/plan.jsonl
   ```
   `record-batch` records or supersedes every `record`/`supersede` row with
   the same checks as a single record. `place-batch` runs the engine on
   those rows and on `place` rows (live forecasts whose model price still
   stands). The engine decides. Its skip reasons (`wide_spread`,
   `edge_below_min`, `lambda_zero`, ...) are data for the retro, not
   problems to work around.
   - `est_prob` IS the model's number. The batch path records exactly that.
     Deviate only for a specific, sourced fact the model cannot see (a
     confirmed injury, a verified event already in the window): record that
     row by hand with `shade: <fact>` in the note.
   - Single row (for warn rows, mention and explore):
     ```
     python3 core/forecast.py record --market-id <id> --outcome "<outcome>" \
       --est-prob <p> --method <lane> --category <category> \
       --note "<inputs or base-rate counts>" --strategy-rev $(git rev-parse --short HEAD)
     python3 core/ledger.py place --forecast-id <id> --rationale "<one line>" \
       --strategy-rev $(git rev-parse --short HEAD)
     ```
   - **mention**: for at most 2 events per cycle, count base rates as the
     playbook describes, then record with `--method mention` and place.
   - **explore**: at most 2 other forecasts per cycle, `--method explore`.
     These are never traded; they are how a new lane gets discovered.
7. **Pace**: set `strategy/schedule.json` `next_full_cycle_after` (ISO UTC)
   and `reason`. The default is about 3h. Come back sooner when priced
   markets close or games start within the next hours, and later overnight
   when nothing moves. `loop.sh` settles without you between FULL cycles.
8. **Log**: append one line to `journal/cycles.log`:
   `<UTC ISO> cycle done: settled N, forecasts F, placed M, cash $X (FULL, <lanes priced/unpriced, notable skips>)`
   Take `cash` from `python3 core/ledger.py status`. A TRIGGERED tick writes
   `(TRIGGERED: <keys>, FULL` instead of `(FULL`.
9. **Commit**: `git add -A && git commit -m "cycle: <UTC YYYYMMDD-HHMM> forecasts F placed M settled N"`.
   If HEAD is detached, run `git checkout -B main HEAD` first. Do not push.
