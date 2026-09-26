#!/usr/bin/env python3
"""Paper broker: place simulated positions and track the bankroll.

PROTECTED CORE — the trading agent must not edit files under core/.
The agent CALLS this to bet; it cannot bypass the caps in config/protected.json
because this is the only writer of journal/ledger.jsonl.

Phil v2 (2026-09-26): a bet can only come from a recorded forecast, and the
decision is the engine's, not the agent's. `place --forecast-id` reloads the
forecast, refetches BOTH outcome books and the market's fee terms, fits the
lane's market-shrinkage weight from forecasts known by now, and asks
core/decision.py which side to buy, if any. So the policy that replay scores is
exactly the policy that trades, and the edge is re-checked on the live book at
fill time.

Fills are honest: the paper BUY walks the chosen outcome's live ask book for
the stake (VWAP, like a real taker order) and pays the market's taker fee.
A skip (no side clears the net edge, a cap binds, ...) is a normal outcome,
printed as JSON with its reason and exit code 0.

Usage:
  place:  python3 core/ledger.py place --forecast-id abc123def456 \
            --rationale "barrier model 0.18 vs mid 0.11, OVX-sourced vol" \
            [--strategy-rev $(git rev-parse --short HEAD)] [--dry-run]
  batch:  python3 core/ledger.py place-batch [--dry-run] < work/plan.jsonl
            (rows carry forecast_id, or market_id + outcome of a live forecast)
  status: python3 core/ledger.py status
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import decision  # noqa: E402
import pmapi  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = ROOT / "journal" / "ledger.jsonl"
FORECASTS = ROOT / "journal" / "forecasts.jsonl"
DECISIONS = ROOT / "journal" / "decisions.jsonl"
PROTECTED = json.loads((ROOT / "config" / "protected.json").read_text())
LANES = json.loads((ROOT / "config" / "lanes.json").read_text())["lanes"]


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_ledger():
    return read_jsonl(LEDGER)


def read_risk():
    try:
        return json.loads((ROOT / "strategy" / "risk.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def bankroll(entries):
    cash = PROTECTED["sim_bankroll_usd"]
    for e in entries:
        fee = e.get("fee_usd", 0.0)
        if e["status"] in ("open", "won", "lost", "void"):
            cash -= e["stake_usd"] + fee
        if e["status"] == "won":
            cash += e["shares"]  # $1 per share
        elif e["status"] == "void":
            cash += e["stake_usd"] + fee
    return cash


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def cmd_status(entries):
    now = now_utc()
    open_pos = [e for e in entries if e["status"] == "open"]
    settled = [e for e in entries if e["status"] in ("won", "lost")]
    pnl = sum(e["pnl_usd"] for e in settled)
    print(json.dumps({
        "cash": round(bankroll(entries), 2),
        "open_positions": len(open_pos),
        "settled": len(settled),
        "wins": sum(1 for e in settled if e["status"] == "won"),
        "realized_pnl_net": round(pnl, 2),
        "fees_paid": round(sum(e.get("fee_usd", 0.0) for e in entries), 2),
        "open": [{"id": e["id"], "q": e["question"][:70], "outcome": e["outcome"],
                  "method": decision.method_of(e), "entry": e["entry_price"],
                  "ends": e["end_date"],
                  # closed-but-unresolved is its own state, not a normal open row
                  "past_end": bool(decision.parse_ts(e.get("end_date"))
                                   and decision.parse_ts(e["end_date"]) < now)}
                 for e in open_pos],
    }, indent=2))


def side_quote(tokens, outcome):
    book = pmapi.book_levels(tokens[outcome])
    return {"outcome": outcome, "token_id": tokens[outcome], **book}


class PlaceError(Exception):
    pass


def place_one(fc_id, rationale, strategy_rev, entries, forecasts, dry_run=False):
    """Run the engine on one live forecast; append the bet if it trades.
    Returns the verdict dict (placed id or skip reason). `entries` gains the
    new row, so a batch's later decisions see its earlier bets' caps."""
    fc = next((r for r in forecasts if r["id"] == fc_id), None)
    if fc is None:
        raise PlaceError(f"no forecast with id {fc_id}")
    if fc["status"] != "open" or fc.get("superseded_by"):
        raise PlaceError(f"forecast {fc_id} is not live (status {fc['status']}, "
                         f"superseded_by {fc.get('superseded_by')})")
    m = pmapi.gamma_market(fc["market_id"])
    if m.get("closed"):
        raise PlaceError("market is closed")
    tokens = pmapi.market_tokens(m)
    if len(tokens) != 2 or fc["outcome"] not in tokens:
        raise PlaceError(f"engine trades binary markets only; outcomes {list(tokens)}")
    other = next(o for o in tokens if o != fc["outcome"])
    quotes = {"yes": side_quote(tokens, fc["outcome"]), "no": side_quote(tokens, other)}
    fee = pmapi.fee_schedule(m)

    now = now_utc()
    method = decision.method_of(fc)
    cfg = decision.engine_cfg(PROTECTED, read_risk())
    status = LANES.get(method, {}).get("status")
    fit = decision.lane_lambda(method, status, forecasts, now, PROTECTED["engine"])
    open_pos = [e for e in entries if e["status"] == "open"]
    recent = [e for e in entries
              if now - decision.parse_ts(e["ts"]) < dt.timedelta(hours=1)]
    portfolio = {"open": open_pos, "recent": recent, "cash": bankroll(entries)}
    live_fc = dict(fc, end_date=m.get("endDate") or fc.get("end_date"),
                   event_id=fc.get("event_id") or pmapi.event_id(m))
    d = decision.decide(live_fc, quotes, fee, now, portfolio, status, fit["lam"], cfg)
    d["lambda_fit"] = fit
    if not dry_run:
        # every engine verdict, trade or skip, so retros can see why a lane
        # does or does not trade (compact: the per-side detail stays here)
        best = max((s for s in d.get("sides", []) if "net_edge" in s),
                   key=lambda s: s["net_edge"], default=None)
        with DECISIONS.open("a") as f:
            f.write(json.dumps({
                "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "forecast_id": fc["id"],
                "market_id": fc["market_id"], "method": method, "trade": d["trade"],
                "reason": d.get("reason"), "lam": fit["lam"], "lam_source": fit["source"],
                "n_events": fit["n_events"],
                "mid": d.get("mid"), "spread": d.get("spread"), "p_trade": d.get("p_trade"),
                "best_side": best and best["side"], "best_net_edge": best and best["net_edge"],
                "fee_rate": fee["rate"], "engine_rev": d["engine_rev"]}) + "\n")
    if not d["trade"] or dry_run:
        return {"placed": None, "dry_run": dry_run, "method": method,
                "forecast_id": fc["id"], "question": fc["question"], **d}

    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "forecast_id": fc["id"],
        "market_id": fc["market_id"],
        "question": m.get("question"),
        "slug": m.get("slug"),
        "end_date": m.get("endDate"),
        "event_id": d["event_id"],
        "outcome": d["outcome"],
        "token_id": d["token_id"],
        "side": d["side"],
        "entry_price": d["vwap"],
        "best_bid_at_entry": d["best_bid"],
        "best_ask_at_entry": d["best_ask"],
        # the bet-Brier baseline stays the price actually paid, as before v2
        "market_prob_at_entry": d["vwap"],
        # mid of the outcome BOUGHT (the engine reports the forecast outcome's)
        "mid_at_entry": d["mid"] if d["side"] == "yes" else round(1 - d["mid"], 4),
        "est_prob": d["p_raw"],
        "p_trade": d["prob"],
        "lam": d["lam"],
        "edge": round(d["prob"] - d["vwap"], 4),
        "net_edge": d["net_edge"],
        "stake_usd": d["stake_usd"],
        "shares": d["shares"],
        "fee_rate": fee["rate"],
        "fee_usd": d["fee_usd"],
        "category": fc.get("category"),
        "method": method,
        "rationale": rationale,
        "strategy_rev": strategy_rev,
        "engine_rev": d["engine_rev"],
        "status": "open",
    }
    with LEDGER.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    entries.append(entry)
    return {"placed": entry["id"], "side": d["side"], "outcome": d["outcome"],
            "filled_at": d["vwap"], "net_edge": d["net_edge"], "fee_usd": d["fee_usd"],
            "lam": d["lam"], "method": method, "question": entry["question"]}


def cmd_place(args, entries):
    try:
        out = place_one(args.forecast_id, args.rationale, args.strategy_rev, entries,
                        read_jsonl(FORECASTS), args.dry_run)
    except PlaceError as e:
        sys.exit(f"ERROR: {e}")
    print(json.dumps(out, indent=2))


def cmd_place_batch(args, entries):
    """One JSON row per stdin line with forecast_id, or market_id + outcome
    (the live forecast on it is used); rows with an "action" other than
    record/supersede/place are ignored. Prints one compact verdict per row."""
    forecasts = read_jsonl(FORECASTS)
    live = {(f["market_id"], f["outcome"]): f["id"] for f in forecasts
            if f["status"] == "open" and not f.get("superseded_by")}
    counts = {}
    for line in sys.stdin:
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("action") not in (None, "record", "supersede", "place"):
            continue
        fc_id = row.get("forecast_id") if row.get("action") == "place" else None
        fc_id = fc_id or live.get((str(row.get("market_id")), row.get("outcome")))
        if not fc_id:
            counts["no_live_forecast"] = counts.get("no_live_forecast", 0) + 1
            continue
        try:
            out = place_one(fc_id, row.get("rationale") or args.rationale,
                            args.strategy_rev, entries, forecasts, args.dry_run)
            key = "placed" if out.get("placed") else out.get("reason", "?")
            print(json.dumps({k: out.get(k) for k in (
                "placed", "reason", "method", "side", "net_edge", "lam", "forecast_id",
                "question") if out.get(k) is not None}))
        except (PlaceError, RuntimeError) as e:
            key = "error"
            print(json.dumps({"error": str(e), "forecast_id": fc_id}))
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({"place_batch": counts}), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("place")
    p.add_argument("--forecast-id", required=True,
                   help="the recorded forecast to trade (core/forecast.py record)")
    p.add_argument("--rationale", required=True, help="one-line reason (for the retro)")
    p.add_argument("--strategy-rev", default="", help="git rev of strategy/ used")
    p.add_argument("--dry-run", action="store_true",
                   help="print the engine's decision without placing")
    pb = sub.add_parser("place-batch", help="run the engine on many forecasts (stdin JSONL)")
    pb.add_argument("--rationale", default="lane model vs live book (engine)",
                    help="default rationale for rows that carry none")
    pb.add_argument("--strategy-rev", default="")
    pb.add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    args = ap.parse_args()

    entries = read_ledger()
    if args.cmd == "status":
        cmd_status(entries)
    elif args.cmd == "place-batch":
        cmd_place_batch(args, entries)
    else:
        cmd_place(args, entries)


if __name__ == "__main__":
    main()
