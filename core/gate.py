#!/usr/bin/env python3
"""Forward gate per lane: has a lane's paper record earned real money?

PROTECTED CORE — the trading agent must not edit files under core/.

Each lane's forward test is its settled paper bets placed by the engine since
the lane's registered_at (config/lanes.json). Replay and forecast tables are
in-sample for anything chosen by reading the ledger; this is not. Criteria
live in config/lanes.json "gate" and were fixed before any forward bet:

  PASS     >= min_events distinct events, event-clustered net ROI lower bound
           (roi - 1 se) > min_lcb_net_roi, and no single event carrying more
           than max_event_share of total positive P&L.
  FAIL     >= kill_after_events events and the upper bound (roi + 1 se) < 0:
           demote the lane to forecast_only.
  NOT_YET  otherwise.

A verdict is advice to the operator: flipping a lane to live (and adding it
to config/protected.json real.allowed_lanes) or demoting it are operator
commits. The deep retro reads this report daily.

Usage: python3 core/gate.py [--json]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import decision  # noqa: E402
import stats  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = ROOT / "journal" / "ledger.jsonl"
CFG = json.loads((ROOT / "config" / "lanes.json").read_text())


def verdict(s, gate):
    if s["n_events"] >= gate["kill_after_events"] and s["ucb"] < 0:
        return "FAIL"
    if (s["n_events"] >= gate["min_events"] and s["lcb"] > gate["min_lcb_net_roi"]
            and (s["top_event_share"] or 0) <= gate["max_event_share"]):
        return "PASS"
    return "NOT_YET"


def report(entries):
    gate = CFG["gate"]
    out = {}
    for lane, spec in CFG["lanes"].items():
        since = decision.parse_ts(spec["registered_at"])
        bets = [e for e in entries
                if e.get("engine_rev") and decision.method_of(e) == lane
                and decision.parse_ts(e["ts"]) >= since]
        settled = [dict(e, stake=e["stake_usd"], pnl=e["pnl_usd"], event=decision.event_of(e))
                   for e in bets if e["status"] in ("won", "lost")]
        s = stats.clustered_roi(settled)
        out[lane] = {"status": spec["status"], "since": spec["registered_at"],
                     "open": sum(1 for e in bets if e["status"] == "open"),
                     **s, "verdict": verdict(s, gate)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    entries = [json.loads(x) for x in LEDGER.read_text().splitlines() if x.strip()] \
        if LEDGER.exists() else []
    rep = report(entries)
    if a.json:
        print(json.dumps(rep, indent=2))
        return
    g = CFG["gate"]
    print(f"forward gate (PASS: >={g['min_events']} events, lcb > {g['min_lcb_net_roi']}, "
          f"top event <= {g['max_event_share']:.0%} of gains; FAIL: >={g['kill_after_events']} "
          f"events and ucb < 0)")
    for lane, s in rep.items():
        se = "-" if s["se"] is None else f"{s['se']:.3f}"
        print(f"  {lane:9} [{s['status']:13}] {s['verdict']:7} settled={s['n_bets']:3} "
              f"events={s['n_events']:3} open={s['open']:2} pnl=${s['pnl']:+8.2f} "
              f"roi={s['roi']:+.3f} se={se} lcb={s['lcb']:+.3f}")


if __name__ == "__main__":
    main()
