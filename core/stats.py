#!/usr/bin/env python3
"""Shared evaluation statistics (replay, score, gate).

PROTECTED CORE — the trading agent must not edit files under core/.

Sibling markets on one event are one observation, not several: every
uncertainty here is clustered by event, so three correlated bets on one
election cannot look like three independent wins.
"""
import math
from collections import defaultdict


def clustered_roi(bets):
    """bets: dicts with stake, pnl, event. Stake-weighted ROI with an
    event-clustered standard error (ratio estimator). lcb/ucb = roi -/+ 1 se.
    top_event_share = the largest single event's share of total positive P&L."""
    if not bets:
        return {"n_bets": 0, "n_events": 0, "staked": 0.0, "pnl": 0.0, "roi": 0.0,
                "se": None, "lcb": 0.0, "ucb": 0.0, "top_event_share": None}
    by_event = defaultdict(lambda: [0.0, 0.0])
    for b in bets:
        by_event[b["event"]][0] += b["stake"]
        by_event[b["event"]][1] += b["pnl"]
    staked = sum(s for s, _ in by_event.values())
    pnl = sum(p for _, p in by_event.values())
    roi = pnl / staked if staked else 0.0
    k = len(by_event)
    if k > 1:
        resid = sum((p - roi * s) ** 2 for s, p in by_event.values())
        se = math.sqrt(resid * k / (k - 1)) / staked
    else:
        se = None
    gains = [p for _, p in by_event.values() if p > 0]
    return {
        "n_bets": len(bets), "n_events": k, "staked": round(staked, 2),
        "pnl": round(pnl, 2), "roi": round(roi, 4),
        "se": round(se, 4) if se is not None else None,
        "lcb": round(roi - se, 4) if se is not None else round(roi - 1.0, 4),
        "ucb": round(roi + se, 4) if se is not None else round(roi + 1.0, 4),
        "top_event_share": round(max(gains) / sum(gains), 3) if gains and pnl > 0 else None,
    }


def brier_delta(rows, est_key="est_prob", mkt_key="market_prob_at_record"):
    """Mean Brier(est) - Brier(market) over settled rows; negative = beat the market."""
    rows = [r for r in rows if r.get(mkt_key) is not None]
    if not rows:
        return None
    ys = [1.0 if r["status"] == "won" else 0.0 for r in rows]
    return round(sum((r[est_key] - y) ** 2 - (r[mkt_key] - y) ** 2
                     for r, y in zip(rows, ys)) / len(rows), 4)
