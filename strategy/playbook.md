# Playbook (Phil v2)

AGENT-EDITABLE. These are my active rules. A rule earns its place by changing
a future decision.

- Keep this file under 40 KB. CI fails above 50 KB.
- Replace or merge rules; never append a diary. Evidence lives in retros and
  in git.
- The pre-v2 playbook (432 KB, 2026-07-30 to 2026-09-26) is archived at
  `journal/archive/playbook-2026-09-26.md`. Cite it; don't copy it back.

## 1. Where the edge is, as of the v2 cut-over (2026-09-26)

Settled forecasts, scored against the market mid at record time. Brier delta
is negative when I beat the market. Events are clustered: siblings count
once.

| Method | Events | Brier delta | Read |
|---|---|---|---|
| barrier, 3+ days out | 10 | -0.034 | Best signal, thin n; paper prior λ 0.5 until 20 events |
| barrier_equity | 2 (pre-v2 rows) | +0.163 | Separate lane, paper prior λ 0.5; earnings risk |
| barrier, under 3 days | 12 | worse than market | Excluded from the lane |
| devig (clean feed) | 239 | -0.002 | Real but tiny edge; λ ≈ 0.9; gaps mostly under the fee |
| mention | 11 | -0.014 | Thin n; paper prior λ 0.5 until 20 events |
| explore (narrative) | 270 | +0.020 | The market is better; weight ≈ 0 |

What lost, and why v2 exists:
- Narrative "the market hasn't priced the news" bets went 1 for 8 on claimed
  edges above 0.30. The one win was a stale book after a game had ended.
- Sibling "cross-market" reasoning scored +0.041, my worst method.
- A live probe found 0 fee-adjusted complete-set violations in 197
  multi-outcome events.
- Categories behind the market: ai-model-release +0.084, weather +0.050,
  social-media post counts +0.049, news +0.025, politics +0.015 to +0.027.
- The Haiku screener added no information (it earned 0% weight against the
  market). Mech second opinions were worse than both me and the market.

Polymarket taker fees (per-market terms; the engine reads them live):
- 7%: crypto
- 5%: sports, economics, weather, culture, other
- 4%: politics, finance, mentions, tech
- 0: geopolitics

The fee per share is rate × p × (1 − p). At 50¢ a 5% market costs 1.25¢ per
share, which is why small gaps don't trade.

## 2. Universal rules

1. **est_prob IS the mechanical read.** When a row has a named mechanical or
   benchmark read (the lane tool, a devigged book, touch.py), record exactly
   that. A shade is allowed only when it rests on a measured print quoted in
   the note (source, number, timestamp). Everything else goes in the note as
   "shade view: X" and stays out of est_prob. Evidence: unmeasured shades
   made the Brier worse in 5 of 5 independent events (Musk bootstrap, Senate
   bands, PLTR inferred open, two single-book devigs). The one measured
   shade (the SPY ES overnight print) helped. Two exceptions are defective
   inputs, not shades:
   - a liquid (≥ $1k) sibling priced at 0.02 or 0.98 overrides a count API
     that disagrees with it;
   - official-figure centring for turnout and seat counts.
2. **Resolution rules before numbers.** Read the market description. Pin
   down:
   - the resolution source and exact series (exchange, pair, contract);
   - the window and timezone;
   - touch vs close vs average;
   - rounding;
   - whether preliminary or revised data counts;
   - what happens on a tie or void;
   - which outcome your number is for (`--outcome` inversion has happened).

   Once a series is verified, record it in `strategy/lane-maps.json`.
3. **Only final facts are facts.** State media, provisional prints,
   anonymous reports and "announced" dates are not resolution facts. Info-race
   wins came only from final, resolution-source facts; every loss came from
   provisional or interpretation-dependent ones.
4. **A large disagreement is usually my error.** Before recording, check the
   mapping, the date, the contract and staleness. `lanes.py` flags
   large-gap rows; the engine rejects shrunk edges above 0.15.
5. **Measured inputs only.** Vol comes from a named, dated source (an
   implied index or realized vol from data). Odds come from `core/odds.py`,
   never WebSearch-scraped tables. Scraped and recreational tables were the
   0/7 devig graveyard and the Swedish Liberals loss.
6. **Small n and events.** One event is an anecdote. Siblings, and every
   word market from one speech, are ONE event in every tally. For mention
   markets, "independent" means a distinct speaker-venue-day.
7. **Topical base rates count post-topic analogues only.** State that n.
8. **Skip reasons are data.** `lambda_zero`, `edge_below_min`, `wide_spread`
   and `edge_implausible` mean the engine is working. Never re-record a
   forecast to get a trade. Supersede only when the model or a measured
   input moved by 0.05 or more.

## 3. Lane: barrier

**Scope.** Touch ("reach", "hit", "dip to"), close above or below, and
bracket markets on BTC, ETH, SOL, XRP, LINK, WTI, Brent, gold, silver,
natural gas, SPY/S&P, QQQ/Nasdaq. Only markets with 3+ days to the end: the lane
had no skill under 3 days, and a 30-day implied vol misstates the next few
hours (weekend BTC realized about 0.21 against DVOL about 0.35 on
2026-09-26).

Supply: the gamma tag queries in `discovery.py` (hit-price, crypto-prices,
commodities) surface about 600 priceable markets on about 50 events. The
plan records at most 3 new rungs per event per cycle, largest gaps first.

**Model** (`strategy/tools/touch.py`, driftless lognormal, via `lanes.py`):
- touch = 2·(1 − Φ(|ln B/S| / σ√T));
- close above = Φ((ln S/K − σ²T/2) / σ√T);
- a bracket is the difference of two closes.

Vol sources:
- BTC, ETH: Deribit DVOL;
- oil: ^OVX; gold: ^GVZ; S&P: ^VIX; Nasdaq: ^VXN;
- SOL, XRP, silver, natural gas: 30-day realized.

`band` is p at 0.75× and 1.25× vol. If the engine's trade side flips inside
the band, the disagreement is not robust. Say so in the note, since the
engine can't see the band.

**Mapping checklist.**
- Crypto "reach/dip" markets resolve on Binance BTCUSDT/ETHUSDT 1-minute
  candle highs or lows. The window starts at market creation or the ET day
  and ends 11:59 PM ET on the last day, so T runs to the market's end date.
  Coinbase spot is a close proxy for Binance, but check the gap for thin
  pairs.
- "Price of X above $K on DATE" markets resolve on a specific print (often
  Binance at 12:00 ET). Check that the market's end time equals that print
  time.
- Commodity ladders:
  - pass the ACTIVE-MONTH contract price;
  - CL=F is Yahoo's front month, and it rolls: confirm the market's
    contract and source;
  - "hit (HIGH)/(LOW)" means intraday touch;
  - count sessions, not calendar days, only if you price by hand with
    `--year-days 252`.
- SPY "closes above" resolves on the official close. An intraday "hit"
  needs the touch mode.

**Known limits.**
- The model has no jump term. Books price FAR barriers (gap of 10% or more)
  above it: the ETH reach-$2,800 win at 15% gap came from one +7% day.
  Reach rows also looked good during a rising month. Split far vs near and
  reach vs dip in retros before believing either.
- Gas-price ladders (AAA) and single stocks have no automatic price source
  yet. Adding one is a tool task: extend `UNDERLYINGS`/`SOURCES` in
  `lanes.py` and test it on a live scan.

**Recording.** Record every priced rung of a ladder. A ladder is one event
for the statistics and several trade decisions for the engine.

## 3b. Lane: barrier_equity

**Scope.** The same touch, close and bracket markets on single stocks and
ETFs (the ticker in parentheses: COIN, MSTR, HOOD, NVDA, EWY, ...). It
carries its own λ so it cannot contaminate the barrier fit.

**Model.** Yahoo last price and a 30-day realized vol from daily closes. The
rules count regular-hours 1-minute candles (Pyth); an overnight gap past the
level counts at the open.

**The risk that matters.** Earnings, and other scheduled jumps such as an
FDA date or an index inclusion, sit outside realized vol. When verifying a
series, check whether the window contains the company's earnings. If it
does, add the series to `excluded` in `strategy/lane-maps.json` with an
`until` date. Pre-v2 equity-touch rows were n=2 at brier_delta +0.163, and
the PLTR loss was an inferred-open shade: record the model from the last
close.

## 4. Lane: devig

**Scope.** Sports moneylines ("A vs. B"), "Will X win on DATE?" and "end in a
draw?" markets whose league is mapped in `SLUG_SPORT` (`lanes.py`).
Spreads and totals are not priced yet (a possible tool extension, see §7).

**Model.**
- `core/odds.py` pulls fresh h2h lines; `--odds` spends one credit on the
  sport with the most games in the next 36h;
- each book is power-devigged (`devig.py`; the power method shades
  longshots correctly);
- the consensus is the median across books.

Soccer is 3-way. A "Will X win?" market excludes the draw.

**What the evidence says.**
- Across about 40 markets with clean, current lines, tight Polymarket books
  sat within 0–2¢ of the devigged line.
- Every big historical devig "edge" came from stale, scraped or wrong-day
  lines (0/7 in July, before the power-devig fix).
- So devig rarely clears 2¢ net after a 5% fee. When it does, it is most
  likely a lagging Polymarket book shortly before start, or a match error.
- A gap over 8¢ is flagged. Verify the teams, the date, a neutral venue and
  late line moves (injuries) before recording.

**Recording.** Record whatever the tool prices (it's cheap, and it keeps the
λ fit honest). The engine trades only real, fee-clearing gaps.

## 5. Lane: mention

**Scope.** "Will <speaker> say <word> (N+ times) during <event>?" markets.
The price comes from counted base rates. Research at most 2 events per
cycle.

**Method.**
- Take at least two comparable prior transcripts of the same speaker in the
  same venue class (rally, presser, scripted ceremonial, earnings call).
  Thematic reasoning ("this event is about X") is not a base rate.
- Count only the named speaker's lines. Press transcripts interleave
  reporters: split by speaker label. The pooled count caused the Warsh
  Inflation-20+ loss (true speaker counts were 18 and 27, not 32 and 40).
- Verbatim rally transcripts preserve stutters ("stock ar-- market"). Sweep
  the constituent words, not just the exact n-gram.
- For N+ markets, scale each analogue's count to the expected length of
  this speech (count per word × expected words). If the nearest analogue
  sits at N or within 1 of it, cap the estimate at 0.50 unless a scheduled
  hook raises the rate.
- For topical words, only analogues from after the topic existed count.

**Record so far (thin, and one speaker-venue-day dominates).** Yes bets 0W/4L
(−$20: thematic guesses, then the counting bug). No bets 3W/0L (+$4.05).
Paying 0.71–0.88 for No means one loss erases three wins. The break-even
win rate is the ask. Don't read an edge into this yet.

## 6. Explore (forecast-only)

At most 2 per cycle. Use explore to find the next lane, not to hold opinions.
A good explore target:
- has a mechanical method that could be automated (consensus-distribution
  econ prints, weather ensembles, count processes near period end, official
  schedules);
- AND has a reachable primary source.

Don't spend explore on social-media post counts, AI leaderboards, box
office, or narrative news and politics: the settled record is behind the
market there. A method that reaches 20+ events with a negative Brier delta
becomes a lane proposal in `journal/proposals.md`.

## 7. Tool backlog (highest expected value first)

1. Barrier: coverage for gas (AAA daily national/state average) and single
   stocks (last close, plus an implied vol if one is available).
2. Devig: spreads and totals, only at the exact book line the market uses
   (the Poisson/normal extrapolations in the archive were never validated).
3. Devig: add leagues to `SLUG_SPORT` as `lanes.py summary` shows them in
   `no_sport_map_for_slug_prefix`, but only leagues the-odds-api covers.
4. Latency (forecast-only): a finished-game scan. If `core/odds.py scores`
   shows a game completed and the Polymarket book still offers the winner
   below 0.90, record it. The one real info-race win (Cubs–D-backs, +$31)
   was exactly this.

## 8. Pacing and budget

- FULL about every 3h. Come back sooner when priced games start, or when
  barrier windows close, within the next few hours; later overnight.
  `loop.sh` settles between FULL cycles without an LLM.
- Odds budget: about 450 credits a month (`core/odds.py quota`), which is
  one sport per FULL cycle.
- `journal/costs.jsonl` records every LLM tick. If a FULL cycle regularly
  runs long, cut explore first.
