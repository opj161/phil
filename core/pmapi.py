"""Polymarket API helpers (read-only). Stdlib only.

PROTECTED CORE — the trading agent must not edit files under core/.

CLI (read-only, for checking a market's resolution rules in a cycle):
  python3 core/pmapi.py rules <market_id>   question, end date, event, fee
                                            terms, outcomes and the full rules
  python3 core/pmapi.py book <market_id>    top 5 levels of each outcome book
"""
import json
import time
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "pearl-explorations-paper-trader/0.1"}


def get_json(url, params=None, retries=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as e:  # noqa: BLE001 — retry then surface
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} tries: {last_err}")


def gamma_markets(**params):
    return get_json(f"{GAMMA}/markets", params)


def gamma_market(market_id):
    return get_json(f"{GAMMA}/markets/{market_id}")


def clob_book(token_id):
    return get_json(f"{CLOB}/book", {"token_id": token_id})


def best_prices(token_id):
    """Return (best_bid, best_ask) for a CLOB token, None if side empty."""
    book = clob_book(token_id)
    bids = [float(b["price"]) for b in book.get("bids", [])]
    asks = [float(a["price"]) for a in book.get("asks", [])]
    return (max(bids) if bids else None, min(asks) if asks else None)


def book_levels(token_id):
    """Full book for a CLOB token: {"bids": [(price, size)] best-first,
    "asks": [(price, size)] best-first}. Sizes are shares."""
    book = clob_book(token_id)
    bids = sorted(((float(b["price"]), float(b["size"])) for b in book.get("bids", [])),
                  reverse=True)
    asks = sorted((float(a["price"]), float(a["size"])) for a in book.get("asks", []))
    return {"bids": bids, "asks": asks}


def fee_schedule(market):
    """Taker fee terms of a gamma market record, as the engine consumes them.

    Polymarket (help center, Trading Fees): fee = shares * rate * p * (1 - p),
    takers only, on fee-enabled markets. gamma carries the per-market terms
    in `feesEnabled` + `feeSchedule {rate, exponent, takerOnly, rebateRate}`;
    a market without them is fee-free.
    """
    sched = market.get("feeSchedule") or {}
    enabled = bool(market.get("feesEnabled")) and bool(sched)
    return {
        "fees_enabled": enabled,
        "rate": float(sched.get("rate") or 0) if enabled else 0.0,
        "exponent": float(sched.get("exponent") or 1) if enabled else 1.0,
        "fee_type": market.get("feeType"),
    }


def event_id(market):
    """The gamma event a market belongs to (sibling markets share it).

    Only the LIST endpoint (/markets?id=) carries `events`; the single-market
    endpoint gamma_market() does not, so a record from it falls back to a
    list lookup by id (open markets first, then closed ones)."""
    events = market.get("events") or []
    if not events and market.get("id"):
        for closed in ("false", "true"):
            try:
                rows = gamma_markets(id=market["id"], closed=closed)
            except RuntimeError:
                rows = []
            if rows:
                events = rows[0].get("events") or []
                break
    return str(events[0].get("id")) if events and events[0].get("id") else None


def market_tokens(market):
    """Map outcome name -> clob token id for a gamma market record."""
    outcomes = json.loads(market.get("outcomes", "[]"))
    token_ids = json.loads(market.get("clobTokenIds", "[]"))
    return dict(zip(outcomes, token_ids))


def _cli(argv):
    import sys
    if len(argv) != 2 or argv[0] not in ("rules", "book"):
        sys.exit("usage: python3 core/pmapi.py rules|book <market_id>")
    m = gamma_market(argv[1])
    if argv[0] == "rules":
        print(json.dumps({"market_id": m.get("id"), "question": m.get("question"),
                          "end_date": m.get("endDate"), "closed": m.get("closed"),
                          "event_id": event_id(m), "outcomes": list(market_tokens(m)),
                          "fees": fee_schedule(m)}, indent=2))
        print("\n" + (m.get("description") or "(no description)"))
    else:
        for outcome, token in market_tokens(m).items():
            b = book_levels(token)
            print(json.dumps({"outcome": outcome, "bids": b["bids"][:5], "asks": b["asks"][:5]}))


if __name__ == "__main__":
    import sys
    _cli(sys.argv[1:])
