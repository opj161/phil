#!/usr/bin/env python3
"""Lane router and mechanistic pricers — AGENT-EDITABLE (my main tool surface).

Usage:
  python3 core/scan.py --hours 720 --limit 800 2>/dev/null \
    | python3 strategy/tools/lanes.py run [--odds] [--max-sports 2] > work/lanes.jsonl
  python3 strategy/tools/lanes.py summary < work/lanes.jsonl
  python3 strategy/tools/lanes.py plan < work/lanes.jsonl > work/plan.jsonl

`run` routes every scanned market into a lane by the protected shape regexes
(config/lanes.json, first match wins in the order barrier, devig, mention)
and prices what it can:

  barrier  underlying + level(s) + mode parsed from the question; spot and a
           SOURCED vol (implied-vol index where one exists: Deribit DVOL for
           BTC/ETH, ^OVX, ^GVZ, ^VIX, ^VXN; else 30-day realized) fetched
           live; priced by strategy/tools/touch.py (touch / above / below /
           between). p at 0.75x and 1.25x vol is reported as the robustness
           band.
  devig    with --odds only (each sport costs 1 odds-api credit; core/odds.py
           enforces the monthly budget): h2h consensus of every bookmaker,
           power-devigged per book (strategy/tools/devig.py), median across
           books, matched to the Polymarket market by team names and date.
           Moneylines, "Will X win on DATE?" and draws; spreads/totals are
           left unpriced for now.
  mention  listed for base-rate research (no automatic price).

Output: one JSON line per routed market. model_p is P(outcome) for the
"outcome" field (the market's first outcome). `series` is the question with
numbers blanked: strategy/lane-maps.json records series whose resolution
rules I have verified against the model's inputs (price source, time
window, touch vs close); `mapping_verified` says whether this market's
series is in there. A model_p is a forecast INPUT: I still read the rules,
then record with core/forecast.py --method <lane> and let the engine decide.
"""
import argparse
import datetime as dt
import json
import math
import pathlib
import re
import statistics
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "strategy" / "tools"))
import devig  # noqa: E402
import touch  # noqa: E402

LANES = json.loads((ROOT / "config" / "lanes.json").read_text())["lanes"]
ROUTE_ORDER = ("barrier", "devig", "mention")
# A clean sharp-book devig lands 0-5c from a tight Polymarket book (v1: ~40
# markets at 0-2c); bigger gaps were stale/scraped/wrong-day lines. Barrier
# gaps are wider by nature (retail overprices far touches).
LARGE_GAP = {"barrier": 0.20, "barrier_equity": 0.20, "devig": 0.08, "mention": 1.0}
MAPS_PATH = ROOT / "strategy" / "lane-maps.json"
UA = {"User-Agent": "Mozilla/5.0 (phil-lanes)"}

# ---------------------------------------------------------------- barrier --

# (question regex, underlying key). First match wins: keep specific before general.
UNDERLYINGS = [
    (r"\(spy\)|\bspy\b", "SPY"), (r"s&p ?500|\bspx\b", "SPX"),
    (r"\(qqq\)|\bqqq\b", "QQQ"), (r"nasdaq|\bndx\b", "NDX"),
    (r"\bbitcoin\b|\bbtc\b", "BTC"), (r"\bethereum\b|\beth\b", "ETH"),
    (r"\bsolana\b|\bsol\b", "SOL"), (r"\bxrp\b", "XRP"),
    (r"\bchainlink\b|\blink\b", "LINK"),
    (r"\bwti\b|crude oil", "WTI"), (r"\bbrent\b", "BRENT"),
    (r"\bgold\b|\bxauusd\b", "GOLD"), (r"\bsilver\b|\bxagusd\b", "SILVER"),
    (r"natural gas|\(ng\)", "NG"),
]
# spot: (kind, symbol); vol: (kind, symbol). Kinds: coinbase, yahoo,
# deribit_dvol, yahoo_index (vol index in % points), *_realized (30d, from
# daily closes).
SOURCES = {
    "BTC": (("coinbase", "BTC-USD"), ("deribit_dvol", "BTC")),
    "ETH": (("coinbase", "ETH-USD"), ("deribit_dvol", "ETH")),
    "SOL": (("coinbase", "SOL-USD"), ("coinbase_realized", "SOL-USD")),
    "XRP": (("coinbase", "XRP-USD"), ("coinbase_realized", "XRP-USD")),
    "LINK": (("coinbase", "LINK-USD"), ("coinbase_realized", "LINK-USD")),
    "WTI": (("yahoo", "CL=F"), ("yahoo_index", "^OVX")),
    "BRENT": (("yahoo", "BZ=F"), ("yahoo_index", "^OVX")),
    "GOLD": (("yahoo", "GC=F"), ("yahoo_index", "^GVZ")),
    "SILVER": (("yahoo", "SI=F"), ("yahoo_realized", "SI=F")),
    "NG": (("yahoo", "NG=F"), ("yahoo_realized", "NG=F")),
    "SPY": (("yahoo", "SPY"), ("yahoo_index", "^VIX")),
    "SPX": (("yahoo", "^GSPC"), ("yahoo_index", "^VIX")),
    "QQQ": (("yahoo", "QQQ"), ("yahoo_index", "^VXN")),
    "NDX": (("yahoo", "^NDX"), ("yahoo_index", "^VXN")),
}
LEVEL = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*([kKmMbB])?\b")
TERMINAL = re.compile(r"\b(close|closes|closed|settle|settles|finish|finishes|end|ends|be|is|"
                      r"trade|trades)\s+(above|below|over|under|between|greater than|"
                      r"less than|higher than|lower than)\b", re.I)
_cache = {}


def get_json(url):
    if url not in _cache:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            _cache[url] = json.load(r)
    return _cache[url]


def yahoo(symbol, rng="3mo"):
    sym = urllib.request.quote(symbol)
    d = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d")
    r = d["chart"]["result"][0]
    closes = [c for c in r["indicators"]["quote"][0]["close"] if c]
    return r["meta"]["regularMarketPrice"], closes


def realized_vol(closes, periods_per_year):
    rets = [math.log(b / a) for a, b in zip(closes[-31:], closes[-30:])]
    return statistics.stdev(rets) * math.sqrt(periods_per_year)


def fetch_spot(kind, symbol):
    if kind == "coinbase":
        return float(get_json(f"https://api.exchange.coinbase.com/products/{symbol}/ticker")["price"])
    return float(yahoo(symbol)[0])


def fetch_vol(kind, symbol):
    """(annualized vol fraction, source label)."""
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    if kind == "deribit_dvol":
        now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
        d = get_json("https://www.deribit.com/api/v2/public/get_volatility_index_data"
                     f"?currency={symbol}&resolution=3600&start_timestamp={now - 6 * 3600 * 1000}"
                     f"&end_timestamp={now}")
        return d["result"]["data"][-1][4] / 100, f"Deribit DVOL {symbol} {today}"
    if kind == "yahoo_index":
        return float(yahoo(symbol, "5d")[0]) / 100, f"{symbol} implied vol index {today}"
    if kind == "coinbase_realized":
        rows = get_json(f"https://api.exchange.coinbase.com/products/{symbol}/candles?granularity=86400")
        closes = [r[4] for r in sorted(rows)]
        return realized_vol(closes, 365), f"Coinbase {symbol} 30d realized vol {today}"
    if kind == "yahoo_realized":
        return realized_vol(yahoo(symbol)[1], 252), f"Yahoo {symbol} 30d realized vol {today}"
    raise ValueError(kind)


def business_days(start, end):
    """Weekday time between two datetimes, in days (fractional at the ends).
    Holidays are ignored: a small overstatement of trading time."""
    total, t = 0.0, start
    while t < end:
        nxt = min(end, (t + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
        if t.weekday() < 5:
            total += (nxt - t).total_seconds() / 86400
        t = nxt
    return total


def levels(q):
    out = []
    for num, suffix in LEVEL.findall(q):
        v = float(num.replace(",", ""))
        v *= {"k": 1e3, "m": 1e6, "b": 1e9}.get((suffix or "").lower(), 1)
        out.append(v)
    return out


TICKER = re.compile(r"\(([A-Z]{1,5})\)")


def underlying_of(q):
    """(key, lane): a mapped index/commodity/crypto, else a parenthesized
    stock/ETF ticker (barrier_equity lane, Yahoo spot + 30d realized vol)."""
    ql = q.lower()
    und = next((k for rx, k in UNDERLYINGS if re.search(rx, ql)), None)
    if und:
        return und, "barrier"
    t = TICKER.search(q)
    if t:
        SOURCES.setdefault(t.group(1), (("yahoo", t.group(1)), ("yahoo_realized", t.group(1))))
        return t.group(1), "barrier_equity"
    return None, None


def parse_barrier(q):
    """(underlying, mode, level, upper) or a reason string."""
    und, _ = underlying_of(q)
    if und is None:
        return "no_known_underlying"
    lv = levels(q)
    if not lv:
        return "no_level"
    term = TERMINAL.search(q)
    if term:
        word = term.group(2).lower()
        if word == "between":
            return (und, "between", lv[0], lv[1]) if len(lv) >= 2 else "between_needs_two_levels"
        mode = "above" if word in ("above", "over", "greater than", "higher than") else "below"
        return und, mode, lv[0], None
    return und, "touch", lv[0], None


def price_barrier(m, now):
    parsed = parse_barrier(m["question"])
    if isinstance(parsed, str):
        return {"unpriced": parsed}
    und, mode, level, upper = parsed
    end = dt.datetime.fromisoformat(m["end_date"].replace("Z", "+00:00"))
    days = (end - now).total_seconds() / 86400
    floor = LANES[underlying_of(m["question"])[1]].get("min_days_to_end", 0)
    if days < floor:
        # the lane only has skill at 3+ days; 30-day implied vol also misstates
        # the next few hours (config/lanes.json barrier description)
        return {"unpriced": f"horizon_below_{floor}d"}
    (sk, ss), (vk, vs) = SOURCES[und]
    try:
        spot = fetch_spot(sk, ss)
        vol, vol_source = fetch_vol(vk, vs)
    except Exception as e:  # noqa: BLE001 - a data outage leaves the row unpriced
        return {"unpriced": f"data_error: {type(e).__name__}: {str(e)[:80]}"}
    if not 0.3 < level / spot < 3:
        return {"unpriced": f"scale_mismatch (level {level} vs {und} spot {spot})"}
    ql = m["question"].lower()
    if mode == "touch":
        down = "dip" in ql or "(low)" in ql or "low)" in ql
        if (down and spot <= level) or (not down and spot >= level):
            return {"unpriced": "already_through_barrier"}
    # Time must be on the vol's own clock (a units fix the 2026-09-26 test
    # cycle proposed): realized vol from daily closes of an exchange-traded
    # underlying is per trading day (x sqrt 252), so its T counts weekdays
    # over 252; implied-vol indices (calendar-annualized) and crypto (trades
    # every day) use calendar days over 365.
    if vk == "yahoo_realized":
        t_days, year_days = business_days(now, end), 252.0
    else:
        t_days, year_days = days, 365.0
    if t_days <= 0:
        return {"unpriced": "no_trading_time_left"}
    p = lambda v: touch.price(mode, spot, level, t_days, v, upper, year_days)  # noqa: E731
    return {"model_p": round(p(vol), 4),
            "band": [round(p(vol * 0.75), 4), round(p(vol * 1.25), 4)],
            "inputs": {"underlying": und, "mode": mode, "level": level, "upper": upper,
                       "spot": spot, "spot_source": f"{sk} {ss}", "ann_vol": round(vol, 4),
                       "vol_source": vol_source, "days": round(days, 3),
                       "t_days": round(t_days, 3), "year_days": year_days}}

# ------------------------------------------------------------------ devig --

# Polymarket slug prefix -> the-odds-api sport key (extend as leagues appear).
SLUG_SPORT = {
    "nfl": "americanfootball_nfl", "cfb": "americanfootball_ncaaf",
    "mlb": "baseball_mlb", "nba": "basketball_nba", "wnba": "basketball_wnba",
    "nhl": "icehockey_nhl", "ufc": "mma_mixed_martial_arts",
    "epl": "soccer_epl", "lal": "soccer_spain_la_liga", "es2": "soccer_spain_segunda_division",
    "bun": "soccer_germany_bundesliga", "sea": "soccer_italy_serie_a",
    "fl1": "soccer_france_ligue_one", "ucl": "soccer_uefa_champs_league",
    "uel": "soccer_uefa_europa_league", "unl": "soccer_uefa_nations_league",
    "mls": "soccer_usa_mls", "mex": "soccer_mexico_ligamx", "bra": "soccer_brazil_campeonato",
    "arg": "soccer_argentina_primera_division", "ere": "soccer_netherlands_eredivisie",
    "por": "soccer_portugal_primeira_liga", "efl": "soccer_efl_champ",
}
STOP = {"fc", "cf", "sc", "cd", "afc", "ac", "club", "de", "the", "cp", "sv", "fk", "bk", "if"}


def norm_tokens(name):
    import unicodedata
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return {t for t in re.findall(r"[a-z0-9]+", s) if t not in STOP}


def same_team(a, b):
    ta, tb = norm_tokens(a), norm_tokens(b)
    if not ta or not tb:
        return False
    small, big = sorted((ta, tb), key=len)
    return small <= big or len(ta & tb) / len(ta | tb) >= 0.5


def consensus(event):
    """Median across books of power-devigged h2h probabilities, by outcome name."""
    per = {}
    for book in event.get("bookmakers", []):
        for mk in book.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            names = [o["name"] for o in mk["outcomes"]]
            raw = [1 / float(o["price"]) for o in mk["outcomes"]]
            if len(raw) < 2 or any(not 0 < r < 1 for r in raw):
                continue
            fair, _ = devig.power_devig(raw)
            for n, f in zip(names, fair):
                per.setdefault(n, []).append(f)
    return {n: statistics.median(v) for n, v in per.items()}, len(event.get("bookmakers", []))


def slug_date(slug):
    m = re.search(r"(20\d\d-\d\d-\d\d)", slug or "")
    return dt.date.fromisoformat(m.group(1)) if m else None


def find_event(events, teams, date):
    for ev in events:
        start = dt.datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).date()
        if date and abs((start - date).days) > 1:
            continue
        sides = [ev["home_team"], ev["away_team"]]
        if all(any(same_team(t, s) for s in sides) for t in teams):
            return ev
    return None


def price_devig(m, events):
    q, outs = m["question"], m["outcomes"]
    date = slug_date(m.get("slug"))
    if re.search(r"^spread:|\bO/U\s?\d", q, re.I):
        return {"unpriced": "line_market_not_supported"}
    draw = re.search(r"Will (.+?) vs\.? (.+?) end in a draw", q, re.I)
    win = re.search(r"Will (.+?) win on (20\d\d-\d\d-\d\d)", q, re.I)
    if draw:
        ev = find_event(events, [draw.group(1), draw.group(2)], date)
        target = "Draw"
    elif win:
        ev = find_event(events, [win.group(1)], date)
        target = win.group(1)
    elif len(outs) == 2 and outs != ["Yes", "No"]:
        ev = find_event(events, outs, date)
        target = outs[0]
    else:
        return {"unpriced": "unrecognized_sports_shape"}
    if ev is None:
        return {"unpriced": "no_matching_bookmaker_event"}
    fair, n_books = consensus(ev)
    key = next((k for k in fair if k == target or (target != "Draw" and same_team(target, k))), None)
    if key is None or n_books == 0:
        return {"unpriced": "target_not_in_book"}
    return {"model_p": round(fair[key], 4),
            "inputs": {"book_event": f"{ev['away_team']} @ {ev['home_team']}",
                       "commence": ev["commence_time"], "book_outcome": key,
                       "n_books": n_books, "fair": {k: round(v, 4) for k, v in fair.items()}}}


def load_odds(sport):
    region = "eu" if sport.startswith("soccer_") else "us"
    r = subprocess.run([sys.executable, str(ROOT / "core" / "odds.py"), "odds", sport,
                        "--region", region], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:200])
    return json.loads(r.stdout)

# ------------------------------------------------------------------- main --


def series_of(lane, m):
    """Markets sharing resolution rules. Devig: league + market shape (every
    game's rules are the same template); others: the question with numbers
    blanked."""
    q = m["question"]
    if lane == "devig":
        shape = ("draw" if re.search(r"end in a draw", q, re.I)
                 else "win" if re.search(r"\bwin on 20", q, re.I) else "moneyline")
        return f"devig:{(m.get('slug') or '?').split('-')[0]}:{shape}"
    return f"{lane}:" + re.sub(r"\d[\d,.]*", "#", q).strip()


def route(q):
    for lane in ROUTE_ORDER:
        rx = LANES.get(lane, {}).get("shape_regex")
        if rx and re.search(rx, q):
            return lane
    return None


def cmd_run(args):
    now = dt.datetime.now(dt.timezone.utc)
    try:
        maps = json.loads(MAPS_PATH.read_text()).get("series", {})
    except (FileNotFoundError, json.JSONDecodeError):
        maps = {}
    markets = [json.loads(line) for line in sys.stdin if line.strip()]
    routed = [(route(m["question"]), m) for m in markets]
    routed = [(lane, m) for lane, m in routed if lane]

    odds = {}
    if args.odds:
        # spend the budget on the sports with the most games in the next 36h:
        # bookmaker lines are sharpest, and the engine's fills freshest, near start
        by_sport = {}
        soon = now + dt.timedelta(hours=36)
        for lane, m in routed:
            if lane == "devig" and m.get("end_date"):
                sport = SLUG_SPORT.get((m.get("slug") or "").split("-")[0])
                end = dt.datetime.fromisoformat(m["end_date"].replace("Z", "+00:00"))
                if sport and end <= soon:
                    by_sport[sport] = by_sport.get(sport, 0) + 1
        for sport, _ in sorted(by_sport.items(), key=lambda kv: -kv[1])[:args.max_sports]:
            try:
                odds[sport] = load_odds(sport)
            except Exception as e:  # noqa: BLE001
                odds[sport] = e
                print(f"lanes: odds {sport} failed: {e}", file=sys.stderr)

    for lane, m in routed:
        rec = {"lane": lane, "market_id": m["market_id"], "question": m["question"],
               "slug": m.get("slug"), "end_date": m.get("end_date"),
               "event_id": m.get("event_id"),
               "outcome": (m.get("outcomes") or ["?"])[0],
               "mid": (m.get("outcome_prices") or [None])[0],
               "series": series_of(lane, m)}
        rec["mapping_verified"] = rec["series"] in maps
        bb, ba = m.get("best_bid"), m.get("best_ask")
        if bb is not None and ba is not None and (bb or ba):
            rec["mid"] = round((bb + ba) / 2, 4)  # the book's mid, not a last trade
        if (bb is None or ba is None or ba - bb > 0.20) and "best_ask" in m:
            # no real book (fresh listing, one-sided): nothing to benchmark or
            # trade, and core/forecast.py refuses it anyway
            rec["unpriced"] = "no_real_book"
        elif rec["mid"] == 0.5 and (m.get("outcome_prices") or [0, 0])[1] == 0.5:
            rec["unpriced"] = "placeholder_mid_0.50"  # fresh listing, no real price yet
        elif lane == "barrier":
            sub = underlying_of(m["question"])[1] or "barrier"
            rec["lane"] = sub
            rec["series"] = series_of(sub, m)
            rec["mapping_verified"] = rec["series"] in maps
            if m.get("outcomes") != ["Yes", "No"]:
                rec["unpriced"] = "not_yes_no"
            else:
                rec.update(price_barrier(m, now))
        elif lane == "devig":
            sport = SLUG_SPORT.get((m.get("slug") or "").split("-")[0])
            if sport is None:
                rec["unpriced"] = "no_sport_map_for_slug_prefix"
            elif sport not in odds:
                rec["unpriced"] = "odds_not_fetched (run with --odds; budgeted)"
            elif isinstance(odds[sport], Exception):
                rec["unpriced"] = f"odds_error: {odds[sport]}"
            else:
                rec.update(price_devig(m, odds[sport]))
        else:
            rec["unpriced"] = "research_base_rates"
        if rec.get("model_p") is not None and rec["mid"] is not None:
            rec["model_minus_mid"] = round(rec["model_p"] - rec["mid"], 4)
            if abs(rec["model_minus_mid"]) > LARGE_GAP[lane]:
                rec["warn"] = ("large_gap: check the match and inputs before recording "
                               "(wrong team/day/contract, stale line, jump-prone far barrier)")
        print(json.dumps(rec))


def cmd_summary(_args):
    rows = [json.loads(line) for line in sys.stdin if line.strip()]
    by = {}
    for r in rows:
        k = (r["lane"], "priced" if r.get("model_p") is not None else r.get("unpriced", "?")[:40])
        by[k] = by.get(k, 0) + 1
    for (lane, what), n in sorted(by.items()):
        print(f"{lane:8} {n:4}  {what}")
    priced = sorted((r for r in rows if r.get("model_minus_mid") is not None),
                    key=lambda r: -abs(r["model_minus_mid"]))
    print("largest model-vs-mid gaps (the engine decides; this is triage):")
    for r in priced[:15]:
        print(f"  {r['lane']:8} {r['market_id']:>9} mid={r['mid']:.3f} model={r['model_p']:.3f} "
              f"gap={r['model_minus_mid']:+.3f} verified={r['mapping_verified']} {r['question'][:60]}")


def read_jsonl(path):
    p = ROOT / path
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def spec_fields(r):
    """category + note for core/forecast.py from the model inputs."""
    i = r.get("inputs") or {}
    if r["lane"] in ("barrier", "barrier_equity"):
        cat = f"{i.get('underlying', '?').lower()}-{i.get('mode', '?')}"
        note = (f"lanes.py barrier {i.get('mode')} S={i.get('spot')} ({i.get('spot_source')}) "
                f"L={i.get('level')}{'-' + str(i.get('upper')) if i.get('upper') else ''} "
                f"T={i.get('days')}d vol={i.get('ann_vol')} ({i.get('vol_source')}) "
                f"band={r.get('band')}")
    elif r["lane"] == "devig":
        cat = (r.get("series") or "devig").replace("devig:", "")
        note = (f"lanes.py devig {i.get('book_event')} {i.get('book_outcome')} "
                f"n_books={i.get('n_books')} fair={i.get('fair')}")
    else:
        cat, note = r["lane"], ""
    return cat, note[:480]


def cmd_plan(args):
    """Turn priced candidates into batch specs against the journals.

    action: record (no live forecast), supersede (model moved >= 0.05 from
    the live forecast: forecast.py's material-revision bar), place (live
    forecast still current: the engine re-checks it on today's book), or
    skip-positioned. Largest model-vs-mid gaps go first. Per cycle at most
    --per-event new records per event and --max-records in total; place rows
    only when |gap| >= --min-gap (smaller gaps cannot clear the engine's
    net-edge floor at any lambda). --verified-only drops rows whose series
    is not in strategy/lane-maps.json, and rows with a `warn`, and lists
    both on stderr for checking. Output feeds `core/forecast.py
    record-batch` and then `core/ledger.py place-batch`."""
    rows = [json.loads(line) for line in sys.stdin if line.strip()]
    try:
        excluded = json.loads(MAPS_PATH.read_text()).get("excluded", {})
    except (FileNotFoundError, json.JSONDecodeError):
        excluded = {}
    live = {(f["market_id"], f["outcome"]): f for f in read_jsonl("journal/forecasts.jsonl")
            if f["status"] == "open" and not f.get("superseded_by")}
    positioned = {e["market_id"] for e in read_jsonl("journal/ledger.jsonl") if e["status"] == "open"}
    priced = sorted((r for r in rows if r.get("model_p") is not None),
                    key=lambda r: -abs(r.get("model_minus_mid") or 0))
    counts, per_event, unverified, warned = {}, {}, set(), 0
    records = 0
    for r in priced:
        if r["series"] in excluded:
            counts["excluded_series"] = counts.get("excluded_series", 0) + 1
            continue
        if args.verified_only and not r["mapping_verified"]:
            unverified.add(r["series"])
            continue
        if args.verified_only and r.get("warn"):
            warned += 1
            continue
        f = live.get((r["market_id"], r["outcome"]))
        gap = abs(r.get("model_minus_mid") or 0)
        if r["market_id"] in positioned:
            action = "skip-positioned"
        elif f is None:
            action = "record"
        elif abs(r["model_p"] - f["est_prob"]) >= 0.05:
            action = "supersede"
        else:
            action = "place" if gap >= args.min_gap else "hold"
        if action in ("record", "supersede"):
            ev = r.get("event_id") or r["market_id"]
            if per_event.get(ev, 0) >= args.per_event or records >= args.max_records:
                action = "deferred"
            else:
                per_event[ev] = per_event.get(ev, 0) + 1
                records += 1
        counts[action] = counts.get(action, 0) + 1
        if action in ("skip-positioned", "hold", "deferred") and not args.all:
            continue
        cat, note = spec_fields(r)
        print(json.dumps({"action": action, "lane": r["lane"], "method": r["lane"],
                          "market_id": r["market_id"], "outcome": r["outcome"],
                          "est_prob": r["model_p"], "category": cat, "note": note,
                          "supersede": action == "supersede",
                          "forecast_id": f["id"] if f else None, "mid": r["mid"],
                          "gap": r.get("model_minus_mid"), "series": r["series"],
                          "question": r["question"]}))
    print(json.dumps({"plan_counts": counts, "unverified_series": sorted(unverified),
                      "warned_rows_held_back": warned}, indent=1), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--odds", action="store_true",
                   help="fetch bookmaker odds for devig candidates (1 credit per sport)")
    r.add_argument("--max-sports", type=int, default=1)
    sub.add_parser("summary")
    pl = sub.add_parser("plan")
    pl.add_argument("--all", action="store_true",
                    help="also print skip-positioned / hold / deferred rows")
    pl.add_argument("--verified-only", action="store_true",
                    help="only series verified in strategy/lane-maps.json, no warn rows")
    pl.add_argument("--per-event", type=int, default=3)
    pl.add_argument("--max-records", type=int, default=60)
    pl.add_argument("--min-gap", type=float, default=0.02)
    a = ap.parse_args()
    {"run": cmd_run, "summary": cmd_summary, "plan": cmd_plan}[a.cmd](a)


if __name__ == "__main__":
    main()
