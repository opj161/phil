#!/usr/bin/env python3
"""Repo integrity tripwires — run by CI on every push. Offline, no network.

PROTECTED CORE — the trading agent must not edit files under core/.

Checks that an unattended cycle cannot have left the repo broken or unsafe:

  - config/protected.json parses; its caps, the decision-engine bounds and,
    when real trading is enabled, the real caps block sit under hard ceilings
    and real.allowed_lanes names only live lanes
  - config/lanes.json is a well-formed lane registry
  - strategy/risk.json and strategy/schedule.json parse and stay inside the
    protected bounds
  - strategy/playbook.md stays under its size cap (the playbook is active
    judgment, not an evidence log: it grew to 432 KB by 2026-09-26)
  - journal/ledger.jsonl and journal/forecasts.jsonl rows are well-formed
    and every bet respects the caps
  - every Python file under core/ and strategy/ still compiles

Usage: python3 core/validate.py
"""
import datetime as dt
import json
import pathlib
import py_compile
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

LEDGER_REQUIRED = {
    "id", "ts", "market_id", "question", "outcome", "token_id",
    "entry_price", "est_prob", "stake_usd", "status",
}
ENGINE_BET_REQUIRED = {"forecast_id", "method", "engine_rev", "fee_usd", "net_edge", "lam"}
LEDGER_STATUSES = {"open", "won", "lost", "void"}

FORECAST_REQUIRED = {
    "id", "ts", "market_id", "question", "outcome", "token_id",
    "est_prob", "market_prob_at_record", "category", "skip_reason", "status",
}
LANE_STATUSES = {"forecast_only", "paper", "live"}

REAL_HARD_CEILINGS = {"max_stake_usd": 2.0, "daily_stake_cap_usd": 10.0,
                      "max_open_positions": 20}
# (field, low, high): the engine bounds the operator may set, and no further.
ENGINE_BOUNDS = [
    ("min_net_edge_floor", 0.01, 0.5), ("max_net_edge", 0.05, 0.5),
    ("max_spread", 0.005, 0.2),
    ("min_price", 0.01, 0.5), ("max_price", 0.5, 0.99),
    ("max_stake_per_event_usd", 1, 100), ("max_new_positions_per_hour", 1, 60),
    ("max_vwap_slippage", 0.0, 0.05), ("lambda_min_events", 10, 1000),
    ("lambda_shrink_k", 0, 1000), ("lambda_prior_paper", 0.0, 1.0),
    ("legacy_known_lag_hours", 0, 168),
]
PLAYBOOK_MAX_BYTES = 50_000

errors = []


def err(msg):
    errors.append(msg)


def load_json(relpath):
    path = ROOT / relpath
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        err(f"{relpath}: missing")
    except json.JSONDecodeError as e:
        err(f"{relpath}: invalid JSON — {e}")
    return None


def check_iso_z(relpath, field, value):
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        err(f"{relpath}: {field} is not a YYYY-MM-DDTHH:MM:SSZ timestamp: {value!r}")


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


lanes_cfg = load_json("config/lanes.json")
lanes = {}
if lanes_cfg:
    lanes = lanes_cfg.get("lanes") or {}
    if not lanes:
        err("config/lanes.json: no lanes")
    for name, spec in lanes.items():
        if spec.get("status") not in LANE_STATUSES:
            err(f"config/lanes.json: lane {name} status {spec.get('status')!r} "
                f"not in {sorted(LANE_STATUSES)}")
        check_iso_z("config/lanes.json", f"{name}.registered_at", spec.get("registered_at"))
        rx = spec.get("shape_regex")
        if rx is not None:
            try:
                re.compile(rx)
            except re.error as e:
                err(f"config/lanes.json: lane {name} shape_regex does not compile — {e}")
    gate = lanes_cfg.get("gate") or {}
    for field in ("min_events", "min_lcb_net_roi", "max_event_share", "kill_after_events"):
        if not is_num(gate.get(field)):
            err(f"config/lanes.json: gate.{field} missing or not numeric")

protected = load_json("config/protected.json")
if protected:
    for field in ("sim_bankroll_usd", "max_stake_usd", "max_open_positions",
                  "min_minutes_to_resolution", "max_entry_price", "min_entry_price"):
        if not is_num(protected.get(field)):
            err(f"config/protected.json: {field} missing or not numeric")
    engine = protected.get("engine")
    if not isinstance(engine, dict):
        err("config/protected.json: the 'engine' block is missing (core/decision.py needs it)")
    else:
        for field, low, high in ENGINE_BOUNDS:
            v = engine.get(field)
            if not is_num(v):
                err(f"config/protected.json: engine.{field} missing or not numeric")
            elif not low <= v <= high:
                err(f"config/protected.json: engine.{field} = {v} outside [{low}, {high}]")
    if protected.get("real_trading_enabled") not in (True, False):
        err("config/protected.json: real_trading_enabled must be a boolean")
    real = protected.get("real")
    if protected.get("real_trading_enabled") is True and not isinstance(real, dict):
        err("config/protected.json: real_trading_enabled is true but the 'real' caps "
            "block is missing — real mode without caps is never allowed")
    if isinstance(real, dict):
        for field, ceiling in REAL_HARD_CEILINGS.items():
            v = real.get(field)
            if not is_num(v) or v <= 0:
                err(f"config/protected.json: real.{field} missing or not a positive number")
            elif v > ceiling:
                err(f"config/protected.json: real.{field} = {v} exceeds the hard ceiling "
                    f"{ceiling} (raising it requires editing protected core, deliberately)")
        allowed = real.get("allowed_lanes")
        if not isinstance(allowed, list):
            err("config/protected.json: real.allowed_lanes must be a list")
        else:
            for lane in allowed:
                if lanes.get(lane, {}).get("status") != "live":
                    err(f"config/protected.json: real.allowed_lanes lists {lane!r}, which "
                        f"is not a live lane in config/lanes.json")
            if protected.get("real_trading_enabled") is True and not allowed:
                err("config/protected.json: real trading enabled with no allowed lanes")

risk = load_json("strategy/risk.json")
if risk and protected:
    for field in ("stake_usd", "min_net_edge"):
        if not is_num(risk.get(field)):
            err(f"strategy/risk.json: {field} missing or not numeric")
    if is_num(risk.get("stake_usd")) and not 0 < risk["stake_usd"] <= protected["max_stake_usd"]:
        err(f"strategy/risk.json: stake_usd {risk['stake_usd']} outside "
            f"(0, max_stake_usd {protected['max_stake_usd']}]")
    if is_num(risk.get("min_net_edge")) and not 0 < risk["min_net_edge"] < 1:
        err(f"strategy/risk.json: min_net_edge {risk['min_net_edge']} outside (0, 1)")

schedule = load_json("strategy/schedule.json")
if schedule:
    if not (isinstance(schedule.get("min_full_cycles_per_day"), int)
            and schedule["min_full_cycles_per_day"] >= 1):
        err("strategy/schedule.json: min_full_cycles_per_day missing or < 1 "
            "(the agent may not pace itself to zero)")
    if schedule.get("next_full_cycle_after") is not None:
        check_iso_z("strategy/schedule.json", "next_full_cycle_after",
                    schedule["next_full_cycle_after"])

playbook = ROOT / "strategy" / "playbook.md"
if playbook.exists() and playbook.stat().st_size > PLAYBOOK_MAX_BYTES:
    err(f"strategy/playbook.md: {playbook.stat().st_size} bytes exceeds the "
        f"{PLAYBOOK_MAX_BYTES}-byte cap — prune: move evidence to journal/, keep "
        f"active rules only")


def jsonl_rows(relpath):
    path = ROOT / relpath
    if not path.exists():
        return
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            yield lineno, json.loads(line)
        except json.JSONDecodeError as e:
            err(f"{relpath}:{lineno}: invalid JSON — {e}")


if protected:
    for lineno, row in jsonl_rows("journal/ledger.jsonl"):
        where = f"ledger.jsonl:{lineno}"
        missing = LEDGER_REQUIRED - row.keys()
        if missing:
            err(f"{where}: missing fields {sorted(missing)}")
            continue
        if row.get("engine_rev"):
            missing = ENGINE_BET_REQUIRED - row.keys()
            if missing:
                err(f"{where}: engine bet missing fields {sorted(missing)}")
            if row.get("method") not in lanes:
                err(f"{where}: method {row.get('method')!r} is not a registered lane")
        if row["status"] not in LEDGER_STATUSES:
            err(f"{where}: unknown status {row['status']!r}")
        if row["status"] != "open" and not ("pnl_usd" in row and "settled_ts" in row):
            err(f"{where}: settled row lacks pnl_usd/settled_ts")
        if row["stake_usd"] > protected["max_stake_usd"]:
            err(f"{where}: stake {row['stake_usd']} exceeds max_stake_usd "
                f"{protected['max_stake_usd']}")
        if not (protected["min_entry_price"] <= row["entry_price"]
                <= protected["max_entry_price"]):
            err(f"{where}: entry_price {row['entry_price']} outside "
                f"[{protected['min_entry_price']}, {protected['max_entry_price']}]")
        if not 0 < row["est_prob"] <= 1:
            err(f"{where}: est_prob {row['est_prob']} outside (0, 1]")

for lineno, row in jsonl_rows("journal/forecasts.jsonl"):
    where = f"forecasts.jsonl:{lineno}"
    missing = FORECAST_REQUIRED - row.keys()
    if missing:
        err(f"{where}: missing fields {sorted(missing)}")
        continue
    if row.get("method") is not None and row["method"] not in lanes:
        err(f"{where}: method {row['method']!r} is not a registered lane")
    if row["status"] not in LEDGER_STATUSES:
        err(f"{where}: unknown status {row['status']!r}")
    if row["status"] != "open" and "settled_ts" not in row:
        err(f"{where}: settled row lacks settled_ts")
    if not 0 < row["est_prob"] < 1:
        err(f"{where}: est_prob {row['est_prob']} outside (0, 1)")
    if not 0 <= row["market_prob_at_record"] <= 1:
        err(f"{where}: market_prob_at_record {row['market_prob_at_record']} outside [0, 1]")

if protected and isinstance(protected.get("real"), dict):
    real_cap = protected["real"].get("max_stake_usd")
    for lineno, row in jsonl_rows("journal/real-ledger.jsonl"):
        if is_num(real_cap) and is_num(row.get("usd")) and row["usd"] > real_cap:
            err(f"real-ledger.jsonl:{lineno}: real stake {row['usd']} exceeds "
                f"real.max_stake_usd {real_cap}")

for pyfile in sorted((ROOT / "core").glob("*.py")) + \
        sorted((ROOT / "strategy").rglob("*.py")):
    try:
        py_compile.compile(str(pyfile), doraise=True)
    except py_compile.PyCompileError as e:
        err(f"{pyfile.relative_to(ROOT)}: does not compile — {e.msg}")

if errors:
    print(f"FAIL — {len(errors)} integrity error(s):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("OK — config, lanes, risk knobs, schedule, playbook size, ledgers and Python sources all sane")
