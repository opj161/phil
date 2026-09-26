#!/usr/bin/env python3
"""Decision engine: the ONE rule that turns a recorded forecast into a trade.

PROTECTED CORE — the trading agent must not edit files under core/.

core/ledger.py (paper placement on live books), core/replay.py (the same rule
over recorded books, point-in-time) and core/real.py (revalidation before a
real twin) all call this module. Pure functions, no I/O: callers fetch books
and fees and pass them in, so every decision is reproducible from its inputs.

The rule (Phil v2, 2026-09-26):
  1. Only lanes with status paper|live trade (config/lanes.json).
  2. The traded probability is the market mid moved toward the lane's
     estimate by the lane's weight: p_trade = mid + lam * (p_raw - mid).
     lam is fitted per lane from settled forecasts whose outcome was KNOWN
     before the decision (fit_lambda). Raw disagreement with the market has
     been overconfident (settled forecasts put ~79% weight on the market
     overall), so each method gets exactly the weight its own history
     earns. Below lambda_min_events settled events a paper lane trades at
     the protected cold-start prior (lane_lambda), a live lane not at all.
  3. Both sides are candidates, each filled by walking its OWN ask book for
     the stake (VWAP). net_edge = prob_side - vwap - taker fee per share,
     fee = rate * (p * (1 - p)) ** exponent (Polymarket, per market terms).
  4. Trade the side with the larger net_edge if it clears min_net_edge, is
     not implausibly large (max_net_edge: a probable mapping or stale-input
     error) and every protected check passes; otherwise return why not.
"""
import datetime as dt
import hashlib
import pathlib
import re

ENGINE_REV = hashlib.sha1(pathlib.Path(__file__).read_bytes()).hexdigest()[:8]
TRADEABLE = ("paper", "live")


def parse_ts(value):
    if not value:
        return None
    t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def fee_per_share(price, fee):
    """Taker fee in USD per share bought at `price` under market terms `fee`."""
    if not fee or not fee.get("rate"):
        return 0.0
    return fee["rate"] * (price * (1 - price)) ** fee.get("exponent", 1.0)


def vwap_fill(asks, usd):
    """Walk an ask book [(price, size)] best-first to spend `usd`."""
    spent = shares = 0.0
    for price, size in asks:
        if spent >= usd - 1e-9:
            break
        take = min(usd - spent, price * size)
        spent += take
        shares += take / price
    return {"vwap": round(spent / shares, 6) if shares else None,
            "shares": round(shares, 4), "spent": round(spent, 4),
            "unfilled_usd": round(usd - spent, 4)}


def method_of(row):
    """Lane of a forecast or bet; legacy rows carry a backfilled guess."""
    return row.get("method") or row.get("method_inferred") or "explore"


def event_of(row):
    """Independence unit: sibling markets on one event are one observation."""
    return str(row.get("event_id") or row.get("market_id"))


def known_ts(row, lag_hours):
    """When a settled row's outcome was knowable. resolve.py writes
    noticed_ts; older rows only carry the market's close time (settled_ts),
    which runs ahead of the settlement being visible, so they get a lag."""
    t = parse_ts(row.get("noticed_ts"))
    if t:
        return t
    s = parse_ts(row.get("settled_ts"))
    return s + dt.timedelta(hours=lag_hours) if s else None


def fit_lambda(method, history, at, engine):
    """Market-shrinkage weight for `method`, from forecasts known before `at`.

    w_opt is the least-squares weight on the market mid in the blend
    w * mid + (1 - w) * est over the lane's settled, non-superseded forecasts;
    lam = clip(1 - w_opt, 0, 1) shrunk by n / (n + k) over n distinct events.
    """
    lag = engine["legacy_known_lag_hours"]
    rows = []
    for r in history:
        if (method_of(r) != method or r.get("status") not in ("won", "lost")
                or r.get("superseded_by") or r.get("market_prob_at_record") is None):
            continue
        k = known_ts(r, lag)
        if k is not None and k < at:
            rows.append(r)
    n = len({event_of(r) for r in rows})
    out = {"lam": 0.0, "n_events": n, "n_rows": len(rows), "w_opt": None}
    if n < engine["lambda_min_events"]:
        return out
    num = den = 0.0
    for r in rows:
        e, m = r["est_prob"], r["market_prob_at_record"]
        y = 1.0 if r["status"] == "won" else 0.0
        num += (m - e) * (y - e)
        den += (m - e) ** 2
    if den <= 0:
        return out
    w = num / den
    lam = min(1.0, max(0.0, 1.0 - w)) * n / (n + engine["lambda_shrink_k"])
    out.update(w_opt=round(w, 4), lam=round(lam, 4))
    return out


def lane_lambda(method, status, history, at, engine):
    """The lambda the engine trades a lane at: the fitted value once the lane
    has lambda_min_events settled events, else (paper lanes only) the
    protected cold-start prior, so a new lane's paper forward record can
    begin. Live and forecast-only lanes never get the prior."""
    fit = fit_lambda(method, history, at, engine)
    fit["source"] = "fitted"
    if fit["n_events"] < engine["lambda_min_events"]:
        if status == "paper":
            fit.update(lam=engine["lambda_prior_paper"], source="paper_prior")
        else:
            fit["source"] = "insufficient_events"
    return fit


def _reject(reason, **ctx):
    return {"trade": False, "reason": reason, "engine_rev": ENGINE_REV, **ctx}


def decide(fc, quotes, fee, now, portfolio, lane_status, lam, cfg):
    """Decide one forecast.

    fc          forecast row: est_prob is P(fc["outcome"]).
    quotes      {"yes": side, "no": side|None}; "yes" is fc's outcome token,
                "no" its complement. side = {"outcome", "token_id",
                "bids": [(p, s)] best-first, "asks": [(p, s)] best-first}.
    fee         pmapi.fee_schedule() dict.
    portfolio   {"open": [open ledger rows], "recent": [rows placed in the
                last hour], "cash": float}.
    lane_status config/lanes.json status of method_of(fc).
    lam         fit_lambda(...)["lam"].
    cfg         protected engine block plus: stake_usd, min_net_edge,
                banned (compiled patterns), min_minutes_to_resolution,
                min_entry_price, max_entry_price, max_open_positions.
    """
    stake = cfg["stake_usd"]
    if lane_status not in TRADEABLE:
        return _reject("lane_not_tradeable", lane_status=lane_status)
    if lam <= 0:
        return _reject("lambda_zero")
    end = parse_ts(fc.get("end_date"))
    if end is None or (end - now).total_seconds() < 60 * cfg["min_minutes_to_resolution"]:
        return _reject("market_ends_too_soon", end_date=fc.get("end_date"))
    if any(p.search(fc.get("question") or "") for p in cfg["banned"]):
        return _reject("banned_question")
    if len(portfolio["open"]) >= cfg["max_open_positions"]:
        return _reject("max_open_positions")
    if any(r["market_id"] == fc["market_id"] for r in portfolio["open"]):
        return _reject("already_positioned_on_market")
    if len(portfolio["recent"]) >= cfg["max_new_positions_per_hour"]:
        return _reject("hourly_position_cap")
    event = event_of(fc)
    event_stake = sum(r["stake_usd"] for r in portfolio["open"] if event_of(r) == event)
    if event_stake + stake > cfg["max_stake_per_event_usd"] + 1e-9:
        return _reject("event_stake_cap", event_stake=event_stake)

    yes = quotes["yes"]
    if not yes["bids"] or not yes["asks"]:
        return _reject("no_two_sided_book")
    bid, ask = yes["bids"][0][0], yes["asks"][0][0]
    spread = round(ask - bid, 4)
    mid = (bid + ask) / 2
    p_trade = min(0.999, max(0.001, mid + lam * (fc["est_prob"] - mid)))

    lo = max(cfg["min_price"], cfg["min_entry_price"])
    hi = min(cfg["max_price"], cfg["max_entry_price"])
    sides = []
    for name, side, prob, raw in (("yes", yes, p_trade, fc["est_prob"]),
                                  ("no", quotes.get("no"), 1 - p_trade, 1 - fc["est_prob"])):
        cand = {"side": name, "prob": round(prob, 4), "p_raw": round(raw, 4)}
        sides.append(cand)
        if not side or not side["asks"]:
            cand["skip"] = "no_asks"
            continue
        fill = vwap_fill(side["asks"], stake)
        cand.update(outcome=side["outcome"], token_id=side["token_id"],
                    best_ask=side["asks"][0][0],
                    best_bid=side["bids"][0][0] if side["bids"] else None, **fill)
        if fill["unfilled_usd"] > 0.01 * stake:
            cand["skip"] = "insufficient_depth"
            continue
        if fill["vwap"] - side["asks"][0][0] > cfg["max_vwap_slippage"]:
            cand["skip"] = "slippage"
            continue
        if not lo <= fill["vwap"] <= hi:
            cand["skip"] = "price_out_of_bounds"
            continue
        fps = fee_per_share(fill["vwap"], fee)
        cand["fee_per_share"] = round(fps, 6)
        cand["net_edge"] = round(prob - fill["vwap"] - fps, 4)
    ok = [c for c in sides if "net_edge" in c]
    best = max(ok, key=lambda c: c["net_edge"]) if ok else None
    ctx = {"mid": round(mid, 4), "spread": spread, "lam": lam,
           "p_trade": round(p_trade, 4), "sides": sides}
    if spread > cfg["max_spread"]:
        # judged after pricing both sides, so the decision log shows what the
        # cap cost (best net edge of the book it refused)
        return _reject("wide_spread", **ctx)
    if best is None or best["net_edge"] < cfg["min_net_edge"]:
        return _reject("edge_below_min", min_net_edge=cfg["min_net_edge"], **ctx)
    if best["net_edge"] > cfg["max_net_edge"]:
        # an edge this large after shrinkage is far likelier a wrong mapping,
        # a stale input or a wrong-day match than a real mispricing
        return _reject("edge_implausible", max_net_edge=cfg["max_net_edge"], **ctx)
    fee_usd = round(best["shares"] * best["fee_per_share"], 4)
    if stake + fee_usd > portfolio["cash"]:
        return _reject("insufficient_cash", **ctx)
    return {"trade": True, "engine_rev": ENGINE_REV, "stake_usd": stake,
            "fee_usd": fee_usd, "event_id": event, **ctx, **{
                k: best[k] for k in ("side", "outcome", "token_id", "prob", "p_raw",
                                     "vwap", "shares", "best_ask", "best_bid",
                                     "fee_per_share", "net_edge")}}


def engine_cfg(protected, risk):
    """Merge the protected engine bounds with the agent's risk.json knobs.
    The agent may only tighten: min_net_edge is floored, stake is capped."""
    eng = dict(protected["engine"])
    eng.update(
        stake_usd=min(float(risk.get("stake_usd", 5.0)), protected["max_stake_usd"]),
        min_net_edge=max(float(risk.get("min_net_edge", 0.0)), eng["min_net_edge_floor"]),
        banned=[re.compile(p, re.I) for p in protected["banned_question_patterns"]],
        min_minutes_to_resolution=protected["min_minutes_to_resolution"],
        min_entry_price=protected["min_entry_price"],
        max_entry_price=protected["max_entry_price"],
        max_open_positions=protected["max_open_positions"],
    )
    return eng
