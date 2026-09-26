#!/usr/bin/env python3
"""Point-in-time replay of the decision engine over the frozen forecast ledger.

PROTECTED CORE — the trading agent must not edit files under core/.

Every settled forecast is replayed in record-time order through the SAME
engine that places paper bets (core/decision.py), with only what was knowable
at that moment:
  - the lane weight lambda is fitted from forecasts whose outcome was known
    before the row was recorded (noticed_ts, else settled_ts + lag): no
    future label can reach the fit, unlike the fold replay this replaces
    (which trained on earlier-RECORDED rows whatever their settlement time).
    Below lambda_min_events a paper lane gets the cold-start prior, exactly
    as live placement does (decision.lane_lambda);
  - the book is the one recorded with the forecast. The complement side's
    ask is approximated as 1 - recorded bid (the live engine reads the
    complement's own book), and depth beyond the recorded top level is not
    known, so a top level too small for the stake falls back to a 1c-worse
    level;
  - fees are the market's recorded taker terms; rows recorded before fee
    terms were captured get an ASSUMED rate by category (--assume-fees
    category, the default, or none), flagged in the report;
  - open simulated bets count against the event and hourly caps until their
    outcome was known. Cash is not simulated.

Lanes trade per their current config/lanes.json status; --all-lanes replays
every method as if tradeable (research view, never a promotion argument).
Legacy rows carry a backfilled method_inferred. Replay is IN-SAMPLE for any
rule chosen by reading this ledger; only paper bets after a lane's
registered_at (core/gate.py) are forward evidence.

Usage: python3 core/replay.py [--after TS] [--all-lanes]
                              [--assume-fees category|none] [--json] [--bets]
  --after TS   only rows whose outcome was unknown at TS (settled_ts > TS)
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import decision  # noqa: E402
import stats  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
FORECASTS = ROOT / "journal" / "forecasts.jsonl"
PROTECTED = json.loads((ROOT / "config" / "protected.json").read_text())
LANES = json.loads((ROOT / "config" / "lanes.json").read_text())["lanes"]
BIG = 1e9

# Polymarket taker-fee categories (help center, Trading Fees, 2026-07), mapped
# from the agent's category labels. Used ONLY for legacy rows recorded before
# per-market fee terms were captured; fee-free markets exist in every
# category, so this errs toward charging.
ASSUMED_FEE_BY_PREFIX = [
    (("crypto",), 0.07),
    (("say-the-word", "trump-mention", "vance-mention", "mention", "politic",
      "commodit", "equit", "corporate", "ai-", "product", "app-store"), 0.04),
    (("geopolitic", "news"), 0.0),
]
DEFAULT_ASSUMED_FEE = 0.05  # sports, economics, weather, culture, other


def assumed_fee(category):
    c = (category or "").lower()
    for prefixes, rate in ASSUMED_FEE_BY_PREFIX:
        if any(c.startswith(p) for p in prefixes):
            return rate
    return DEFAULT_ASSUMED_FEE


def load_forecasts():
    return [json.loads(line) for line in FORECASTS.read_text().splitlines() if line.strip()]


def replayable(r):
    return (r.get("status") in ("won", "lost") and not r.get("superseded_by")
            and r.get("best_ask_at_record") is not None
            and r.get("best_bid_at_record") is not None)


def recorded_quotes(r, stake):
    ask, bid = r["best_ask_at_record"], r["best_bid_at_record"]

    def level(price, size):
        # a recorded top level too thin for the stake gets a 1c-worse backstop
        if size is not None and size * price < stake:
            return [(price, size), (round(price + 0.01, 4), BIG)]
        return [(price, BIG)]

    yes = {"outcome": r["outcome"], "token_id": r.get("token_id"),
           "bids": [(bid, BIG)], "asks": level(ask, r.get("ask_size_at_record"))}
    no = {"outcome": "(complement)", "token_id": None,
          "bids": [(round(1 - ask, 4), BIG)], "asks": [(round(1 - bid, 4), BIG)]}
    return {"yes": yes, "no": no}


def run(forecasts, after=None, all_lanes=False, assume_fees="category"):
    engine = PROTECTED["engine"]
    cfg = decision.engine_cfg(PROTECTED, read_risk())
    lag = engine["legacy_known_lag_hours"]
    rows = sorted((r for r in forecasts if replayable(r)), key=lambda r: (r["ts"], r["id"]))
    if after:
        rows = [r for r in rows if (r.get("settled_ts") or "") > after]
    open_bets, bets, rejects = [], [], defaultdict(int)
    assumed = 0
    lam_cache = {}
    for r in rows:
        t = decision.parse_ts(r["ts"])
        open_bets = [b for b in open_bets if b["known"] > t]
        method = decision.method_of(r)
        status = "paper" if all_lanes else LANES.get(method, {}).get("status")
        key = (method, r["ts"][:13])
        if key not in lam_cache:
            lam_cache[key] = decision.lane_lambda(method, status, forecasts, t, engine)["lam"]
        if r.get("fee_rate") is not None:
            fee = {"rate": r["fee_rate"], "exponent": r.get("fee_exponent") or 1.0}
        else:
            fee = {"rate": assumed_fee(r.get("category")) if assume_fees == "category" else 0.0,
                   "exponent": 1.0}
            assumed += 1
        portfolio = {"open": open_bets,
                     "recent": [b for b in open_bets if t - b["t"] < dt.timedelta(hours=1)],
                     "cash": BIG}
        d = decision.decide(r, recorded_quotes(r, cfg["stake_usd"]), fee, t, portfolio,
                            status, lam_cache[key], cfg)
        if not d["trade"]:
            rejects[d["reason"]] += 1
            continue
        side_wins = (r["status"] == "won") == (d["side"] == "yes")
        pnl = (d["shares"] if side_wins else 0.0) - d["stake_usd"] - d["fee_usd"]
        b = {"id": r["id"], "t": t, "known": decision.known_ts(r, lag) or t,
             "market_id": r["market_id"], "event_id": decision.event_of(r),
             "event": decision.event_of(r), "stake_usd": d["stake_usd"],
             "stake": d["stake_usd"], "pnl": round(pnl, 4), "fee": d["fee_usd"],
             "side": d["side"], "price": d["vwap"], "net_edge": d["net_edge"],
             "lam": d["lam"], "method": method, "est_prob": r["est_prob"],
             "market_prob_at_record": r["market_prob_at_record"], "status": r["status"],
             "category": r.get("category"), "question": r["question"][:60]}
        open_bets.append(b)
        bets.append(b)
    by_method = defaultdict(list)
    for b in bets:
        by_method[b["method"]].append(b)
    return {
        "n_rows": len(rows), "after": after, "all_lanes": all_lanes,
        "assumed_fee_rows": assumed if assume_fees == "category" else 0,
        "overall": {**stats.clustered_roi(bets), "brier_delta": stats.brier_delta(bets),
                    "fees": round(sum(b["fee"] for b in bets), 2)},
        "by_method": {m: {**stats.clustered_roi(bs), "brier_delta": stats.brier_delta(bs)}
                      for m, bs in sorted(by_method.items())},
        "rejects": dict(sorted(rejects.items(), key=lambda kv: -kv[1])),
        "bets": bets,
    }


def read_risk():
    try:
        return json.loads((ROOT / "strategy" / "risk.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def fmt(s):
    se = "-" if s["se"] is None else f"{s['se']:.3f}"
    bd = s.get("brier_delta")
    bd = "-" if bd is None else f"{bd:+.4f}"
    return (f"bets {s['n_bets']:>4} events {s['n_events']:>4} staked {s['staked']:>8.2f} "
            f"pnl {s['pnl']:>+8.2f} roi {s['roi']:>+7.3f} se {se:>6} lcb {s['lcb']:>+7.3f} "
            f"dBrier {bd}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--after", metavar="TS",
                    help="only rows whose outcome was unknown at this UTC timestamp")
    ap.add_argument("--all-lanes", action="store_true",
                    help="treat every method as tradeable (research view)")
    ap.add_argument("--assume-fees", choices=("category", "none"), default="category")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--bets", action="store_true", help="list every replayed bet")
    a = ap.parse_args()
    if a.after:
        try:
            decision.parse_ts(a.after)
        except ValueError:
            sys.exit(f"--after expects a UTC timestamp like 2026-09-02T00:14:36Z, got {a.after!r}")
    rep = run(load_forecasts(), a.after, a.all_lanes, a.assume_fees)
    if a.json:
        out = dict(rep, bets=[{k: (v.isoformat() if isinstance(v, dt.datetime) else v)
                               for k, v in b.items()} for b in rep["bets"]])
        print(json.dumps(out, indent=1))
        return
    if a.bets:
        for b in rep["bets"]:
            print(f"  {b['id']} {b['method']:<8} {b['side']:>3} px={b['price']:.3f} "
                  f"est={b['est_prob']:.3f} lam={b['lam']:.2f} net={b['net_edge']:+.3f} "
                  f"pnl={b['pnl']:+7.2f} {b['question']}")
    scope = f"settled after {a.after}" if a.after else "all settled"
    print(f"replay (point-in-time, engine {decision.ENGINE_REV}): {rep['n_rows']} {scope} "
          f"forecasts; {'ALL lanes as tradeable' if a.all_lanes else 'lanes per config/lanes.json'}")
    if rep["assumed_fee_rows"]:
        print(f"  fees: {rep['assumed_fee_rows']} legacy rows priced at an ASSUMED category "
              f"taker rate (conservative; --assume-fees none to drop)")
    print(f"  overall   {fmt(rep['overall'])}  fees {rep['overall']['fees']:.2f}")
    for m, s in rep["by_method"].items():
        print(f"  {m:<9} {fmt(s)}")
    print("  rejects: " + ", ".join(f"{k} {v}" for k, v in rep["rejects"].items()))


if __name__ == "__main__":
    main()
