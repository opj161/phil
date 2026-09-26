#!/usr/bin/env python3
"""Forecast ledger: score every researched estimate, not just bets.

PROTECTED CORE — the trading agent must not edit files under core/.
This is the only writer of journal/forecasts.jsonl (resolve.py settles rows).

The experiment's honest metric is brier_delta — is the agent's probability a
better forecast than the market's own price? — and measuring that needs no
stake. Research that ends in a skip (no-edge, market-agrees) still produced
an estimate; recording it here turns ~10-30 researched candidates/day into
scored calibration feedback instead of ~0-1 settled bets/day.

No caps, no edge floor, no fill: the market baseline is the MID at record
time ((bid+ask)/2), not the ask a bet would fill at — a forecast has no
transaction, and the mid is the stricter benchmark. Forecast brier_delta is
therefore NOT comparable to bet brier_delta; score.py reports them in
separate sections. est_prob is the agent's honest belief, formed before
anchoring on the price, exactly as for bets.

Every forecast names its METHOD - a lane in config/lanes.json (Phil v2). The
lane is what the engine (core/decision.py) fits its market-shrinkage weight
on and what it decides to trade, so a forecast is also the only way into a
bet: core/ledger.py place --forecast-id <id>.

One live forecast per market+outcome: recurring re-checks of the same market
must not flood the stats with correlated rows. A materially changed read
(|delta est_prob| >= 0.05, or a changed funnel decision) may replace the live
row via record --supersede: the rows are linked (supersedes / superseded_by),
only the latest row counts in headline scoring, and the superseded row still
settles into score.py's separate revised-away slice - whether revisions
actually improve estimates is measured, not assumed (PLBY 2026-08-10: the
revision was worse than the original).

Usage:
  record: python3 core/forecast.py record --market-id 123 --outcome Yes \
            --est-prob 0.62 --method barrier --category commodities \
            [--note "..."] [--strategy-rev abc1234] \
            [--confirm-extreme] [--supersede]
  batch:  python3 core/forecast.py record-batch < specs.jsonl
            (one JSON spec per line with the same fields; rows whose
            "action" is neither record nor supersede are ignored)
  status: python3 core/forecast.py status
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import uuid
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pmapi  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
FORECASTS = ROOT / "journal" / "forecasts.jsonl"
LANES = json.loads((ROOT / "config" / "lanes.json").read_text())["lanes"]

# A supersede must change something material: a re-record of an unchanged
# estimate is the correlated-row flooding the one-live-row rule exists to
# prevent, not a revision.
MIN_REVISION_DELTA = 0.05

# An |est_prob - mid| gap this large is either a deliberate extreme
# disagreement (rare: the outside-view-veto class) or an inverted outcome
# side (fe954ed9f325: --outcome No with the Yes-side est_prob, silently
# recording the opposite of the researched belief). The flag costs one
# keystroke exactly when the agent should be pausing anyway; the typo gets
# caught at the only moment it is fixable.
EXTREME_DISAGREEMENT = 0.40

# A book wider than this has no usable market probability (Phil v2).
MAX_BENCHMARK_SPREAD = 0.20


def read_forecasts():
    if not FORECASTS.exists():
        return []
    return [json.loads(line) for line in FORECASTS.read_text().splitlines() if line.strip()]


def cmd_status(rows):
    print(json.dumps({
        "total": len(rows),
        "by_status": dict(Counter(r["status"] for r in rows)),
        "by_method": dict(Counter(r.get("method") or r.get("method_inferred") or "?"
                                  for r in rows)),
        "settled_wins": sum(1 for r in rows if r["status"] == "won"),
        "revised_away": sum(1 for r in rows if r.get("superseded_by")),
    }, indent=2))


def _num(value):
    """gamma numeric field -> float rounded to cents, or None if absent/unparseable."""
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _fee_fields(fee):
    return {"fees_enabled": fee["fees_enabled"], "fee_rate": fee["rate"],
            "fee_exponent": fee["exponent"], "fee_type": fee["fee_type"]}


class Rejected(Exception):
    pass


def record_one(spec, rows):
    """Validate and append one forecast. spec keys: market_id, outcome,
    est_prob, method, category and optionally skip_reason, supersede,
    confirm_extreme, fit_score, note, strategy_rev. Appends the new row to
    `rows` (so a batch sees its own earlier rows) and returns the summary.
    Raises Rejected with the reason instead of writing anything."""
    args = argparse.Namespace(**{"skip_reason": "engine", "supersede": False,
                                 "confirm_extreme": False, "fit_score": None,
                                 "note": "", "strategy_rev": "", **spec})
    if args.method not in LANES:
        raise Rejected(f"method {args.method!r} is not a lane in config/lanes.json")
    args.est_prob = float(args.est_prob)
    args.market_id = str(args.market_id)
    if not 0.0 < args.est_prob < 1.0:
        raise Rejected("est-prob must be in (0,1)")
    live = [r for r in rows
            if r["market_id"] == args.market_id and r["outcome"] == args.outcome
            and r["status"] == "open" and not r.get("superseded_by")]
    if live and not args.supersede:
        raise Rejected("already have an open forecast on this market+outcome "
                 "(a materially changed read may supersede it: --supersede)")
    old = None
    if args.supersede:
        if not live:
            raise Rejected("--supersede, but no live open forecast on this "
                     "market+outcome to supersede")
        old = live[0]
        # round like ledger.py's edge field so an exactly-boundary revision
        # (0.33 - 0.28 = 0.049999...) does not float-drop below the gate
        if (round(abs(args.est_prob - old["est_prob"]), 4) < MIN_REVISION_DELTA
                and args.skip_reason == old.get("skip_reason")):
            raise Rejected(f"supersede needs a material change — "
                     f"|delta est_prob| >= {MIN_REVISION_DELTA} "
                     f"(old {old['est_prob']}, new {args.est_prob}) or a changed "
                     f"skip-reason (old {old.get('skip_reason')!r})")

    m = pmapi.gamma_market(args.market_id)
    if m.get("closed"):
        raise Rejected("market is closed")
    lane = LANES[args.method]
    if lane.get("shape_regex") and not re.search(lane["shape_regex"], m.get("question") or ""):
        raise Rejected(f"question does not have the {args.method!r} lane's shape "
                 f"(config/lanes.json shape_regex) - record it under the lane whose "
                 f"method you actually used, or as 'explore'")
    if lane.get("min_days_to_end"):
        end = dt.datetime.fromisoformat(m["endDate"].replace("Z", "+00:00"))
        days = (end - dt.datetime.now(dt.timezone.utc)).total_seconds() / 86400
        if days < lane["min_days_to_end"]:
            raise Rejected(f"resolves in {days:.1f} days, under the {args.method!r} "
                     f"lane's min_days_to_end {lane['min_days_to_end']} - record it as "
                     f"'explore' if you still formed an estimate")
    tokens = pmapi.market_tokens(m)
    if args.outcome not in tokens:
        raise Rejected(f"outcome {args.outcome!r} not in {list(tokens)}")
    book = pmapi.book_levels(tokens[args.outcome])
    bid = book["bids"][0][0] if book["bids"] else None
    ask = book["asks"][0][0] if book["asks"] else None
    if bid is None or ask is None or ask - bid > MAX_BENCHMARK_SPREAD:
        # a one-sided or placeholder book (e.g. 0.01/0.99 on a fresh listing)
        # has no market probability: its "mid" would score any estimate as
        # skill and corrupt the engine's per-lane lambda fit
        raise Rejected(f"no real market price to benchmark against (bid {bid}, ask {ask}; "
                       f"spread limit {MAX_BENCHMARK_SPREAD})")
    mid = (bid + ask) / 2

    gap = abs(args.est_prob - mid)
    if gap > EXTREME_DISAGREEMENT and not args.confirm_extreme:
        raise Rejected(f"est_prob {args.est_prob} vs market mid {round(mid, 4)} "
                 f"for outcome {args.outcome!r} differs by {round(gap, 4)} "
                 f"(> {EXTREME_DISAGREEMENT}). If this extreme disagreement is your "
                 "researched belief, re-run with --confirm-extreme; if not, you "
                 "probably inverted the outcome side (est_prob must be for the "
                 f"named outcome {args.outcome!r}, not its complement).")

    row = {
        "id": uuid.uuid4().hex[:12],
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market_id": args.market_id,
        "question": m.get("question"),
        "slug": m.get("slug"),
        "end_date": m.get("endDate"),
        "outcome": args.outcome,
        "token_id": tokens[args.outcome],
        "est_prob": args.est_prob,
        "best_bid_at_record": bid,
        "best_ask_at_record": ask,
        "market_prob_at_record": round(mid, 4),
        # Book size at record time, from the same gamma record scan.py reads.
        # Added 2026-09-09 so research edge can be split by liquidity later;
        # gnhf run 5 had to drop that feature for lack of it. None when gamma
        # omits the field - never a guess, never a later re-read.
        "liquidity_at_record": _num(m.get("liquidityNum")),
        "volume_24h_at_record": _num(m.get("volume24hr")),
        # Top-of-book sizes (shares), the event the market belongs to and the
        # market's taker-fee terms, all at record time (Phil v2): the engine,
        # replay and gate need depth, event clustering and net-of-fee edges.
        "bid_size_at_record": book["bids"][0][1] if book["bids"] else None,
        "ask_size_at_record": book["asks"][0][1] if book["asks"] else None,
        "event_id": pmapi.event_id(m),
        **_fee_fields(pmapi.fee_schedule(m)),
        "method": args.method,
        "category": args.category,
        "skip_reason": args.skip_reason,
        "fit_score": args.fit_score,
        "note": args.note,
        "strategy_rev": args.strategy_rev,
        "status": "open",
    }
    if old is not None:
        # The old row stays open so resolve.py still settles it (score.py
        # grades it in the revised-away slice, not the headline stats).
        row["supersedes"] = old["id"]
        old["superseded_by"] = row["id"]
        old["superseded_ts"] = row["ts"]
        FORECASTS.write_text("".join(json.dumps(r) + "\n" for r in rows + [row]))
    else:
        with FORECASTS.open("a") as f:
            f.write(json.dumps(row) + "\n")
    rows.append(row)
    out = {"recorded": row["id"], "mid": row["market_prob_at_record"],
           "bid": bid, "ask": ask, "delta_vs_mid": round(args.est_prob - mid, 4),
           "question": row["question"]}
    if old is not None:
        out["supersedes"] = old["id"]
        out["delta_est_prob"] = round(args.est_prob - old["est_prob"], 4)
    return out


def cmd_record(args, rows):
    try:
        print(json.dumps(record_one(vars(args), rows), indent=2))
    except Rejected as e:
        sys.exit(f"REJECTED: {e}")


def cmd_record_batch(rows):
    """One JSON spec per stdin line (the fields record takes, as JSON keys;
    strategy/tools/lanes.py plan writes them). Every row passes the same
    checks as a single record; a rejected row is reported and skipped."""
    n_ok = n_rej = 0
    for line in sys.stdin:
        if not line.strip():
            continue
        spec = json.loads(line)
        if spec.get("action") not in (None, "record", "supersede"):
            continue
        spec = {k: v for k, v in spec.items() if k in (
            "market_id", "outcome", "est_prob", "method", "category", "skip_reason",
            "supersede", "confirm_extreme", "fit_score", "note", "strategy_rev")}
        try:
            out = record_one(spec, rows)
            n_ok += 1
            print(json.dumps({"ok": True, "market_id": spec["market_id"], **out}))
        except (Rejected, KeyError, ValueError, RuntimeError) as e:
            n_rej += 1
            print(json.dumps({"ok": False, "market_id": spec.get("market_id"),
                              "error": f"{type(e).__name__}: {e}"}))
    print(json.dumps({"recorded": n_ok, "rejected": n_rej}), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("record")
    p.add_argument("--market-id", required=True)
    p.add_argument("--outcome", required=True, help="exact outcome name, e.g. Yes")
    p.add_argument("--est-prob", type=float, required=True,
                   help="agent's honest probability, formed before reading the price")
    p.add_argument("--category", required=True,
                   help="agent-assigned category, e.g. earnings/soccer/esports/news")
    p.add_argument("--method", required=True, choices=sorted(LANES),
                   help="lane whose method produced est_prob (config/lanes.json); "
                        "the engine fits and trades each lane separately")
    p.add_argument("--skip-reason", default="engine",
                   help="optional disposition note; trading is decided by "
                        "core/ledger.py place --forecast-id (the engine)")
    p.add_argument("--supersede", action="store_true",
                   help="replace this market+outcome's live open forecast with a "
                        "materially changed read (links the rows; the old one is "
                        "graded in the revised-away slice, not the headline stats)")
    p.add_argument("--confirm-extreme", action="store_true",
                   help="required when |est_prob - mid| > "
                        f"{EXTREME_DISAGREEMENT}: confirms the extreme "
                        "disagreement is deliberate, not an inverted outcome side")
    p.add_argument("--fit-score", type=int, default=None, help="playbook fit score 0-5")
    p.add_argument("--note", default="", help="one line of context (optional)")
    p.add_argument("--strategy-rev", default="", help="git rev of strategy/ used")
    sub.add_parser("record-batch",
                   help="record many forecasts: one JSON spec per stdin line")
    sub.add_parser("status")
    args = ap.parse_args()

    rows = read_forecasts()
    if args.cmd == "record-batch":
        cmd_record_batch(rows)
    elif args.cmd == "status":
        cmd_status(rows)
    else:
        cmd_record(args, rows)


if __name__ == "__main__":
    main()
