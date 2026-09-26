# Phil (self-improving trader), v2

A self-improving trading agent for short-term Polymarket markets. `loop.sh`
ticks hourly on this machine. A tick either:
- settles only, with no LLM; or
- runs `CYCLE.md` headless: settle → score → retro → lane pricing →
  forecast → engine-decided paper bets.

Once a day it runs `DEEP.md`, the audit and pruning retro, on a stronger
model.

## Layout

- `core/` + `config/` — PROTECTED, operator-owned. The agent never edits
  these; `loop.sh` reverts any such change and CI fails agent commits that
  touch them.
  - `core/decision.py` is the one decision engine behind paper placement,
    replay and real twins. It fits the market-shrinkage weight λ per lane
    from outcomes known at decision time. It trades on net edge, after VWAP
    and the market's taker fee.
  - `core/ledger.py place --forecast-id` is the only way into a bet.
  - `core/replay.py` is the point-in-time engine replay.
  - `core/gate.py` is the per-lane forward test that decides real-money
    eligibility.
  - `core/test_engine.py` holds the engine tests; CI runs them.
  - `config/lanes.json` is the lane registry: methods, shape regexes, status
    `forecast_only|paper|live`, and gate criteria.
  - `config/protected.json` holds the caps and the engine bounds.
- Also operator-owned: `CYCLE.md`, `DEEP.md`, `REAL.md`, `loop.sh`, the
  top-level docs, `LICENSE`, `.github/`. Human commits to protected paths MUST
  use the `operator:` message prefix, or CI's boundary guard fails the push.
- `strategy/` — the agent's own:
  - `playbook.md` (active rules, capped at 50 KB by CI);
  - `risk.json` (stake and min_net_edge knobs inside the protected bounds);
  - `tools/lanes.py` (lane router and pricers: the main self-improvement
    surface), `tools/touch.py`, `tools/devig.py`;
  - `lane-maps.json` (verified resolution mappings);
  - `discovery.py` (scan queries);
  - `schedule.json` (pacing);
  - `watchlist.json` (watch triggers).
- `journal/` — the ledgers are written only by core:
  - `ledger.jsonl`, `forecasts.jsonl`, `real-ledger.jsonl`;
  - `decisions.jsonl` — every engine verdict;
  - `costs.jsonl` — LLM cost per tick;
  - retros, the cycle log, `proposals.md` (agent → operator asks), and
    `operator-notes.md`;
  - `journal/archive/` — the pre-v2 playbook, proposals, schedule and funnel.

## Purpose

Paper is the learning engine. Profitability is judged per lane by forward
net P&L after fees, clustered by event. Real execution runs only on this
machine via `./loop.sh --real`: engine-placed paper bets in lanes that are
`live` (after a `core/gate.py` PASS and an operator commit) get a $1 real
twin on Polymarket through Pearl Connect.

## Real execution (operator machine only)

- Env: `PEARL_CONNECT_STORE` = Pearl Connect workspace dir (contains
  `.mcp.json`); optional `CONNECT_POLYMARKET_VENV` (default
  `~/.cache/connect-polymarket/venv`).
- `core/real.py` (protected) is the only code that touches funds. It
  enforces the `real` caps block and lane gating, and is the sole writer of
  `journal/real-ledger.jsonl`.
- `real_trading_enabled` is currently false. Enabling it and listing lanes in
  `real.allowed_lanes` are operator acts, and `core/validate.py` checks both:
  the ceilings, and that every listed lane is live.
- REAL.md is appended to the cycle prompt only in real mode. `loop.sh`
  downgrades to paper with a warning if the signer isn't ready.
