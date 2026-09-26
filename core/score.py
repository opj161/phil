#!/usr/bin/env python3
"""Scoring & calibration report over settled paper positions and forecasts.

PROTECTED CORE — the trading agent must not edit files under core/.

The primary table is BY METHOD (lane, config/lanes.json): Phil v2 trades
lanes, fits the market-shrinkage weight lambda per lane, and promotes lanes
on their own record. brier_delta = Brier(agent) - Brier(market); negative
means the agent's estimate beat the market's own price as a forecast. P&L is
net of taker fees. Uncertainty is clustered by event (core/stats.py), so
sibling markets on one event count once.

Reported:
  bets       overall (+ luck-adjusted z), by era (pre-engine legacy vs engine),
             by method, open positions marked to market
  forecasts  overall, by method (n, events, brier_delta, current lambda),
             by category (n >= 10), calibration, revised-away slice

Usage: python3 core/score.py [--json] [--skip-mtm]
"""
import argparse
import datetime as dt
import json
import math
import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import decision  # noqa: E402
import pmapi  # noqa: E402
import stats as st  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = ROOT / "journal" / "ledger.jsonl"
FORECASTS = ROOT / "journal" / "forecasts.jsonl"
PROTECTED = json.loads((ROOT / "config" / "protected.json").read_text())
LANES = json.loads((ROOT / "config" / "lanes.json").read_text())["lanes"]
MIN_CATEGORY_N = 10


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def luck_adjusted(rows):
    """Expected wins under the agent's own estimates vs actual, as a z-score:
    if every est_prob were right, wins ~ sum(p) +- sqrt(sum p(1-p))."""
    exp = sum(r["est_prob"] for r in rows)
    var = sum(r["est_prob"] * (1 - r["est_prob"]) for r in rows)
    wins = sum(1 for r in rows if r["status"] == "won")
    return {"expected_wins": round(exp, 2), "actual_wins": wins,
            "z": round((wins - exp) / math.sqrt(var), 2) if var > 0 else 0.0}


def bet_stats(bets):
    rows = [dict(b, stake=b["stake_usd"], pnl=b["pnl_usd"], event=decision.event_of(b))
            for b in bets]
    return {**st.clustered_roi(rows),
            "wins": sum(1 for b in bets if b["status"] == "won"),
            "fees": round(sum(b.get("fee_usd", 0.0) for b in bets), 2),
            "brier_delta": st.brier_delta(bets, mkt_key="market_prob_at_entry")}


def forecast_stats(rows, lam=None):
    return {"n": len(rows), "events": len({decision.event_of(r) for r in rows}),
            "win_rate": round(sum(1 for r in rows if r["status"] == "won") / len(rows), 3),
            "brier_delta": st.brier_delta(rows), **({"lam": lam} if lam else {})}


def calibration(rows):
    buckets = defaultdict(list)
    for r in rows:
        buckets[min(int(r["est_prob"] * 10), 9)].append(r)
    return [{"est_range": f"{b/10:.1f}-{(b+1)/10:.1f}", "n": len(rs),
             "realized": round(sum(1 for r in rs if r["status"] == "won") / len(rs), 3)}
            for b, rs in sorted(buckets.items())]


def mark_to_market(open_entries):
    """Best-effort live marks for open positions (needs network)."""
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for e in open_entries:
        try:
            bid, ask = pmapi.best_prices(e["token_id"])
        except Exception as err:  # noqa: BLE001 — MTM is advisory, never fatal
            out.append({"id": e["id"], "error": str(err)[:80]})
            continue
        mid = (bid + ask) / 2 if bid is not None and ask is not None else bid or ask or 0.0
        end = decision.parse_ts(e.get("end_date"))
        out.append({"id": e["id"], "q": e["question"][:60], "outcome": e["outcome"],
                    "method": decision.method_of(e), "entry": e["entry_price"],
                    "mid": round(mid, 3),
                    "unrealized_usd": round(e["shares"] * mid - e["stake_usd"]
                                            - e.get("fee_usd", 0.0), 2),
                    "past_end_date": bool(end and end < now)})
    return out


def build(entries, frows, skip_mtm=True):
    now = dt.datetime.now(dt.timezone.utc)
    settled = [e for e in entries if e["status"] in ("won", "lost")]
    rep = {"bets": {}, "forecasts": {}}
    if settled:
        by_method, by_era = defaultdict(list), defaultdict(list)
        for e in settled:
            by_method[decision.method_of(e)].append(e)
            by_era["engine" if e.get("engine_rev") else "pre-engine"].append(e)
        rep["bets"] = {
            "overall": bet_stats(settled), "luck_adjusted": luck_adjusted(settled),
            "by_era": {k: bet_stats(v) for k, v in sorted(by_era.items())},
            "by_method": {k: bet_stats(v) for k, v in sorted(by_method.items())},
        }
    open_pos = [e for e in entries if e["status"] == "open"]
    rep["bets"]["open"] = len(open_pos)
    if open_pos and not skip_mtm:
        rep["bets"]["open_mtm"] = mark_to_market(open_pos)

    live = [r for r in frows if not r.get("superseded_by")]
    fs = [r for r in live if r["status"] in ("won", "lost")]
    revised = [r for r in frows if r.get("superseded_by") and r["status"] in ("won", "lost")]
    rep["forecasts"]["open"] = sum(1 for r in live if r["status"] == "open")
    if fs:
        by_method, by_cat = defaultdict(list), defaultdict(list)
        for r in fs:
            by_method[decision.method_of(r)].append(r)
            by_cat[r.get("category") or "?"].append(r)
        methods = {}
        for m in sorted(set(by_method) | set(LANES)):
            fit = decision.lane_lambda(m, LANES.get(m, {}).get("status"), frows, now,
                                       PROTECTED["engine"])
            rows = by_method.get(m, [])
            methods[m] = {**(forecast_stats(rows) if rows else {"n": 0, "events": 0}),
                          "lam": fit["lam"], "lam_source": fit["source"], "w_opt": fit["w_opt"],
                          "status": LANES.get(m, {}).get("status", "unregistered")}
        rep["forecasts"].update({
            "overall": forecast_stats(fs), "luck_adjusted": luck_adjusted(fs),
            "by_method": methods,
            "by_category": {c: forecast_stats(rs) for c, rs in sorted(by_cat.items())
                            if len(rs) >= MIN_CATEGORY_N},
            "calibration": calibration(fs),
            "revised_away": forecast_stats(revised) if revised else {"n": 0},
        })
    return rep


def print_report(rep):
    b = rep["bets"]
    if b.get("overall"):
        o, la = b["overall"], b["luck_adjusted"]
        print(f"BETS settled={o['n_bets']} events={o['n_events']} wins={o['wins']} "
              f"pnl(net)=${o['pnl']:+.2f} roi={o['roi']:+.3f} (event-clustered se "
              f"{o['se']}) fees=${o['fees']:.2f} brier_delta={o['brier_delta']:+.4f}")
        print(f"  luck-adjusted: expected wins (own ests)={la['expected_wins']} "
              f"actual={la['actual_wins']} z={la['z']:+.2f}")
        for title, table in (("by era", b["by_era"]), ("by method", b["by_method"])):
            print(f"  {title}:")
            for k, s in table.items():
                print(f"    {k:11} n={s['n_bets']:3} ev={s['n_events']:3} "
                      f"pnl=${s['pnl']:+8.2f} roi={s['roi']:+.3f} lcb={s['lcb']:+.3f} "
                      f"brier_delta={s['brier_delta']:+.4f}")
    print(f"  open positions: {b.get('open', 0)}")
    for r in b.get("open_mtm", []):
        if "error" in r:
            print(f"    {r['id']} MTM unavailable: {r['error']}")
        else:
            flag = "  PAST END DATE" if r["past_end_date"] else ""
            print(f"    {r['id']} {r['method']:8} {r['outcome'][:10]:10} entry={r['entry']} "
                  f"mid={r['mid']} unrealized=${r['unrealized_usd']:+.2f}{flag}")
    f = rep["forecasts"]
    if not f.get("overall"):
        print(f"FORECASTS settled=0 open={f.get('open', 0)}")
        return
    o, la = f["overall"], f["luck_adjusted"]
    print(f"\nFORECASTS (mid baseline) settled={o['n']} events={o['events']} open={f['open']} "
          f"brier_delta={o['brier_delta']:+.4f} luck z={la['z']:+.2f}")
    print("  by method (lam = the engine's current market-shrinkage weight):")
    for m, s in f["by_method"].items():
        bd = "-" if s.get("brier_delta") is None else f"{s['brier_delta']:+.4f}"
        w = "-" if s["w_opt"] is None else f"{s['w_opt']:+.2f}"
        print(f"    {m:9} [{s['status']:13}] n={s['n']:4} ev={s['events']:4} "
              f"brier_delta={bd} w_opt={w} lam={s['lam']:.2f} ({s['lam_source']})")
    ra = f["revised_away"]
    if ra.get("n"):
        print(f"  revised-away: n={ra['n']} brier_delta={ra['brier_delta']:+.4f}")
    print(f"  by category (n>={MIN_CATEGORY_N}):")
    for c, s in f["by_category"].items():
        print(f"    {c:24} n={s['n']:4} ev={s['events']:4} brier_delta={s['brier_delta']:+.4f}")
    print("  calibration: " + "  ".join(
        f"{c['est_range']}:n={c['n']},r={c['realized']:.2f}" for c in f["calibration"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-mtm", action="store_true",
                    help="skip live mark-to-market of open positions (offline)")
    args = ap.parse_args()
    rep = build(read_jsonl(LEDGER), read_jsonl(FORECASTS), skip_mtm=args.skip_mtm)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print_report(rep)


if __name__ == "__main__":
    main()
