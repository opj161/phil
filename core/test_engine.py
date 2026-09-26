#!/usr/bin/env python3
"""Tests for the decision engine and its evaluators. Offline, stdlib only.

PROTECTED CORE — the trading agent must not edit files under core/.

Run: python3 core/test_engine.py   (CI runs it on every push)
"""
import datetime as dt
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import decision  # noqa: E402
import replay  # noqa: E402
import stats  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROTECTED = json.loads((ROOT / "config" / "protected.json").read_text())
LANES = json.loads((ROOT / "config" / "lanes.json").read_text())["lanes"]
NOW = dt.datetime(2026, 9, 26, 12, 0, tzinfo=dt.timezone.utc)
CFG = decision.engine_cfg(PROTECTED, {"stake_usd": 5.0, "min_net_edge": 0.02})


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def side(outcome, bid, ask, size=1e6):
    return {"outcome": outcome, "token_id": outcome.lower(),
            "bids": [(bid, size)] if bid is not None else [],
            "asks": [(ask, size)] if ask is not None else []}


def quotes(bid=0.49, ask=0.50, no_bid=0.50, no_ask=0.51, size=1e6):
    return {"yes": side("Yes", bid, ask, size), "no": side("No", no_bid, no_ask, size)}


def fc(est=0.60, **kw):
    row = {"id": "f1", "market_id": "m1", "event_id": "e1", "outcome": "Yes",
           "question": "Will WTI hit (HIGH) $100 in October?", "est_prob": est,
           "end_date": iso(NOW + dt.timedelta(days=3)), "method": "barrier"}
    row.update(kw)
    return row


def empty_portfolio(**kw):
    p = {"open": [], "recent": [], "cash": 1000.0}
    p.update(kw)
    return p


def run(f=None, q=None, fee=None, portfolio=None, status="paper", lam=1.0, cfg=CFG):
    return decision.decide(f or fc(), q or quotes(), fee or {"rate": 0.0}, NOW,
                           portfolio or empty_portfolio(), status, lam, cfg)


def test_fee_formula():
    # Polymarket help center example: 5% category at 50c -> 1.25c per share
    assert abs(decision.fee_per_share(0.5, {"rate": 0.05, "exponent": 1}) - 0.0125) < 1e-12
    assert decision.fee_per_share(0.5, {"rate": 0.0}) == 0.0
    assert abs(decision.fee_per_share(0.9, {"rate": 0.04}) - 0.0036) < 1e-12


def test_vwap_walk_and_partial_fill():
    f = decision.vwap_fill([(0.40, 5), (0.42, 100)], 5.0)
    assert abs(f["spent"] - 5.0) < 1e-9 and f["unfilled_usd"] == 0
    assert abs(f["shares"] - (5 + 3 / 0.42)) < 1e-3
    assert abs(f["vwap"] - 5.0 / (5 + 3 / 0.42)) < 1e-5
    p = decision.vwap_fill([(0.40, 5)], 5.0)
    assert abs(p["unfilled_usd"] - 3.0) < 1e-9


def hist_row(i, est, mid, won, recorded, settled, noticed=None, method="barrier"):
    r = {"id": f"h{i}", "event_id": f"ev{i}", "market_id": f"mk{i}", "method": method,
         "est_prob": est, "market_prob_at_record": mid, "ts": iso(recorded),
         "status": "won" if won else "lost", "settled_ts": iso(settled)}
    if noticed:
        r["noticed_ts"] = iso(noticed)
    return r


def test_lambda_point_in_time_no_leakage():
    eng = PROTECTED["engine"]
    past = NOW - dt.timedelta(days=5)
    base = [hist_row(i, 0.8, 0.5, True, past, past, past) for i in range(25)]
    fit = decision.fit_lambda("barrier", base, NOW, eng)
    assert fit["n_events"] == 25 and fit["lam"] > 0
    expected = 1.0 * 25 / (25 + eng["lambda_shrink_k"])  # w_opt < 0 clips to lam_raw 1
    assert abs(fit["lam"] - round(expected, 4)) < 1e-9
    # A row RECORDED before now but whose outcome was only noticed AFTER now
    # must not reach the fit (the fold-replay leak this engine replaces).
    leak = hist_row(99, 0.1, 0.5, True, past, NOW - dt.timedelta(hours=1),
                    noticed=NOW + dt.timedelta(hours=2))
    assert decision.fit_lambda("barrier", base + [leak], NOW, eng) == fit
    # A legacy row (no noticed_ts) settled 1h ago is not yet known under the lag.
    legacy = hist_row(98, 0.1, 0.5, True, past, NOW - dt.timedelta(hours=1))
    assert decision.fit_lambda("barrier", base + [legacy], NOW, eng) == fit
    # Superseded rows and other lanes never count.
    sup = dict(hist_row(97, 0.1, 0.5, True, past, past, past), superseded_by="x")
    other = hist_row(96, 0.1, 0.5, True, past, past, past, method="devig")
    assert decision.fit_lambda("barrier", base + [sup, other], NOW, eng) == fit


def test_lambda_zero_below_min_events_and_sibling_clustering():
    eng = PROTECTED["engine"]
    past = NOW - dt.timedelta(days=5)
    rows = [dict(hist_row(i, 0.8, 0.5, True, past, past, past), event_id="one-event")
            for i in range(50)]
    fit = decision.fit_lambda("barrier", rows, NOW, eng)
    assert fit["n_events"] == 1 and fit["lam"] == 0.0  # 50 siblings are one event


def test_cold_start_prior_only_for_paper_lanes():
    eng = PROTECTED["engine"]
    past = NOW - dt.timedelta(days=5)
    few = [hist_row(i, 0.8, 0.5, True, past, past, past) for i in range(5)]
    assert decision.lane_lambda("barrier", "paper", few, NOW, eng)["lam"] == eng["lambda_prior_paper"]
    assert decision.lane_lambda("barrier", "live", few, NOW, eng)["lam"] == 0.0
    assert decision.lane_lambda("barrier", "forecast_only", few, NOW, eng)["lam"] == 0.0
    # past the threshold the fit rules, even when it is 0 (no skill stops the lane)
    bad = [hist_row(i, 0.9, 0.5, False, past, past, past) for i in range(30)]
    fit = decision.lane_lambda("barrier", "paper", bad, NOW, eng)
    assert fit["source"] == "fitted" and fit["lam"] == 0.0


def test_side_choice():
    d = run(fc(est=0.60))
    assert d["trade"] and d["side"] == "yes" and d["outcome"] == "Yes"
    assert abs(d["net_edge"] - round(0.60 - 0.50, 4)) < 1e-9
    d = run(fc(est=0.35))
    assert d["trade"] and d["side"] == "no" and d["outcome"] == "No"
    assert abs(d["net_edge"] - round(0.65 - 0.51, 4)) < 1e-9


def test_shrinkage_and_fee_reduce_edge():
    # lam 0.1: p_trade = 0.495 + 0.1 * (0.60 - 0.495) = 0.5055 -> edge 0.0055 < 0.02
    d = run(fc(est=0.60), lam=0.1)
    assert not d["trade"] and d["reason"] == "edge_below_min"
    # a 10-point edge survives a 5% fee (1.25c/share at 50c)
    d = run(fc(est=0.60), fee={"rate": 0.05, "exponent": 1})
    assert d["trade"] and abs(d["net_edge"] - round(0.60 - 0.50 - 0.0125, 4)) < 1e-9
    assert abs(d["fee_usd"] - round(d["shares"] * 0.0125, 4)) < 1e-9


def test_rejections():
    cases = [
        (dict(status="forecast_only"), "lane_not_tradeable"),
        (dict(lam=0.0), "lambda_zero"),
        (dict(f=fc(end_date=iso(NOW + dt.timedelta(minutes=5)))), "market_ends_too_soon"),
        (dict(f=fc(question="Bitcoin Up or Down on September 27?")), "banned_question"),
        (dict(q=quotes(bid=0.40, ask=0.50)), "wide_spread"),
        (dict(q=quotes(bid=None)), "no_two_sided_book"),
        (dict(f=fc(est=0.51)), "edge_below_min"),
        (dict(f=fc(est=0.95)), "edge_implausible"),
        (dict(portfolio=empty_portfolio(open=[{"market_id": "m1", "stake_usd": 5.0}])),
         "already_positioned_on_market"),
        (dict(portfolio=empty_portfolio(open=[{"market_id": "m2", "event_id": "e1",
                                               "stake_usd": 10.0}])), "event_stake_cap"),
        (dict(portfolio=empty_portfolio(recent=[{}] * CFG["max_new_positions_per_hour"])),
         "hourly_position_cap"),
        (dict(portfolio=empty_portfolio(cash=1.0)), "insufficient_cash"),
    ]
    for kw, reason in cases:
        d = run(**kw)
        assert not d["trade"] and d["reason"] == reason, (reason, d.get("reason"))


def test_depth_rejects_thin_book():
    d = run(q=quotes(size=1.0), f=fc(est=0.60))  # $0.50 on the ask: cannot fill $5
    assert not d["trade"] and d["reason"] == "edge_below_min"
    assert all(s.get("skip") == "insufficient_depth" for s in d["sides"] if "skip" in s)


def test_agent_knobs_only_tighten():
    loose = decision.engine_cfg(PROTECTED, {"stake_usd": 999, "min_net_edge": 0.0})
    assert loose["stake_usd"] == PROTECTED["max_stake_usd"]
    assert loose["min_net_edge"] == PROTECTED["engine"]["min_net_edge_floor"]


def test_replay_uses_the_engine():
    """Parity: a replayed row gets exactly the decision the engine gives the
    same recorded book (the path ledger.py takes with a live book)."""
    past = NOW - dt.timedelta(days=10)
    hist = [hist_row(i, 0.8, 0.5, True, past, past, past) for i in range(30)]
    row = dict(fc(est=0.60), id="t1", ts=iso(NOW), status="won", settled_ts=iso(NOW),
               best_bid_at_record=0.49, best_ask_at_record=0.50,
               market_prob_at_record=0.495, fee_rate=0.05, fee_exponent=1.0,
               category="commodities")
    rep = replay.run(hist + [row], all_lanes=True)
    assert rep["overall"]["n_bets"] == 1
    bet = rep["bets"][0]
    lam = decision.fit_lambda("barrier", hist + [row], NOW, PROTECTED["engine"])["lam"]
    cfg = decision.engine_cfg(PROTECTED, replay.read_risk())
    direct = decision.decide(row, replay.recorded_quotes(row, cfg["stake_usd"]),
                             {"rate": 0.05, "exponent": 1.0}, NOW,
                             {"open": [], "recent": [], "cash": 1e9}, "paper", lam, cfg)
    assert direct["trade"] and bet["side"] == direct["side"]
    assert bet["net_edge"] == direct["net_edge"] and bet["lam"] == lam
    won_pnl = direct["shares"] - direct["stake_usd"] - direct["fee_usd"]
    assert abs(bet["pnl"] - round(won_pnl, 4)) < 1e-9


def test_settlement_is_net_of_fees():
    import resolve  # noqa: PLC0415
    market = {"closed": True, "outcomes": '["Yes", "No"]', "outcomePrices": '["0", "1"]',
              "closedTime": "2026-09-26 10:00:00+00"}
    won = {"outcome": "No", "shares": 5.3763, "stake_usd": 5.0, "fee_usd": 0.0245,
           "end_date": iso(NOW)}
    assert resolve.settle_against_market(won, market, NOW)
    assert won["status"] == "won" and abs(won["pnl_usd"] - round(5.3763 - 5.0 - 0.0245, 4)) < 1e-9
    assert won["noticed_ts"] == iso(NOW) and won["settled_ts"] == "2026-09-26T10:00:00Z"
    lost = {"outcome": "Yes", "shares": 60.0, "stake_usd": 5.0, "fee_usd": 0.32,
            "end_date": iso(NOW)}
    assert resolve.settle_against_market(lost, market, NOW)
    assert lost["status"] == "lost" and abs(lost["pnl_usd"] + 5.32) < 1e-9
    legacy = {"outcome": "Yes", "shares": 10.0, "stake_usd": 5.0, "end_date": iso(NOW)}
    assert resolve.settle_against_market(legacy, market, NOW) and legacy["pnl_usd"] == -5.0


def test_clustered_roi():
    bets = [{"stake": 5, "pnl": 5, "event": "a"}, {"stake": 5, "pnl": 5, "event": "a"},
            {"stake": 5, "pnl": -5, "event": "b"}]
    s = stats.clustered_roi(bets)
    assert s["n_events"] == 2 and s["n_bets"] == 3 and abs(s["roi"] - 5 / 15) < 1e-4
    assert s["top_event_share"] == 1.0


def test_lane_shapes():
    rx = {k: re.compile(v["shape_regex"]) for k, v in LANES.items() if v["shape_regex"]}
    assert rx["barrier"].search("Will WTI Crude Oil (WTI) hit (HIGH) $100 in August?")
    assert rx["barrier"].search("Will the price of Bitcoin be between $64,000 and $66,000 on August 10?")
    assert rx["barrier"].search("S&P 500 (SPY) closes above $765 on September 4?")
    assert not rx["barrier"].search("Will Tesla be the largest company?")
    assert rx["devig"].search("Chicago Cubs vs. Arizona Diamondbacks")
    assert rx["devig"].search("Will CA Talleres win on 2026-07-30?")
    assert rx["mention"].search('Will Trump say "Afford" during RNC speech?')
    assert not rx["mention"].search("Will Grüne win at least 7% of all valid second votes?")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, f in tests:
        f()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
