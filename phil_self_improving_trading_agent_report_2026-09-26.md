# Phil self-improving trading agent: architecture, evidence audit, comparison with current methods, and prioritized improvement plan

**Report date:** 2026-09-26  
**Repository snapshot:** `phil-main.zip` supplied in this conversation  
**Scope:** static inspection of the supplied code, configuration, documentation, journals, and JSONL ledgers, plus current external research through 2026-09-26.

> **Important interpretation note.** In this report, **Observed** means directly supported by the supplied repository snapshot or by an explicitly cited external source. **Inference** means a reasoned interpretation of those observations. **Recommendation** means a proposed change whose effect is uncertain until prospectively tested. I do not assume missing implementation details. I also did **not execute the repository's trading or agent code**; I inspected it statically and independently parsed the supplied JSON/JSONL data for descriptive checks.

---

## Executive summary

Phil is best described as a **self-editing LLM trading process**, not a model-training system. The backbone LLM is fixed for each cycle; what “learns” is principally the agent's textual/procedural policy and its operating memory: `strategy/playbook.md`, `strategy/risk.json`, discovery and screening logic, tools, schedules, and accumulated journals. Settled prediction-market outcomes trigger scoring and retrospectives, and those retrospectives may lead the agent to edit its own strategy files and commit the changes. The protected `core/` layer supplies market access, ledgers, scoring, simulation, validation, and limited real-money execution. This puts Phil unusually close to the September 2026 **EvolveTrade** idea of keeping the backbone LLM fixed while revising a text-parameterized trading policy from decision traces and realized feedback [R1], and more broadly near QuantAgent's outer-loop knowledge improvement [R2], FinMem's evolving memory [R4], and AlphaEvolve's proposal/evaluator/archive pattern [R3].

The strongest architectural idea in Phil is the separation between **agent-editable judgment** and a **protected execution/evaluation core**. The system also records forecasts that do not become bets, scores calibration against market prices, keeps superseded forecasts for separate grading, and has a genuinely prospective `--after` replay mode. These are materially better scientific practices than judging only realized P&L. Current forecasting work supports this emphasis: research on post-cutoff forecasting, ForecastBench, KalshiBench, and PolyBench all emphasize temporal discipline, calibration, and contamination-resistant evaluation, and they show that strong general LLMs often do not automatically beat market or crowd baselines [R6][R7][R8][R9].

However, the supplied snapshot does **not yet demonstrate durable forecasting or trading edge**. Independently parsing the ledgers gives:

- **Paper bets:** 47 settled, 19 wins / 28 losses, $235 total stake, **-$8.539 realized P&L**, **-3.63% ROI**. Brier score of the agent's bet-time probabilities is 0.29638 versus 0.20915 for the recorded fill-price baseline, a **+0.08723 Brier delta** (positive is worse here).
- **Forecast stream:** 1,161 rows total; after excluding 156 superseded rows, 875 are settled and 129 open. On those 875 settled live forecasts, the agent Brier score is **0.17085** versus **0.16261** for the recorded market midpoint, **+0.008239 Brier delta**. Recent windows do not show a clear reversal: +0.01131 over the most recent 7 days, +0.01093 over 14 days, and +0.01274 over 30 days, anchored to the latest supplied settlement at 2026-09-26T09:12:02Z.
- An in-sample linear blend of market midpoint and agent estimate puts roughly **79% weight on the market** overall and about **81% on the market** when the two disagree by at least five points. That blend improves Brier by only about **0.00062 overall** and **0.00161 on disagreement rows**. This is interesting as a research hypothesis, not proof of tradeable residual information.
- The experimental `strategy/policy.py` v3 explicitly says its thresholds were selected with all then-available data visible. Its pre-registered forward test was subsequently marked **RESOLVED-NEGATIVE**: at the first judgment point it had 16 bets, +$28.40 P&L but `cw_return = -0.1557`, with one winner larger than the entire net profit (`journal/proposals.md:2252-2257`). On the larger current snapshot, independently applying the same frozen rule to rows settled after the registered cutoff gives 58 bets, +$20.62 P&L, +7.11% raw ROI, but still **negative `cw_return` (-0.0975)**. It should not be promoted.
- The real-money ledger contains 56 rows, all `type: "settle"`; there are **no supplied real `place`/fill records**. The snapshot therefore contains no empirical real-execution P&L to validate the paper-to-real transfer.

The highest-priority issue is **evaluation integrity**. Ordinary `core/replay.py` folds are ordered by forecast *record time*, but the training history includes all outcomes in earlier record-time folds even if those outcomes had not yet settled when the next test fold began. With the current 861-row replay universe, I count **180 leaked training-label inclusions across 5 folds** and **418 across 10 folds**. This does not alter current v3 decisions because v3 has no `fit()` function, but it would contaminate any future learned/calibrated policy using the documented `fit(history)` interface. Separately, v3's rule selection is already acknowledged as in-sample. This makes point-in-time label availability, event-level purging, and multiple-testing control the first changes I would make.

The second major issue is **execution-model mismatch**. Phil's paper broker and counterfactual sweeps assume a full fill at the top ask and do not account for taker fees, order-book size, partial fills, queue position, or latency. Polymarket's current fee schedule charges takers on many categories using `fee = shares × feeRate × p × (1-p)`, while makers pay no fee; at 50¢ a 5% fee-rate category costs 1.25¢ per share, enough to consume 62.5% of a nominal 2-point probability edge before spread or adverse selection [R18]. Polymarket also explicitly documents partial fills and order delays on some sports markets [R20]. Because many Phil hypotheses operate in a 2–7 point edge band, fee- and depth-aware replay is not optional if profitability is the objective.

The third important issue is that the **actual paper placement choke point does not enforce all rules that the documentation presents as risk policy**. `core/ledger.py` enforces maximum open positions, maximum stake per individual order, bankroll, entry-price bounds, and duplicate market+outcome positions. But it does not itself enforce `strategy/risk.json`'s `min_edge`, `max_spread`, or `max_stake_per_event_usd`, nor protected `max_new_positions_per_cycle`, `min_minutes_to_resolution`, or banned-question patterns. Some of these are applied upstream by scanning or replay code, but a direct `ledger.py place` call bypasses them. That creates a reproducibility and safety mismatch between written strategy, replay, and actual paper execution.

### Highest-priority recommendations

1. **Fix point-in-time evaluation before learning any more decision rules.** Train only on labels actually known at each decision time, group/purge related markets by underlying event, keep a true untouched forward window, and explicitly count every tried strategy variant. Use search-adjusted statistics or at minimum a pre-registered promotion protocol. This is the prerequisite for trusting any claimed profitability improvement [R13][R14][R15].
2. **Make paper and replay execution fee-, depth-, and fill-aware.** Persist fee status/rate, full or sufficient L2 book depth, quote timestamps, intended order type, simulated VWAP/partial fill, and realized real fill/fee data. Evaluate net edge, not probability edge [R18][R19][R20][R21].
3. **Split “independent forecast” from “trade posterior.”** Keep Phil's blind/pre-price probability for scientific measurement, but derive a separately frozen, cross-fitted market-aware probability for trading. The present data says the market deserves roughly 80% weight; any residual improvement is small and must be prospective. This is more plausible than asking the LLM to ignore a demonstrably stronger prior [R6][R7][R8].
4. **Hard-enforce the active policy at the broker choke point.** Either `ledger.py` itself, or a protected compiled policy artifact, should enforce the exact edge, spread, event exposure, pacing, timing, and banned-shape rules used in replay. Record an immutable `policy_rev` and decision-feature snapshot with every bet.
5. **Pre-register one focused test of the apparent No-side asymmetry rather than adopting it.** The current score-style counterfactual is negative on the Yes side at every tested edge floor and positive on the No side across roughly 2–10 point floors; at a 5-point No floor it is 129 rows and about +10.1% one-unit gross return, while the corresponding Yes floor is negative. But these are hindsight-selected, fee-blind, correlated rows and multiple thresholds were inspected. The right next step is one exact, fee-aware, event-clustered prospective hypothesis—not a rule change.
6. **Redirect scarce research from raw LLM divergence toward measurable value of information.** Phil's own screening studies already conclude that the Haiku divergence ranking is not a demonstrated predictive signal over price. Favor official scheduled releases, exact cross-market consistency constraints, timestamped catalysts, and validated families, while preserving a random-tail audit lane to discover new opportunities.
7. **Automate event/coherence graphs and executable cross-market constraints.** This is especially aligned with the current real-money allowlist, which permits only `cross-market`. Normalize sibling markets, complements, mutually exclusive outcomes, bracket monotonicity, and venue mappings; then require fee- and rule-adjusted executable inconsistency rather than narrative similarity.
8. **Replace the 6,770-line active playbook with structured, retrievable policy memory.** Keep the full historical evidence log, but represent active rules as records with scope, status, evidence count, promotion/kill criteria, supersession, and last review. This is closer to disciplined memory architectures such as FinMem/FinAgent and evaluator/archive systems such as AlphaEvolve [R3][R4][R5].

The central profitability conclusion is therefore not “make the agent more aggressive” or “add a larger model.” It is: **first make the evidence and execution model trustworthy; then combine the market as a strong prior with the small subset of Phil's information that survives prospective, fee-aware, event-level validation.** Increasing stake size, Kelly sizing, more LLM agents, or lower edge thresholds would be premature given the current calibration evidence.

---

## 1. Scope, methodology, and evidence limits

### 1.1 What was inspected

The supplied snapshot contains the main orchestration and strategy documents (`README.md`, `CLAUDE.md`, `CYCLE.md`, `loop.sh`), protected configuration (`config/protected.json`), agent-editable strategy files (`strategy/`), protected broker/evaluation code (`core/`), and substantial journals including:

- `journal/ledger.jsonl` — 51 paper bet rows;
- `journal/forecasts.jsonl` — 1,161 forecast rows;
- `journal/real-ledger.jsonl` — 56 real-execution journal rows;
- `journal/screener.jsonl` — 73,800 screening rows;
- daily deep retrospectives through `journal/retros/DEEP-2026-09-26.md`;
- operator notes, proposals, and several dedicated decision memos about screener value and lane coverage.

The unpacked snapshot has no `.git` directory. Therefore, although many records contain `strategy_rev` hashes and documents discuss git history as part of the experiment, I cannot independently reconstruct commit diffs or verify commit ancestry from this zip alone. Any statement about a historical edit is based on the supplied notes/logs or current file contents, not a local git history.

### 1.2 Safety and reproducibility method

I did not run `loop.sh`, Claude, market API calls, broker code, resolution code, or real-money code. I treated the repository as untrusted code and performed static source inspection. For descriptive ledger statistics, I used separate, minimal parsing logic over the JSONL files rather than importing or running the repository's modules. Where I re-created a metric such as Brier delta, a replay selection rule, or fold leakage count, I followed the supplied source formulas in independent code.

External research was checked against current sources on 2026-09-26. I distinguish peer-reviewed/proceedings work from arXiv preprints and first-party platform documentation in the references.

### 1.3 Metric conventions used here

For a binary outcome `y ∈ {0,1}` and forecast `p`, Brier score is `(p-y)^2`; lower is better. Phil's `brier_delta` is `Brier(agent) - Brier(market)`, so **negative is good for Phil**, positive means the recorded market probability was better.

Paper-bet ROI here is realized P&L divided by settled stake. Counterfactual threshold sweeps in `core/score.py` use one-unit full fills at the recorded ask (or `1-bid` for the complement) and **do not include trading fees**. Those sweeps should therefore be read as gross diagnostic simulations, not realizable returns.

---

## 2. How the agent actually works

### 2.1 It self-improves by editing policy and process, not model weights

**Observed.** `CLAUDE.md:3-5` describes the main cycle as settle → score → retrospective → edit strategy → research → simulated bets. `CYCLE.md:14-20` permits the agent to edit `strategy/` while reserving the ledger and core evaluation machinery to protected code. `README.md:27-29` explicitly says the agent edits its playbook, risk policy, tooling, sensing, and pacing. `loop.sh:99-142` selects a Claude model for the current tick but contains no model training procedure.

**Inference.** “Self-improving” here means **policy/process adaptation in external text and code memory**. The base Claude model's weights are not updated by Phil. This is a meaningful form of online adaptation, but it should not be conflated with reinforcement learning, gradient fine-tuning, or autonomous model retraining.

This distinction makes EvolveTrade the closest current research analogue I found. EvolveTrade explicitly treats the system prompt as a text-parameterized policy, keeps the LLM backbone fixed, and has a Policy Agent revise that policy from accumulated decision traces and realized portfolio feedback [R1]. QuantAgent similarly separates an inner problem-solving loop from an outer loop that updates a domain knowledge base using tested outcomes [R2].

### 2.2 State and “memory”

**Observed.** Durable state is distributed across:

- `strategy/playbook.md` — the main accumulated decision rules and evidence; currently **6,770 lines**;
- `strategy/risk.json` — editable thresholds and sizing policy;
- `strategy/discovery.py`, screener prompts/strata/filters, tools, and schedule;
- `journal/forecasts.jsonl` and `journal/ledger.jsonl` — append-like empirical records;
- retrospectives and proposal/status documents;
- git revisions named in journal rows and expected commits/pushes.

The latest deep retro says ten commits in its audit window touched `strategy/playbook.md` and added 169 lines, while playbook compaction remained undone (`journal/retros/DEEP-2026-09-26.md:70,197-198`).

**Inference.** This is a hybrid of episodic memory (journals and forecasts), semantic/procedural memory (playbook rules), and governance memory (operator notes, promotion gates). It resembles FinMem's layered memory concept [R4] and FinAgent's diversified memory/reflection approach [R5], but Phil's active memory is substantially more free-form and monolithic.

### 2.3 The orchestration loop

**Observed.** `CYCLE.md:42-52` defines three tick classes:

- **FULL** — run the complete research/trading/self-edit sequence;
- **LIGHT** — settle/monitor only;
- **TRIGGERED** — watch-driven response to a detected event.

`loop.sh` predicts whether a tick can be LIGHT and uses Sonnet 5 for those ticks; otherwise it uses `claude-opus-5-5` (`loop.sh:99-142`). The agent receives file read/edit/write, web search/fetch, Task subagents, selected `core/*` commands, limited git commands, and optional Pearl Connect mechanism tools (`loop.sh:159-180`). After the agent exits, the shell checks protected paths and reverts uncommitted modifications to them (`loop.sh:193-202`).

**Observed.** Full cycles first settle outcomes and score them; if new positions have settled, the cycle writes a retro, separates estimate error from fill quality and variance, inspects Brier/P&L by category, and is instructed not to overreact to fewer than about 15 settlements (`CYCLE.md:108-120`). It then scans and screens markets, researches selected candidates, records every researched probability, and may place paper bets.

### 2.4 Market discovery and screening

**Observed.** `CYCLE.md:122-150` calls roughly:

```text
core/scan.py --hours 336 --limit 800 | core/screen.py prepare
```

The screened pool is divided into strata; cheap subagents score batches; `core/screen.py collect` validates results, computes divergence from market mids, appends `journal/screener.jsonl`, and returns top-ranked rows. The screen “ranks, it does not gate”; separate watch, calendar, and sibling lanes can still claim research slots.

`strategy/screener-strata.json` includes top-liquidity, top-volume, close-to-resolution, and a random-tail component. That random lane is important scientifically because it retains some observation of the distribution the heuristic ranking would otherwise discard.

**Observed.** Phil has already audited its screener rather than assuming its LLM ranking works. `journal/screener-rank-decision.md` and `journal/screener-value-decision.md` conclude that raw divergence/uncertainty are not demonstrated predictors of later research value; the latter reports about 542 settled rows / 394 events with mean Brier delta roughly +0.0080 ± 0.0091 and rejects switching to a learned empirical-Bayes prior. That is a strong example of the system falsifying one of its own components.

### 2.5 Research and forecast recording

**Observed.** `core/forecast.py` enforces one live forecast per market+outcome unless a material revision is recorded with `--supersede`. A revision needs an absolute probability change of at least 0.05 or a changed skip reason (`core/forecast.py:50-53,93-112`). Superseded rows remain and later settle; headline scoring uses only the latest row, while abandoned estimates are scored separately (`core/forecast.py:160-166`; `core/score.py:184-199`).

The code records best bid, best ask, midpoint, liquidity and 24h volume fields, category, skip reason, notes, and strategy revision (`core/forecast.py:134-159`). It explicitly describes `est_prob` as an “honest probability, formed before reading the price” (`core/forecast.py:185-186`). An extreme difference above 0.40 from the market midpoint needs explicit confirmation, partly to catch outcome-side inversion errors (`core/forecast.py:55-61,125-132`).

**Inference.** This “blind estimate first, market price recorded second” design is valuable because it makes Phil's independent information content measurable. But a blind estimate is not automatically the best *trading* posterior once a strong market prior is available. This distinction becomes central in the recommendations.

### 2.6 Paper placement

**Observed.** `core/ledger.py` is the only writer of `journal/ledger.jsonl` and paper buys cross the book at the current best ask (`core/ledger.py:2-10,82-118`). It computes `edge = est_prob - ask`, stake, and shares `stake/ask`.

At placement time it enforces:

- protected maximum open positions;
- protected maximum stake per single order;
- simulated cash availability;
- estimate inside `(0,1)`;
- no duplicate open position on the same market+outcome;
- market open and chosen outcome valid;
- an ask exists;
- ask within protected min/max entry price.

These are visible in `core/ledger.py:68-92`.

### 2.7 What placement does **not** enforce

**Observed.** The actual `cmd_place()` path does **not** check:

- `strategy/risk.json:min_edge`;
- `strategy/risk.json:max_spread`;
- `strategy/risk.json:max_stake_per_event_usd`;
- protected `max_new_positions_per_cycle`;
- protected `min_minutes_to_resolution`;
- protected `banned_question_patterns`.

Some are applied elsewhere. `core/scan.py` filters banned patterns and minimum resolution time in normal discovery, and `core/replay.py:120-152` applies banned patterns, minimum minutes, entry bounds, and stake clipping during replay. But there is no equivalent check in `core/ledger.py place`. A direct place call can therefore enter a market that normal scanning would have rejected.

`core/validate.py` also validates types and ceilings but does not post-hoc enforce those omitted per-placement conditions. Its top-level docstring is stale: it says real trading should remain false (`core/validate.py:8-9`), while the implementation explicitly supports `real_trading_enabled: true` provided a capped real block is present (`core/validate.py:86-110`). `CLAUDE.md` contains the same historical inconsistency: line 14 says the tripwire keeps real trading false, while line 49 describes true as validated.

**Inference.** There is a gap between **documented policy**, **replay policy**, and **broker-enforced policy**. Even if the agent normally follows CYCLE instructions, this weakens both safety and experimental reproducibility. A strategy change cannot be cleanly attributed if the broker does not record and enforce the exact decision regime.

### 2.8 Scoring and retrospection

**Observed.** `core/score.py` reports P&L/ROI and Brier score for bets, plus a separate forecast stream whose baseline is the market midpoint rather than the fill ask (`core/score.py:31-64`). It includes:

- edge-threshold counterfactuals on the recorded side (`threshold_sweep`);
- complementary No-side counterfactuals (`threshold_sweep_no`);
- blends of market midpoint and agent probability (`blend_sweep`);
- category, skip-reason, calibration, and revision slices.

This is significantly more diagnostic than a P&L-only loop. In particular, it can detect when the agent got lucky on trades despite bad probability estimates.

### 2.9 Replay and policy learning

**Observed.** `core/replay.py` defines an optional policy contract `fit(history) -> state` plus `decide(row,state)`, and strips outcome fields from test rows (`core/replay.py:12-18,97-105`). It simulates Yes at the recorded ask and No at `1 - recorded bid`, applying several protected filters (`core/replay.py:120-152`).

Ordinary replay sorts settled, non-superseded forecasts by **forecast record timestamp** and cuts them into contiguous folds (`core/replay.py:77-94,225-244`). For fold `k`, it gives `fit()` all rows in earlier record-time chunks with their outcomes (`core/replay.py:232-235`). It does **not** check whether those earlier rows had actually settled before the first observation in the test fold.

By contrast, `--after` explicitly separates rows by `settled_ts`: train rows settled by the cutoff and test rows settled after it (`core/replay.py:208-222`). The file itself calls this “the only true out-of-sample score” for a policy whose thresholds were chosen by reading the ledger (`core/replay.py:42-47`).

### 2.10 Real-money twin path

**Observed.** `config/protected.json` has `real_trading_enabled: true`, real max stake $1, max 10 open positions, daily stake cap $5, and `allowed_edge_classes: ["cross-market"]`. `core/real.py` is the sole funds-touching code. It requires a paper twin, checks the twin's edge class against the allowlist, caps per-order real stake, permits one real position per market, limits open positions and daily stake, and blocks further orders if an earlier submission is ambiguous (`core/real.py:180-250`). It shells out to Pearl Connect's Polymarket scripts.

**Observed.** `FEE_HEADROOM = 0.15` is used only to fund/top-up enough cash before the external buy (`core/real.py:47,230-240`). The real ledger base row records market/token/question/outcome/edge class/USD/strategy revision and then the returned external `order`, but `core/real.py` does not normalize and persist a first-class fill price, filled quantity, Polymarket fee, maker/taker flag, order-book snapshot, or slippage metric.

**Observed.** The supplied `journal/real-ledger.jsonl` has 56 rows and every row has `type: "settle"`; there are no place/fill records. Therefore there is no supplied evidence that real twins have executed in this snapshot.

---

## 3. What the current data says

### 3.1 Paper betting performance

Independent parsing of `journal/ledger.jsonl`:

| Metric | Snapshot value |
|---|---:|
| Total paper rows | 51 |
| Settled | 47 |
| Open | 4 |
| Wins / losses | 19 / 28 |
| Settled stake | $235.00 |
| Realized P&L | **-$8.5391** |
| ROI | **-3.63%** |
| Agent Brier on settled bets | 0.29638 |
| Recorded fill-price Brier baseline | 0.20915 |
| Brier delta | **+0.08723** |

By declared edge class on settled paper bets:

| Edge class | n | Wins | P&L | ROI | Brier delta |
|---|---:|---:|---:|---:|---:|
| unclassified / legacy | 18 | 5 | -$46.89 | -52.10% | +0.12598 |
| `book-devig` | 2 | 1 | $0.00 | 0.00% | -0.00139 |
| `other` | 22 | 12 | +$27.12 | +24.65% | +0.01455 |
| `info-race` | 5 | 1 | +$11.23 | +44.93% | +0.30299 |

The `info-race` row is a useful warning: positive P&L coexists with extremely poor relative calibration. A small number of asymmetric payoffs can make a bad forecasting process look profitable temporarily. This validates Phil's choice to keep Brier delta beside P&L.

### 3.2 Forecasting performance

`journal/forecasts.jsonl` contains 1,161 rows. 156 have `superseded_by` and are deliberately excluded from headline forecasts. Among the 1,005 non-superseded rows, 875 are settled and 129 are open; one row is void in the full file.

On 875 settled non-superseded forecasts:

- agent Brier = **0.170852**;
- recorded market-midpoint Brier = **0.162613**;
- `brier_delta = +0.008239`.

That means the market midpoint remains the better probability estimator overall in the supplied period.

Recent settled windows, measured from the latest supplied settlement at 2026-09-26T09:12:02Z:

| Window | n | Brier delta |
|---|---:|---:|
| 7 days | 166 | +0.01131 |
| 14 days | 284 | +0.01093 |
| 30 days | 573 | +0.01274 |

There is no simple recent-period evidence here that self-editing has already turned the aggregate forecast stream market-beating.

The latest deep retro reports 872 headline settlements rather than 875 because it ran earlier on 2026-09-26; three supplied rows settled later that morning. This is a timing difference, not a contradiction.

### 3.3 Market-aware blending: promising but tiny and in-sample

Using the source formula in `blend_sweep`, the current 875-row sample gives a least-squares blend of roughly:

```text
p_trade ≈ 0.791 * p_market + 0.209 * p_agent
```

The blended Brier is about 0.161991, an improvement of just **0.000622** over the market midpoint on the same data used to fit the weight. On 280 rows where `|p_agent - p_market| >= 0.05`, the optimal market weight is about 0.8075 and the in-sample Brier improvement is roughly **0.00161**.

**Inference.** The most plausible reading is not “Phil should ignore the market,” but “Phil may contain a small residual signal after heavy shrinkage toward the market.” That is exactly the kind of signal that can disappear after proper cross-fitting, fees, and regime change. KalshiBench's systematic overconfidence result [R8], PolyBench's mixed profitability across frontier LLMs [R9], and ForecastBench's remaining human-forecaster advantage [R7] all argue for treating market/crowd probabilities as a strong prior rather than a nuisance input.

### 3.4 Category results are exploratory, not promotion evidence

Some categories with at least eight current settled forecasts have negative Brier delta—for example `mlb-moneyline` (n=15, about -0.0499), `commodities-touch` (n=14, -0.0378), `crypto-touch` (n=16, -0.0307), `commodities` (n=15, -0.0181), `mlb-totals` (n=33, -0.0105), `say-the-word` (n=64, -0.0098), and soccer (n=99, -0.0052). Others are materially positive/worse, such as `ai-model-release` (n=35, +0.0838), `social-media-postcount` (n=37, +0.0489), and weather (n=34, +0.0495).

These cells are useful for hypothesis generation, but they are not independent experiments: categories were created and revised by the same adaptive agent, many events have sibling rows, and many category/threshold slices have been inspected. The 2026 finance literature on search-adjusted false discovery is directly relevant: in a search-and-selection process, apparent in-sample discoveries can be much less reliable than their individual statistics suggest [R14][R15].

### 3.5 The gates appear to be doing some real harm reduction

By current skip reason, the largest problematic disagreement cells are often withheld rather than bet. For example:

- `outside-view-veto`: n=140, Brier delta about **+0.0442**;
- `category-bar`: n=39, about **+0.0316**;
- `market-agrees`: n=135, about **+0.0047**;
- `no-edge`: n=437, approximately flat at **-0.00028**;
- `bet`: n=17, **-0.0164**;
- `wide-spread-veto`: n=16, **-0.0283**.

This does not prove the gates are optimal—the selection mechanism itself creates conditioning—but it suggests the system has learned to keep many of its worst disagreements out of the bet ledger. A profitability-improvement program should preserve that property and measure **saved expected loss**, not simply try to maximize bet count.

### 3.6 The No-side asymmetry

Re-creating `core/score.py`'s current gross, one-unit threshold sweeps on settled non-superseded forecasts gives:

| Edge floor | Yes-side n | Yes gross ROI | No-side n | No gross ROI |
|---:|---:|---:|---:|---:|
| 0.02 | 161 | -4.16% | 205 | +4.44% |
| 0.03 | 135 | -1.26% | 172 | +6.09% |
| 0.04 | 113 | -8.18% | 146 | +7.01% |
| 0.05 | 103 | -7.06% | 129 | +10.07% |
| 0.07 | 77 | -15.34% | 107 | +11.62% |
| 0.10 | 48 | -25.36% | 77 | +20.92% |
| 0.15 | 27 | -36.75% | 52 | -2.83% |

`DEEP-2026-09-26.md:45-48` independently notices the same shape and calls the 5–10 point No-side band “the only slice worth watching,” not an adopted edge.

This could reflect a genuine asymmetric bias in Phil's estimates—for example a tendency to overestimate the named outcome—or it could be a selection artifact. The sweep inspects seven thresholds on each side, ignores current taker fees, treats correlated event siblings as separate rows, and is computed after seeing all outcomes. Therefore it should be **pre-registered prospectively**, not deployed as found alpha.

### 3.7 Policy v3: instructive negative result

`strategy/policy.py` v3 considers both sides, restricts edge to 0.02–0.07, prices to 0.10–0.90, excludes a 0.20–0.45 “dead zone,” caps spread at 0.03, and stakes a flat $5 (`strategy/policy.py:66-99`). The file itself candidly states that every threshold was chosen with all 420 then-settled rows visible and that the apparent 5-fold and 10-fold scores are **IN-SAMPLE** (`strategy/policy.py:42-56`). Two sibling Bank of Israel rows contributed +$73 of the historical P&L.

The operator then pre-registered an actual forward gate on 2026-09-02: at least 15 bets, positive forward `cw_return`, and no single bet above half of positive total P&L (`journal/operator-notes.md:723-738`). It failed on 2026-09-10 (`journal/proposals.md:2252-2257`).

This is exactly how the self-improvement loop should behave scientifically: a good-looking historical rule was frozen, prospectively tested, and rejected when its risk-adjusted behavior did not replicate.

### 3.8 Real execution evidence is absent in the supplied snapshot

The design anticipates a paper/real twin, but the current real ledger has no `placed` rows. Any statement that the real path currently matches paper fills, fees, or slippage would therefore be an inference from code structure, not observed execution. Real profitability should remain a separate evidence tier until actual fill-level rows exist.

---

## 4. Evaluation integrity audit

This is the highest-leverage technical section because a self-improving agent can optimize whatever measurement errors exist in its evaluator.

### 4.1 Point-in-time label leakage in ordinary replay

**Observed code behavior.** `load_rows()` sorts by **record timestamp** (`core/replay.py:77-94`). For each later fold, `replay()` builds the training history from all prior record-time chunks and exposes a `won` label for each (`core/replay.py:102-105,225-244`). There is no `settled_ts <= test_start` filter in ordinary replay.

That means a forecast recorded earlier but resolving later can have its future outcome made available to `fit()` merely because its *record* fell in a prior chunk.

Using the current 861-row `load_rows()` universe and reproducing the exact chunking independently:

- 5-fold replay has leaked-label counts **48, 54, 20, 58** across its four scored folds: **180** training inclusions whose outcomes had not settled by the first record time of the corresponding test fold.
- 10-fold replay has **51, 49, 97, 56, 25, 13, 27, 58, 42**: **418** such inclusions.

This number counts fold-level inclusions, not unique forecasts, because the same row can remain in later training folds.

**Materiality.** Current v3 has no `fit()` function, so the leakage does not change its deterministic decisions. But the public contract explicitly supports learned `fit(history)`, and the repository has experimented with history-calibrated variants. Any future calibration, threshold learner, category weight, or sizing model trained through ordinary replay would receive information that was unavailable in real time.

**Recommendation.** Change the training set for every decision/test block to include only rows whose `settled_ts` is no later than the decision timestamp used to form the test. Better still, group by event and apply a purge/embargo for overlapping resolution windows. Financial-validation research finds ordinary walk-forward can be fragile under temporal dependence; combinatorial purged approaches can reduce backtest overfitting in controlled settings, although their assumptions should not be copied mechanically [R13]. The general principle—point-in-time data and purging overlapping labels—is directly applicable.

### 4.2 Rule-selection leakage remains even after fold repair

Fixing `settled_ts` leakage does not solve v3's larger issue: its thresholds were manually searched using the whole dataset. The file documents this itself. This is **selection overfitting**, not a code bug.

The Deflated Sharpe Ratio literature emphasizes that trying many alternatives inflates observed performance and that inference should account for the number and dependence of trials [R14]. A recent 2026 paper by López de Prado and Fabozzi goes further: when published/reported results are themselves selected from a search process, false-discovery rates cannot be identified from the selected in-sample statistics alone without modelling the search [R15]. Their exact model is not a drop-in answer for Phil, but the methodological warning is highly relevant because Phil repeatedly edits prompts, filters, categories, thresholds, and tool choices based on the same growing ledger.

**Recommendation.** Maintain a machine-readable experiment registry containing every considered policy version, its timestamp, parent, exact data cutoff, hypothesis, primary metric, and promotion/kill criterion. Treat abandoned and uncommitted variants as trials too when feasible. Promotion should require an untouched future window or another contamination-resistant holdout.

### 4.3 Event correlation is under-accounted

Several files recognize one-per-event and event caps, and v3's own documentation notes that two sibling Bank of Israel rows dominated its historical P&L. But forecasts and score tables are still usually row-level. Related markets on one election, one speech, one economic release, or one match are not independent evidence units.

**Recommendation.** Add a canonical `event_id` and `dependency_group_id` to forecasts and bets. Report both row-level and event-clustered metrics. Bootstrap or form confidence intervals by event, not by row. Enforce event-level stake limits in the broker. In a cross-market system, correlated siblings are precisely where interesting structure exists, so they should not be thrown away; they should be recognized as a **single information event with multiple instruments**.

### 4.4 Search exposure should be treated as part of the learning algorithm

Phil's self-editing is powerful because it can generate and test many ideas. That is also a statistical hazard: the agent sees retros, score slices, counterfactuals, and old failures, then writes new rules. The ledger effectively becomes a repeatedly queried adaptive dataset.

**Recommendation.** Divide data into three logical roles:

1. **development history** — freely inspected and used to create hypotheses;
2. **rolling validation** — available only to a deterministic evaluation service that returns predeclared metrics;
3. **promotion forward window** — not exposed in detail until the registered decision point.

For high-frequency monitoring of a single frozen hypothesis, anytime-valid confidence sequences are a possible tool because they control coverage under repeated looks [R16]. They do not solve adaptive hypothesis generation; that still needs frozen hypotheses and trial accounting.

---

## 5. Execution realism audit

### 5.1 Top-of-book full-fill simulation is too optimistic for profitability claims

`core/pmapi.py:42-47` fetches the CLOB book but reduces each side to maximum bid/minimum ask, discarding sizes. `core/ledger.py` then assumes the full requested paper stake fills at that single ask. This is defensible as a minimal, conservative-vs-mid paper convention, but it is not a complete execution model.

Polymarket documents that limit orders can partially fill [R20] and warns that desired size can move the price or fail to fill depending on order-book depth [R21]. At Phil's current $5 paper and $1 real sizes, depth impact will often be small, but the point matters precisely in thin markets where apparent edge is largest and in any future scale-up.

**Recommendation.** Persist at least the top N levels and sizes, or enough cumulative depth to cover the intended order. Paper fills should walk the ask book to compute VWAP and partial fill. If the paper system cannot reconstruct queue dynamics, it should say so and distinguish “marketable taker fill simulation” from passive maker simulation.

### 5.2 Current Polymarket fees materially change small-edge economics

Polymarket's help center, updated July 10, 2026, says takers pay fees on multiple categories using:

```text
fee = shares × feeRate × p × (1 - p)
```

with rates of 7% for crypto, 5% for sports/economics/culture/weather/general, 4% for finance/politics/mentions/tech, and 0 for geopolitics; makers pay no fee. Fees apply only to fee-enabled markets and `feesEnabled` should be checked per market [R18][R19].

At `p = 0.50`:

- a 5% category costs `0.05 × 0.5 × 0.5 = $0.0125` per share;
- a 4% category costs `$0.0100` per share;
- a 7% category costs `$0.0175` per share.

For a one-share binary claim, a true probability just 2 points above a 50¢ price has only 2¢ of gross expected value before fees. A 1.25¢ taker fee consumes **62.5% of that nominal edge**. Even a 4-point edge loses roughly 31% of its gross edge to that fee before spread, stale-quote risk, or research cost.

Phil's current base `risk.json:min_edge` is 0.04, while experimental policies explore down to 0.02. A fee-blind backtest can therefore reverse the ranking of strategies near the decision boundary.

**Recommendation.** Snapshot `feesEnabled`, fee category/rate, and exact fee parameters at forecast and order time. All score/replay/counterfactual P&L should be net of fees. Since platform schedules can change, do not hard-code a timeless fee table; store the applied terms with each decision.

### 5.3 Maker execution deserves a separate prospective experiment

Polymarket says makers are not charged fees and fee-enabled markets fund daily maker rebates; a $1 accrued rebate is required before payout [R19]. Passive execution could therefore improve economics for slow signals. But passive orders introduce **non-fill and adverse-selection risk**: a maker order may fill exactly when the market moves against the stale quote. Sports also have specific marketable-order delays and order cancellation behavior around game start [R20].

**Recommendation.** Do not retrospectively assume maker fills. Instead shadow-run a maker/taker router:

- use taker orders for time-critical information races where edge decays quickly;
- for slower signals, post at/inside the book subject to a cancellation deadline;
- record fill probability, time-to-fill, post-fill markout, missed trade P&L, and fee savings;
- compare with a contemporaneous taker shadow price.

At $1 real size, the maker rebate minimum means direct rebate income may be negligible; **fee avoidance** and price improvement are the main reasons to test it.

### 5.4 Real execution logs need normalized economic fields

The real wrapper currently stores the raw returned `order` object but does not guarantee stable normalized fields for fill price, quantity, fees, or slippage. That makes later paper-vs-real attribution brittle.

**Recommendation.** For every real twin, append a normalized execution record containing at least:

- request timestamp and broker acknowledgement timestamp;
- intended side/notional/order type/limit;
- book snapshot ID and top-of-book/depth at request;
- filled shares and average fill price;
- explicit fee and maker/taker flag;
- unfilled remainder/cancellation reason;
- paper simulated price at the same timestamp;
- slippage vs paper and markout after fixed horizons.

This creates an actual feedback signal for deciding whether a paper edge survives implementation.

---

## 6. Comparison with current related systems and methods

### 6.1 EvolveTrade: the closest architectural analogue

EvolveTrade (submitted 2026-09-15) treats the tool-using agent's system prompt as a text-parameterized policy. After each update interval, a separate Policy Agent revises that policy from decision traces and realized portfolio feedback while the backbone LLM remains fixed; the authors report improved Sharpe/cumulative return in most evaluated settings [R1]. It is a fresh arXiv preprint, so its performance claims should be treated as author-reported rather than settled evidence.

**Similarity to Phil:** extremely high at the conceptual level. Phil's `strategy/playbook.md`, risk file, sensing, tooling, and pacing are a richer text/code policy that the agent revises from resolved outcomes while Claude's weights remain fixed.

**Difference:** EvolveTrade presents policy refinement as a more explicit optimization object. Phil's evaluator is more heterogeneous: Brier, P&L, retros, manual/operator gates, and many prose rules. Phil also has a stricter protected-core boundary and an append-like forecast ledger.

**Useful import:** make policy evolution a **structured proposal → frozen candidate → evaluator → promotion/archive** protocol rather than free-form accumulation. The important part to copy is the separation of reusable policy from decision traces, not any reported return figure.

### 6.2 QuantAgent: outer-loop knowledge improvement

QuantAgent (2024) proposes a two-layer loop: an inner loop uses a knowledge base to refine responses; an outer loop tests those responses in real scenarios and updates the knowledge base with new insights [R2].

**Similarity:** Phil's retrospectives update procedural knowledge after settlement.

**Difference:** Phil's knowledge is mostly human-readable playbook text and tool code; QuantAgent is framed around mining quantitative signals and a knowledge base.

**Useful import:** clearer separation between **candidate knowledge**, **validated knowledge**, and **rejected knowledge**. Phil currently carries these states in prose across a very long playbook.

### 6.3 AlphaEvolve: evaluator-driven evolution

Google DeepMind's AlphaEvolve uses LLMs to propose code changes, automated evaluators to score them, and an evolutionary database/archive to preserve and recombine promising programs; DeepMind has reported production and algorithmic uses of the system [R3]. It is not a trading system, but it is highly relevant to self-improving-agent governance.

**Similarity:** Phil proposes changes, evaluates behavior, preserves history, and has protected evaluators.

**Difference:** AlphaEvolve's evaluation target is usually objective and repeatable; trading returns are noisy, non-stationary, correlated, and highly vulnerable to backtest search. Phil cannot safely choose “highest score wins” without stronger statistical controls.

**Useful import:** explicit candidate lineage, immutable evaluator inputs, archive of rejected alternatives, and reproducible promotion criteria. Do **not** copy aggressive evolutionary search over the same financial sample without search-adjusted validation.

### 6.4 FinMem and FinAgent: structured memory and reflection

FinMem's published AAAI Symposium description uses Profiling, layered Memory, and Decision-making modules, with adjustable memory span and a claim of improved trading outcomes [R4]. FinAgent uses multimodal inputs, tool augmentation, diversified memory, and reflection [R5].

**Similarity:** Phil already has long-term journals, retrospectives, and multiple information sources.

**Difference:** Phil's active procedural memory is largely one giant playbook plus scattered memos, making retrieval and supersession difficult.

**Useful import:** layered memory with explicit recency/importance/type and a retrieval layer that supplies only relevant validated rules to a decision. Keep the full historical log separately so compression cannot erase falsifying evidence.

### 6.5 TradingAgents and PolySwarm: multi-agent diversity

TradingAgents organizes specialized analyst, debate, trader, and risk-management agents and reports experimental gains [R10]. PolySwarm, a 2026 preprint specifically about prediction markets, proposes 50 diverse LLM personas, confidence-weighted aggregation with market probabilities, cross-market divergence detection, latency arbitrage, and quarter-Kelly sizing; its authors report better calibration than single-model baselines [R11].

**Similarity:** Phil already fans out Haiku screening subagents and samples external “Mech” opinions. It also explores cross-market structures.

**Critical difference:** Phil has empirical evidence that its current screening subagents' divergence ranking does **not** automatically create value. More agents with similar prompts can create correlated confidence, not independent information.

**Useful import:** if multiple agents are used, diversity should be **informational**, not cosmetic. Give different agents non-overlapping roles or sources—e.g. official-source parser, base-rate historian, resolution-criteria skeptic, market-structure solver—and score each one's residual contribution out of sample. Do not copy quarter-Kelly sizing until probabilities are prospectively calibrated.

### 6.6 Forecasting systems: retrieval, aggregation, and market baselines

Halawi et al. build a retrieval-augmented LM system that searches for relevant information, forecasts, and aggregates predictions. On questions published after model knowledge cutoffs, the system approaches the aggregate of competitive human forecasters and surpasses it in some settings [R6]. ForecastBench is a dynamic benchmark designed to keep questions genuinely future-facing; its ICLR 2025 work reports competitive human forecasters outperforming leading LLM systems on its controlled comparison [R7]. KalshiBench's 2025 preprint reports systematic overconfidence across five frontier models and only one positive Brier Skill Score [R8].

**Implication for Phil:** research retrieval and aggregation are worthwhile, but the market/crowd forecast is itself a powerful model. Phil should measure whether each research action improves probability **relative to market**, not whether the narrative sounds convincing.

### 6.7 PolyBench: especially relevant evaluation design

PolyBench (April 2026 preprint) records timestamp-locked Polymarket snapshots coupling live CLOB state and news across 38,666 binary markets / 4,997 events and evaluates models with financially grounded execution simulation. Its authors report that only two of seven evaluated LLMs achieved positive returns in their setup [R9].

**Similarity:** Phil also stores point-in-time bid/ask/mid and research context.

**Difference:** Phil does not yet store enough book depth/fee data for comparably realistic execution replay, and its online adaptive policy repeatedly reuses the same ledger.

**Useful import:** timestamp-locked multimodal snapshots and a richer execution environment. The exact PolyBench return metric need not be copied; the temporal discipline should be.

### 6.8 Live trading benchmarks: general intelligence is not enough

AI-Trader reports that most evaluated LLM agents in live, data-uncontaminated financial environments had poor returns and weak risk management, with risk control strongly related to robustness [R12]. StockBench similarly finds that most LLM agents struggle to beat a simple buy-and-hold baseline in its multi-month stock environment [R17]. These are not prediction-market results, but they reinforce a common lesson: fluent reasoning and tool use do not guarantee economic edge.

A 2026 peer-reviewed survey of LLM-enhanced RL in finance identifies benchmark fragmentation, data leakage/look-ahead bias, computational overhead, and training instability as major open issues [R23]. Phil is exposed to exactly the leakage/evaluation side of that problem even though it is not itself an RL learner.

### 6.9 Comparison table

| System / method | What adapts | Evaluation emphasis | Similarity to Phil | Most useful lesson for Phil |
|---|---|---|---|---|
| **Phil** | text policy, risk, tools, sensing, pacing | market-relative Brier + P&L + retros | — | strong protected-core idea; needs stricter point-in-time and execution evaluation |
| EvolveTrade [R1] | text-parameterized policy, fixed backbone | portfolio feedback / returns | **very high** | formalize policy versions and policy-evaluator loop |
| QuantAgent [R2] | knowledge base via outer loop | tested signals / forecasts | high | distinguish learned knowledge states |
| AlphaEvolve [R3] | executable programs | automated evaluator + archive | medium | candidate lineage, immutable evaluator, archive—without financial sample oversearch |
| FinMem [R4] | layered memory/profile | trading outcomes | medium-high | structured memory and retrieval |
| FinAgent [R5] | diversified memory/reflection/tools | multi-dataset trading | medium | role-specific memories and reflection |
| TradingAgents [R10] | multi-agent deliberation | trading experiments | medium | specialization can help, but only if contributions are independent and scored |
| PolySwarm [R11] | multi-agent ensemble + market prior | calibration, log loss, P&L | high | market-aware ensemble and cross-market solver are relevant; Kelly is premature here |
| Halawi forecasting [R6] | retrieval + aggregation | post-cutoff forecasting | high | retrieval + aggregation; evaluate against crowd/market |
| ForecastBench [R7] | benchmark, not self-learning | dynamic future-only Brier | high eval relevance | maintain future-only outcome discipline |
| KalshiBench [R8] | benchmark | calibration / Brier skill | high eval relevance | expect LLM overconfidence; calibration needs explicit work |
| PolyBench [R9] | benchmark | timestamped CLOB + news + return | **very high eval relevance** | store sufficient point-in-time execution state |

---

## 7. Detailed improvement opportunities

### Improvement 1 — Make replay genuinely point-in-time and event-purged

**What should change.** Replace ordinary fold training based on “recorded in an earlier chunk” with training based on **label availability**. For a test decision at time `t`, a training row is usable only if its settlement was known at `t`. At minimum:

```text
train = rows with settled_ts <= test_block_start
```

A stronger version should group all sibling instruments under a canonical event and purge/embargo overlapping event windows. Keep `--after` as the clean promotion path. Add unit tests containing deliberately late-resolving early forecasts so leakage cannot regress.

**Why it should help.** It does not directly create alpha; it prevents false alpha. A self-improving agent that optimizes a contaminated evaluator will preferentially learn rules that exploit contamination or noise. Removing that failure mode raises the chance that later changes survive live trading.

**Evidence/reasoning.** Current ordinary replay supplies 180 unavailable outcome inclusions across 5 folds and 418 across 10 folds in the supplied snapshot. The current policy has no `fit()`, but the interface explicitly permits one. Financial-validation literature finds temporal dependence and selection can make ordinary validation optimistic; purged/CPCV-type methods are designed to reduce overlapping-information leakage [R13]. ForecastBench, StockBench, AI-Trader, and PolyBench independently emphasize post-cutoff or live data discipline [R7][R9][R12][R17].

**Tradeoffs/uncertainties.** Less training data is available at each point, so confidence intervals widen. Event grouping is difficult when market titles have subtly different resolution criteria. CPCV is not automatically superior for every non-stationary prediction market; use it as a robustness tool, not a magic score.

**Priority:** **P0 — prerequisite.**

### Improvement 2 — Add experiment registry and search-adjusted promotion

**What should change.** Create a protected or append-only `experiments.jsonl` containing:

- hypothesis ID and parent;
- code/prompt/policy revision;
- exact data cutoff and universe;
- all parameter variants tried;
- primary and secondary metrics;
- event-level sample target;
- promotion and kill criteria;
- whether the result was development, validation, or forward;
- final disposition.

A strategy edit that changes decision behavior should reference an experiment ID. Promotions should require a future window that was not used in proposal generation.

**Why it should help.** Phil's strength—rapid strategy mutation—creates repeated testing. Trial accounting reduces the chance of promoting a lucky slice.

**Evidence/reasoning.** v3's attractive historical score failed the registered forward test. The Bank of Israel sibling concentration illustrates how a small number of observations can dominate rule selection. DSR explicitly adjusts for selection bias/multiple trials [R14], and the 2026 FDR paper argues that search/selection must be modelled rather than inferred from selected in-sample statistics alone [R15].

**Tradeoffs/uncertainties.** This slows adaptation and adds governance overhead. Formal statistical corrections can be unstable with small, dependent samples. The most robust practical mechanism is still a truly untouched future test.

**Priority:** **P0.**

### Improvement 3 — Make all economic evaluation net of current fees and actual fill mechanics

**What should change.** Extend forecast/order snapshots with:

- `fees_enabled` and category fee rate;
- top N book levels and sizes;
- quote retrieval timestamp;
- intended order type;
- paper fill algorithm version;
- simulated average fill / filled quantity / unfilled quantity;
- explicit fee;
- for real orders, normalized actual fill/fee fields.

Update `ledger.py`, `score.py`, `replay.py`, `counterfactual.py`, and real-twin attribution to use **net P&L**.

**Why it should help.** It removes strategies whose gross edge is smaller than transaction costs and gives the self-improvement loop a target closer to realizable profit.

**Evidence/reasoning.** Current Polymarket taker fees can be 4–7% in the fee formula depending on category, while makers are fee-free [R18]. At 50¢, a 5% category charges 1.25¢/share—material relative to Phil's 2–7 point experimental edge bands. Polymarket documents partial fills and size-dependent price impact [R20][R21]. PolyBench's explicit CLOB execution modelling is a more appropriate benchmark style for a prediction-market trader [R9].

**Tradeoffs/uncertainties.** More data storage and API calls; exact historical queue simulation remains impossible without full event-level order-book history. But a better taker VWAP model and exact fees are still a major improvement over one-price full fills.

**Priority:** **P0.**

### Improvement 4 — Preserve blind forecasts, but trade a separately calibrated market-aware posterior

**What should change.** Record two distinct probabilities:

1. `p_blind`: Phil's estimate formed before seeing current price, used to measure independent research quality;
2. `p_trade`: a frozen/calibrated posterior combining `p_blind`, market midpoint, and possibly a very small number of predeclared context variables.

Start with a simple model that is hard to overfit—e.g. cross-fitted logistic or linear pooling in log-odds space. Fit only on point-in-time available history. Use `p_trade - executable_net_price` for betting while continuing to score `p_blind` separately.

**Why it should help.** The market midpoint currently beats Phil's raw forecasts overall, so ignoring it wastes information. Yet the in-sample blend suggests Phil may contribute a small residual. A disciplined pool can exploit that residual without giving equal authority to a noisier model.

**Evidence/reasoning.** Current snapshot: agent Brier +0.00824 worse than market; best in-sample blend is ~79% market overall and ~81% market on disagreement rows, with only tiny Brier improvement. Halawi et al. find gains from retrieval plus aggregation [R6]. KalshiBench reports systematic overconfidence in frontier LLMs [R8]. PolySwarm also combines agent and market probabilities, although its specific aggregation and performance claims are preliminary [R11].

**Tradeoffs/uncertainties.** The apparent blend improvement is in-sample and small enough to vanish. A single global weight may be mis-specified across categories/horizons. More flexible calibration should be deferred until event-level sample sizes are large.

**Success gate.** Pre-register a fixed blend/calibration form and require negative market-relative Brier on a future event-level sample **and** positive net fee-aware decision value before using it to increase real exposure.

**Priority:** **P0/P1.**

### Improvement 5 — Move active decision rules into a hard broker-enforced policy artifact

**What should change.** Create a protected enforcement layer that reads a frozen, validated `active_policy.json` generated from agent proposals. It should enforce at placement time:

- minimum and maximum edge using `p_trade` and net executable price;
- maximum spread;
- max stake per event/dependency group;
- max new positions per cycle;
- minimum time to resolution;
- banned shapes;
- allowed category/edge class;
- one-per-event rules where applicable;
- current `policy_rev` and experiment ID.

Alternatively, add these checks directly to `core/ledger.py`, but keeping agent-editable thresholds separate from protected hard ceilings can preserve the existing governance model.

**Why it should help.** It guarantees paper reality matches the policy being evaluated and prevents direct placement from bypassing upstream screening assumptions.

**Evidence/reasoning.** The placement gap is directly visible in `core/ledger.py:68-92`; replay enforces more rules than live paper placement. `config/protected.json:max_new_positions_per_cycle` has no placement check. `strategy/risk.json:max_stake_per_event_usd` is descriptive without a broker-side event accumulator.

**Tradeoffs/uncertainties.** Hard enforcement reduces improvisational flexibility and requires defining canonical events. The answer is to make policy updates explicit and versioned, not to leave enforcement implicit.

**Priority:** **P1.**

### Improvement 6 — Pre-register a single fee-aware No-side asymmetry experiment

**What should change.** Freeze one hypothesis such as:

- only consider the complement side when blind estimate is below executable market probability by a preselected band;
- choose one exact floor/band before any new outcomes;
- require spread ≤ a preselected cap;
- one bet per event/dependency group;
- subtract exact taker fees and simulated depth costs;
- fixed flat stake;
- evaluate event-clustered net return plus market-relative Brier;
- set an event-count gate and concentration limit.

The exact band should be chosen from development data once, recorded, then left untouched through the test.

**Why it might help.** The current gross counterfactual asymmetry is large enough to justify testing: No-side returns are positive across multiple adjacent thresholds while Yes-side returns are negative. This could reflect a stable directional calibration bias.

**Why it may fail.** It is one of many inspected slices; rows are correlated; current sweeps ignore fees; prices/market regimes evolve; and an LLM's directional bias can change as its playbook changes. The apparent effect may be a historical accident.

**Supporting evidence.** Internal threshold sweep; latest deep retro. General LLM overconfidence in KalshiBench provides a plausible mechanism but does not establish this particular asymmetry [R8].

**Priority:** **P1, experiment only.**

### Improvement 7 — Replace divergence-first research allocation with measured value-of-information routing

**What should change.** Treat research-slot allocation as a contextual decision problem. Start with deterministic, interpretable priorities rather than another high-capacity learned ranker:

1. official scheduled releases with a reachable primary source and unambiguous resolution;
2. cross-market/event constraints where a deterministic inconsistency can be checked;
3. recent price moves with a timestamped catalyst that can be independently verified;
4. families with already pre-registered positive OOS residual skill;
5. a fixed random-tail audit sample to continue discovering failure modes/opportunities.

Use the forecast ledger to estimate **marginal value of research**: change from pre-research/blind prior to post-research forecast, relative to contemporaneous market movement and eventual outcome. Penalize time/API/tool cost only after prediction quality is measured cleanly.

**Why it should help.** Research is the scarce resource, not market candidates. Phil's own memos have already rejected divergence and an empirical-Bayes research-value prior as demonstrated predictors. Continuing to allocate primarily by divergence risks spending expensive reasoning on precisely the classes where the LLM invents disagreement.

**Evidence/reasoning.** `journal/screener-rank-decision.md` and `journal/screener-value-decision.md` document the weak predictive value of current ranking. The lane coverage memo finds 609 mechanical economic markets, 66% beyond the default 336-hour scan horizon, yet also shows that price information improves sharply only much closer to release; this argues for a **calendar-triggered lane**, not indiscriminate horizon widening.

**Tradeoffs/uncertainties.** Narrow routing may miss novel unscheduled information. Preserve exploration with a random sample and track opportunity cost.

**Priority:** **P1.**

### Improvement 8 — Turn the dormant economic calendar into a pre-triggered official-source lane

**What should change.** Activate/repair the release-calendar workflow so known BLS/BEA/central-bank/official-series markets enter research roughly 48–72 hours before the release, with a fresh check near release time. Build source adapters that record release timestamps, final values, and exact resolution mappings.

**Why it might help.** The lane-coverage memo reports that many economic-print markets sit beyond the general scan window, but also that seven-day pricing is not much more informative than one-day pricing until a late convergence. A calendar lane can avoid continuously scanning long-dated markets while guaranteeing they are present when the information becomes actionable.

**Critical caveat.** The same memo reports 34 calendar-tier forecasts and zero bets at the time of analysis, so merely seeing more markets is not enough. Conversion logic and net edge must be validated.

**Priority:** **P1.**

### Improvement 9 — Build a deterministic event graph and cross-market consistency solver

**What should change.** Add a normalized event layer that maps markets to:

- underlying event and resolution timestamp;
- mutually exclusive / collectively exhaustive outcomes;
- complements;
- ordered thresholds and brackets;
- conditional dependencies;
- cross-venue equivalents where resolution rules truly match.

For each group, compute executable constraints using bid/ask, fees, and size. Examples include sum-of-outcome probability bounds, monotonicity of threshold contracts, complement parity, bracket consistency, and equivalent claims across venues.

**Why it should help.** Phil's current real-money allowlist is only `cross-market`, so this directly improves the only class eligible for real twins. Deterministic inconsistency detection also reduces reliance on free-form LLM forecasting.

**Evidence/reasoning.** PolySwarm explicitly explores negation-pair and cross-market inefficiencies [R11]. Phil itself repeatedly performs sibling censuses and one-per-event reasoning, which suggests the structure is already useful but mostly manual.

**Tradeoffs/uncertainties.** Resolution language can make apparently equivalent markets non-equivalent; fees and shallow depth often eliminate theoretical arbitrage. The event graph therefore needs a resolution-criteria verifier and should label constraints as “semantic candidate” versus “executable verified.”

**Priority:** **P1.**

### Improvement 10 — Replace the monolithic active playbook with structured policy memory

**What should change.** Keep `strategy/playbook.md` as a historical/evidence document if desired, but make active rules machine-readable records such as:

```yaml
rule_id: no_side_small_edge_v1
scope: [general]
status: hypothesis | active | rejected | retired
trigger: ...
action: ...
evidence_cutoff: ...
independent_events: 0
primary_metric: ...
promotion_gate: ...
kill_gate: ...
supersedes: ...
last_reviewed: ...
source_experiments: [...]
```

At cycle time, retrieve only active rules relevant to the market category/event type, plus universal risk rules. Retain the immutable evidence and rejected-rule archive for auditing.

**Why it should help.** A 6,770-line prompt-like policy invites context dilution, conflicting rules, accidental resurrection of old findings, and high token cost. Structured retrieval makes “what rule actually governed this bet?” answerable.

**Evidence/reasoning.** FinMem demonstrates the general value of layered memory architectures [R4]; FinAgent likewise emphasizes diversified memory/reflection [R5]. AlphaEvolve's explicit archive/evaluator model suggests separating active candidates from historical population [R3]. EvolveTrade's policy-as-object framing is especially close [R1].

**Tradeoffs/uncertainties.** Compression can omit nuance or failure evidence. Preserve full provenance and make retrieval deterministic/testable. Do not let the LLM silently rewrite the evidence history.

**Priority:** **P1.**

### Improvement 11 — Repair external-data/tool availability, but evaluate each tool as an instrument

**What should change.** Add health checks and automatic lane fallback for external sources:

- if `ODDS_API_KEY` is unavailable, sports strategies requiring bookmaker consensus should be marked unavailable before research slots are spent;
- restore Mech/second-opinion uptime only under a registered experiment that measures incremental Brier/value;
- log tool version, request, latency, output, and whether it changed `p_blind` or `p_trade`.

The latest deep retro reports no `ODDS_API_KEY`, no new `mlb-moneyline` rows since Sep 16, and no Mech tools for about 51 hours. Those are operational confounders in any apparent strategy trend.

**Why it should help.** A strategy cannot learn reliably when its information set changes silently. Tool outages should become explicit state, not hidden regime shifts.

**Tradeoffs/uncertainties.** More observability does not make a tool predictive. Each data source still needs an incremental-value test.

**Priority:** **P1/P2.**

### Improvement 12 — Use multi-agent opinions only when they add independent, measured information

**What should change.** Retain Phil's “own estimate first” discipline. For second opinions, use role/source diversity:

- official-source fact checker;
- base-rate historian;
- market-structure/odds parser;
- resolution-criteria lawyer/skeptic;
- general forecaster.

Score each role on **residual** Brier improvement after the market and Phil baseline. Aggregate only roles with prospective residual skill. A blind and market-aware version can be compared as Phil's current Mech experiment already contemplates.

**Why it might help.** Specialized agents can catch different error modes; TradingAgents and PolySwarm report benefits from role diversity/aggregation [R10][R11].

**Why it may fail.** Same-family LLM agents are correlated and can amplify the same hallucination. Phil's Haiku screening experience is direct evidence that more LLM judgments do not automatically create signal.

**Priority:** **P2.**

### Improvement 13 — Test maker/taker routing rather than always crossing the spread

**What should change.** Add a decision layer based on edge half-life. For slow information, shadow a passive limit order with deadline/cancel rules. For fast information races, use a marketable/taker path. Compare realized/shadow execution.

**Why it might help.** Makers pay no Polymarket fee and may receive rebates [R18][R19]. A saved 1–1.75¢/share around 50¢ can be a large fraction of Phil's hypothesized edge.

**Risk.** Passive fills are selected: the market may trade into Phil precisely when new information invalidates its estimate. Without a prospective queue/fill experiment, backtesting maker execution would be fiction.

**Priority:** **P2.**

### Improvement 14 — Add event/factor risk accounting before any size increase

**What should change.** Assign every trade to event and latent factor groups (same speech, same election, same macro release, same match, same company announcement). Enforce `max_stake_per_event_usd` in the broker, not just in prose. Report P&L and Brier at both row and event levels.

**Why it should help.** It prevents one information thesis expressed in many markets from masquerading as diversification or many independent wins. v3's Bank of Israel siblings are the clearest historical example.

**Tradeoffs/uncertainties.** Factor mapping is subjective. Start with strict exact-event grouping and only then add broader factors.

**Priority:** **P2.**

### Improvement 15 — Keep flat sizing until calibration earns the right to use Kelly

**What should change.** Do not increase size based on raw LLM edge. If a fee-aware `p_trade` eventually shows stable prospective calibration and positive net value, test small fractional Kelly or a lower-confidence-bound Kelly calculation under hard caps and event limits.

**Why.** Kelly magnifies probability errors as well as true edge. Current aggregate Phil forecasts are worse than the market, extreme disagreements have historically been dangerous, and v3's own experiments say Kelly/edge-scaled sizing lowered its historical score.

**Comparison.** PolySwarm uses quarter-Kelly [R11], but copying that sizing rule would assume a level of calibration that Phil has not demonstrated. Current flat $5 paper / $1 real caps are appropriate while the main uncertainty is whether edge exists at all.

**Priority:** **P2; no scale-up now.**

### Improvement 16 — Automate “fact finality” for information-race markets

**What should change.** Build deterministic official-source adapters for recurring classes—economic releases, central-bank decisions, official sports results, app-store rankings where a canonical feed exists, and similar rule-defined sources. Store source timestamp, parsed value, final/provisional status, and market-resolution mapping. Only let an “information race” trade fire once the source is both fresh and resolution-relevant.

**Why it should help.** Phil's retros repeatedly distinguish a true finalized fact from provisional reports or interpretive evidence. An LLM is best used to map rules and handle exceptions; a deterministic adapter should handle recurring structured facts.

**Tradeoffs/uncertainties.** Every source has revisions, outages, and changing formats. The source adapter itself becomes critical infrastructure and needs tests.

**Priority:** **P2.**

### Improvement 17 — Add decomposition metrics for whether research itself helped

**What should change.** For each candidate, ideally record:

- pre-research prior;
- blind post-research estimate;
- contemporaneous market midpoint before and after research;
- calibrated trade posterior;
- decision and net executable price;
- resolution.

Report calibration/reliability, discrimination, log loss, Brier residual vs market, research delta, and net decision value. For skipped candidates, compute whether the gate saved or cost expected value using a predeclared counterfactual.

**Why it should help.** It separates “good research, bad calibration,” “good calibration, no executable edge,” and “bad research correctly vetoed.” This is more actionable than one aggregate P&L number.

**Tradeoffs/uncertainties.** More metrics create more multiple-testing opportunities. Designate a small primary metric set; use diagnostics for explanation rather than promotion.

**Priority:** **P2.**

---

## 8. Ideas considered but **not** recommended now

### 8.1 Do not adopt `strategy/policy.py` v3

It failed its pre-registered prospective gate. Later positive raw P&L does not retroactively change the registered decision rule, and current `cw_return` remains negative on the expanded forward set.

### 8.2 Do not raise stakes or switch to aggressive Kelly sizing

There is no demonstrated aggregate market-relative calibration edge. Size optimization before edge validation increases variance and can turn estimation error into loss.

### 8.3 Do not simply lower the minimum edge because more bets produce more data

Current Polymarket fees make 2–4 point gross edges expensive in many categories [R18]. A smaller threshold only makes sense after fee-aware calibration and execution modelling.

### 8.4 Do not simply raise the minimum edge either

The current Yes-side sweep gets worse at larger claimed edges, consistent with overconfidence. “Bigger LLM disagreement” is not the same thing as more alpha.

### 8.5 Do not replace Haiku divergence with raw uncertainty or the already-tested empirical-Bayes prior

Phil's own screener studies reject those alternatives as demonstrated improvements. A new ranking algorithm should be tested against random allocation and the current baseline prospectively.

### 8.6 Do not add many more generic LLM agents without independent information

Multi-agent literature is promising [R10][R11], but Phil's own screening results show correlated LLM judgments can spend resources without producing forecast improvement. Role/source independence matters more than persona count.

### 8.7 Do not indiscriminately widen the general market scan to months

The economic-lane memo shows long-horizon availability but also suggests much of the useful price convergence happens closer to release. A calendar-triggered lane is more efficient than scanning everything continuously.

### 8.8 Do not promote category winners from current tables

With dozens of categories, thresholds, skip reasons, and time windows inspected, the best-looking cells are subject to selection. They are hypothesis generators only unless they survive a frozen future test.

---

## 9. Prioritized implementation roadmap

### Phase A — Measurement and enforcement core (P0)

The objective is not higher backtest P&L; it is to make later evidence trustworthy.

| Priority | Change | Concrete implementation | Why it should help | Main risks / uncertainty | Success criterion | Sources |
|---|---|---|---|---|---|---|
| **P0.1** | Point-in-time replay | filter training labels by `settled_ts`; event purge/embargo; leakage regression tests | prevents learned policies using outcomes unavailable in real time | smaller samples; event mapping complexity | zero deliberately injected late-label leakage; forward metrics reproducible | internal `core/replay.py`; [R7][R9][R13] |
| **P0.2** | Experiment registry | append-only experiment IDs, data cutoff, all tried variants, frozen gates | controls adaptive search/selection | process overhead | every strategy-changing rule links to a registered hypothesis and untouched forward window | [R14][R15] |
| **P0.3** | Fee/depth-aware simulator | fee status/rate, L2 depth, VWAP/partial fill, timestamps, net P&L | removes gross edges that cannot survive execution | queue simulation imperfect | paper replay reproduces actual taker fills within a measured error band once real fills exist | [R18][R20][R21] |
| **P0.4** | Blind vs trade posterior | keep `p_blind`; cross-fit simple market-aware `p_trade` | uses strong market prior while retaining measurable independent signal | tiny observed blend gain may vanish | future event-level Brier < market and positive net decision value | [R6][R8][R9] |

### Phase B — Policy integrity and focused prospective experiments (P1)

| Priority | Change | What should change | Why | Evidence | Risks / uncertainty | Supporting sources |
|---|---|---|---|---|---|---|
| **P1.1** | Broker-enforced active policy | exact edge/spread/event/time/pacing/bans at placement; immutable `policy_rev` | paper execution must match replay and written strategy | current `ledger.py` enforcement gap | reduced flexibility; event IDs required | internal code |
| **P1.2** | No-side preregistered test | one exact fee-aware No-side rule, one per event, fixed sample/gates | strongest current asymmetric hypothesis | gross No sweeps positive; Yes negative | hindsight/multiple-testing/correlation may explain it | [R8] plus internal score |
| **P1.3** | Value-of-information research routing | official-source, cross-market, catalyst, validated-family lanes + random audit | current divergence ranking not validated | internal screener memos | narrower routing can miss novelty | [R6][R9] |
| **P1.4** | Economic calendar lane | pre-trigger 48–72h + near-release refresh | fixes known discovery timing without broad scan expansion | lane-coverage memo | previous calendar forecasts did not convert to bets | internal lane memo |
| **P1.5** | Event graph / consistency solver | canonical events, complement/exhaustive/threshold constraints, fee-aware executable checks | aligns with real allowlisted `cross-market` class | sibling/cross-market work already recurring | subtle resolution differences; execution risk | [R11] |
| **P1.6** | Structured policy memory | active rules registry; historical evidence archive; deterministic retrieval | reduces 6,770-line context drift | current playbook growth; memory literature | compression/retrieval omissions | [R1][R3][R4][R5] |

### Phase C — Operational and execution alpha (P2)

| Priority | Change | What should change | Expected benefit | Key uncertainty | Sources |
|---|---|---|---|---|---|
| **P2.1** | Tool health + provenance | detect Odds/Mech outage, route quota elsewhere, score tool contribution | avoids hidden information-regime changes | restored tools may still add no edge | internal retro; [R10] |
| **P2.2** | Specialized multi-agent ensemble | source-diverse roles, residual OOS weighting | possible error diversification | correlated models/hallucination | [R10][R11] |
| **P2.3** | Maker/taker router experiment | passive slow-signal shadow orders, taker fast-signal default | fee avoidance / better price | adverse selection/non-fill | [R18][R19][R20] |
| **P2.4** | Event/factor exposure | canonical event groups and hard event cap | reduces false diversification/concentration | mapping ambiguity | internal v3 evidence |
| **P2.5** | Finality adapters | official structured feeds + final/provisional state | faster, less ambiguous information-race execution | source format/revision risk | internal retros |
| **P2.6** | Rich research attribution | prior → researched belief → market-aware posterior → trade | identifies which step actually adds value | more diagnostics can invite overfitting | [R6][R23] |

### Phase D — Scale only after evidence

Only after a frozen `p_trade` and execution policy produce sufficiently large prospective event-level evidence of positive **net** edge should Phil consider fractional Kelly, larger real stake caps, or broader real edge classes. Any scale change should itself be a protected/operator decision, consistent with the current architecture.

---

## 10. Detailed prioritized list in the requested format

### 1. Repair point-in-time replay and purge dependent events — **P0**

**What should change:** training data must be restricted to labels known at the test decision time; add event grouping/purging and regression tests.  
**Why it should help:** prevents false improvements caused by future resolution leakage and sibling dependence.  
**Evidence/reasoning:** current 5-fold replay has 180 unavailable-label training inclusions and 10-fold has 418; `--after` already demonstrates the correct settlement-time concept. Purged validation is designed for overlapping financial labels [R13].  
**Tradeoffs/risks/uncertainties:** less data per fold, noisier estimates, nontrivial event mapping.  
**Supporting sources:** internal `core/replay.py:77-94,208-244`; [R7], [R9], [R13].

### 2. Register every strategy search and require untouched prospective promotion — **P0**

**What should change:** append-only experiment registry, frozen hypothesis/metric/gates, full variant count, forward promotion window.  
**Why it should help:** Phil's adaptive self-editing creates many implicit trials; accounting for search reduces false discovery.  
**Evidence/reasoning:** v3 looked excellent in-sample and then failed its registered forward gate; selection-bias research directly warns about backtest search [R14][R15].  
**Tradeoffs/risks/uncertainties:** slows adaptation; formal corrections are imperfect under dependence.  
**Supporting sources:** `strategy/policy.py:42-56`; `journal/operator-notes.md:723-738`; `journal/proposals.md:2252-2257`; [R14], [R15].

### 3. Make replay/paper P&L fee-, depth-, and partial-fill-aware — **P0**

**What should change:** store fee status/rate, depth, timestamps, VWAP/partial fills, normalized real fees and slippage; score net P&L.  
**Why it should help:** eliminates nominal probability edges that are not economically executable.  
**Evidence/reasoning:** current taker fees can consume a large fraction of 2–4 point edge around 50¢; current code discards book size. Polymarket documents fees, partial fills, and depth effects [R18][R20][R21].  
**Tradeoffs/risks/uncertainties:** extra storage/API complexity; passive queue simulation remains approximate.  
**Supporting sources:** `core/pmapi.py:42-47`; `core/ledger.py:88-109`; [R18], [R19], [R20], [R21], [R9].

### 4. Separate independent forecasting from the market-aware trading posterior — **P0/P1**

**What should change:** retain `p_blind`; add simple cross-fitted `p_trade` pooling market and agent; trade only from `p_trade` net edge.  
**Why it should help:** the market is currently a better forecaster, but Phil may contain a small residual signal. Shrinkage uses both rather than forcing a false either/or choice.  
**Evidence/reasoning:** current agent Brier is +0.00824 worse than market; in-sample optimum weights market about 79–81% and improves Brier only slightly. Forecasting research favors retrieval/aggregation and highlights LLM overconfidence [R6][R8].  
**Tradeoffs/risks/uncertainties:** the tiny residual improvement may disappear prospectively; category-specific models can overfit.  
**Supporting sources:** internal forecast ledger/`blend_sweep`; [R6], [R7], [R8], [R9].

### 5. Hard-enforce the active strategy at the broker choke point — **P1**

**What should change:** enforce edge, spread, event cap, per-cycle cap, time-to-resolution, banned shapes, and policy revision in `ledger.py` or a protected compiled-policy layer.  
**Why it should help:** makes actual paper behavior match the evaluated policy and closes direct-call bypasses.  
**Evidence/reasoning:** placement currently checks only a subset of protected/strategy conditions; replay checks more than paper placement.  
**Tradeoffs/risks/uncertainties:** stronger coupling between policy schema and broker; needs canonical event IDs.  
**Supporting sources:** internal `core/ledger.py:68-92`; `core/replay.py:120-152`; `config/protected.json`; `strategy/risk.json`.

### 6. Prospectively test, rather than adopt, the No-side asymmetry — **P1**

**What should change:** one pre-registered, fee-aware No-side rule with exact band, one trade/event, flat size, fixed evaluation horizon.  
**Why it might help:** current complement-side gross returns are positive over neighboring thresholds while Yes-side returns are negative.  
**Evidence/reasoning:** at a 5-point floor the current No sweep is 129 rows / +10.07% gross one-unit ROI; at 7 points, 107 / +11.62%; corresponding Yes sweeps are negative. The latest deep retro independently flags the slice.  
**Tradeoffs/risks/uncertainties:** hindsight selection, seven tested thresholds, same-event correlation, no fees; effect may vanish.  
**Supporting sources:** internal `core/score.py:151-181`; latest deep retro; calibration caution [R8].

### 7. Reallocate research by value of information, not raw divergence — **P1**

**What should change:** prioritize official scheduled data, deterministic cross-market constraints, fresh verifiable catalysts, and prospectively validated families; retain random-tail audit exploration.  
**Why it should help:** spend expensive reasoning where information can plausibly change a decision and be verified.  
**Evidence/reasoning:** Phil's own screener-ranking and value memos find no demonstrated lift from current divergence/uncertainty ranking or the attempted prior.  
**Tradeoffs/risks/uncertainties:** deterministic lanes can become crowded; may miss novel soft-information markets.  
**Supporting sources:** internal `journal/screener-rank-decision.md`, `journal/screener-value-decision.md`; retrieval evidence [R6].

### 8. Build an event graph and executable cross-market solver — **P1**

**What should change:** normalize event semantics, siblings, complements, thresholds, brackets, and cross-venue equivalents; solve only fee/depth-adjusted executable inconsistencies.  
**Why it should help:** creates a more mechanical source of edge and directly targets the only real-money edge class currently allowlisted.  
**Evidence/reasoning:** current real config allows `cross-market`; Phil repeatedly reasons about siblings manually; PolySwarm explores cross-market/negation inefficiencies [R11].  
**Tradeoffs/risks/uncertainties:** semantic mismatch between resolution rules can turn “arbitrage” into basis risk; depth/fees erase many opportunities.  
**Supporting sources:** internal config/notes; [R11], [R18].

### 9. Activate a scheduled official-release lane with source finality — **P1/P2**

**What should change:** calendar trigger for known releases, deterministic official-source adapters, final/provisional status, exact market mapping.  
**Why it should help:** ensures high-quality mechanically resolvable markets are present near information time without continuously widening the scan.  
**Evidence/reasoning:** lane memo says 66% of 609 mechanical economic markets were outside the 336h horizon, but the existing calendar lane had 34 forecasts and zero bets—showing that discovery and conversion must be solved together.  
**Tradeoffs/risks/uncertainties:** crowded releases, source revisions, timestamp race, prior lack of conversion.  
**Supporting sources:** internal `journal/lane-coverage-decision.md`.

### 10. Convert the active 6,770-line playbook into structured policy memory — **P1**

**What should change:** machine-readable active rule registry with status, scope, evidence, gates, supersession, and provenance; keep full evidence archive separately.  
**Why it should help:** reduces contradictory/stale context, token bloat, and difficulty attributing decisions to a rule.  
**Evidence/reasoning:** playbook is 6,770 lines and still growing; related agent research uses layered/diversified memory and explicit policy archives [R1][R3][R4][R5].  
**Tradeoffs/risks/uncertainties:** retrieval can omit nuance; migration can lose history unless provenance is preserved.  
**Supporting sources:** internal playbook/deep retro; [R1], [R3], [R4], [R5].

### 11. Instrument and repair external tools as controlled information sources — **P1/P2**

**What should change:** health checks, fallback routing, provenance and incremental-value scoring for Odds API and Mech opinions.  
**Why it should help:** avoids silent strategy degradation when a required information channel disappears.  
**Evidence/reasoning:** latest deep retro reports missing Odds API and a prolonged absence of Mech calls.  
**Tradeoffs/risks/uncertainties:** restored uptime may add cost without edge.  
**Supporting sources:** internal `DEEP-2026-09-26.md`; multi-agent caution [R10][R11].

### 12. Test maker/taker routing for slow signals — **P2**

**What should change:** passive limit-order shadow/live micro-experiment with deadline and markout measurement; keep taker default for decaying information races.  
**Why it might help:** makers pay no platform fee and may earn rebates; avoiding 1–1.75¢/share around 50¢ is economically significant.  
**Evidence/reasoning:** current Polymarket fee and maker-rebate docs [R18][R19].  
**Tradeoffs/risks/uncertainties:** adverse selection, non-fills, queue uncertainty; $1 rebate payout floor makes rebate income insignificant at tiny scale.  
**Supporting sources:** [R18], [R19], [R20].

### 13. Enforce event/factor risk accounting — **P2**

**What should change:** canonical event IDs and broker-side event exposure caps; event-clustered performance reports.  
**Why it should help:** prevents one thesis represented by many sibling contracts from dominating P&L and evidence.  
**Evidence/reasoning:** v3's Bank of Israel siblings contributed most of the attractive backtest profit; `max_stake_per_event_usd` currently exists but is not broker-enforced.  
**Tradeoffs/risks/uncertainties:** event/factor mapping can be subjective.  
**Supporting sources:** internal `strategy/policy.py:42-56`; `strategy/risk.json`.

### 14. Use genuinely diverse, OOS-scored second opinions — **P2**

**What should change:** assign differentiated source roles and weight agents only by prospectively measured residual skill; keep Phil's blind estimate first.  
**Why it might help:** reduces single-model error if information sources are actually independent.  
**Evidence/reasoning:** multi-agent systems report gains, while Phil's own Haiku screening warns against assuming ensemble value [R10][R11].  
**Tradeoffs/risks/uncertainties:** cost, latency, correlated hallucination, ensemble overfitting.  
**Supporting sources:** [R10], [R11], [R5].

### 15. Keep flat sizing until a fee-aware posterior is prospectively calibrated — **P2**

**What should change:** no stake increase now; later test small fractional Kelly only on a frozen `p_trade` with strong OOS calibration and hard event caps.  
**Why it should help:** avoids magnifying probability error.  
**Evidence/reasoning:** aggregate forecasts currently trail the market; historical edge-scaled/Kelly variants did not improve v3's evidence; live-benchmark research emphasizes risk control [R12][R17].  
**Tradeoffs/risks/uncertainties:** flat sizing may underuse a real edge if one emerges, but that is preferable to leveraging an unproven one.  
**Supporting sources:** internal policy notes; [R12], [R17].

---

## 11. What would constitute convincing evidence of improved profitability?

A reasonable promotion ladder for this specific system would be:

1. **Forecast skill:** on an untouched future set grouped by independent event, `p_trade` has negative Brier delta versus the contemporaneous market midpoint, with a confidence interval or registered sequential test that excludes a trivial/no-effect region meaningful for the intended strategy.
2. **Decision skill:** a frozen selection rule converts that residual forecasting skill into positive **net** expected value after fees and realistic executable prices, without one event dominating results.
3. **Execution transfer:** real micro-stake fills show bounded slippage from the fee/depth-aware paper model and no systematic adverse-selection surprise.
4. **Replication:** the result survives a second future window or different market regime without modifying the rule between observations.
5. **Only then, sizing:** gradual protected cap increases or fractional Kelly are tested as a separate experiment.

This ladder is intentionally harder than “positive P&L over N bets.” Prediction-market payoffs are skewed, categories shift, and an adaptive agent can inspect many patterns. The goal is not to make Phil conservative forever; it is to ensure that when it scales, the evidence being scaled is more likely to be real.

---

## 12. Strengths worth preserving

Several design choices should survive a refactor:

- **Protected core vs editable strategy.** This is a sound governance boundary, even though enforcement needs to be completed.
- **Market-relative Brier as a first-class metric.** It prevents lucky P&L from being mistaken for forecasting skill.
- **Forecasting skipped candidates.** This makes gate quality measurable and avoids judging only selected bets.
- **Superseded-forecast bookkeeping.** Old beliefs remain gradeable, which makes revisions falsifiable.
- **Pre-price independent estimate.** Keep it for signal attribution even if a market-aware posterior drives actual trades.
- **Prospective registered tests.** The v3 rejection is a success of the scientific process, not a failure of the project.
- **Random-tail screening sample.** Preserve some unbiased exploration while optimizing research allocation.
- **Real-money micro caps.** Given the lack of demonstrated aggregate edge and absence of supplied real fills, the current tiny real exposure is appropriate.

---

## 13. Bottom line

Phil already embodies an unusually important insight about “self-improving” trading agents: the valuable adaptive object may be the **procedure around a fixed LLM**—what it researches, what it trusts, how it records probabilities, how it vetoes itself, and how it turns evidence into policy. Current research, especially EvolveTrade, independently moves in the same direction [R1].

The snapshot also shows the main danger of that idea. A procedure that can continuously rewrite itself can overfit its own history faster than a static strategy. Phil's explicit v3 forward-test failure, weak aggregate Brier relative to market, screening null results, and current replay label leakage all point to the same priority: **improve the experimental apparatus before increasing the search power of the agent.**

The highest-probability path to better profitability is therefore a sequence:

**clean point-in-time evaluation → net execution economics → market-aware calibrated posterior → hard policy enforcement → one-at-a-time prospective edge tests → deterministic cross-market/source automation → only then more sizing and broader real deployment.**

Nothing in the supplied evidence justifies a claim that profitability will improve from any single proposed change. What the recommendations do is improve the probability that Phil can distinguish a real, executable edge from adaptive backtest noise—and that is the prerequisite for sustainable profitability.

---

## Appendix A — Repository evidence index

Key internal references used in this report:

- `README.md:7-12,20-30,34-48,52-83` — architecture, self-improvement, Brier emphasis, real twin, paper fills, stated caps.
- `CLAUDE.md:3-5,9-20,26-31,43-49` — cycle loop, protected/editable boundary, calibration and real trading.
- `CYCLE.md:8-35,42-52,108-150,151-318` — hard rules, tick types, retro, scanning/screening, research, forecasts, placement, commit flow.
- `loop.sh:99-142,159-202` — model selection, allowed tools, protected-file reversion.
- `config/protected.json` — protected simulation/screener/real caps and allowed real edge classes.
- `strategy/risk.json` — current editable stake/edge/spread/event thresholds.
- `core/ledger.py:68-119` — actual paper broker enforcement and fill fields.
- `core/pmapi.py:42-47` — best bid/ask extraction without size.
- `core/forecast.py:50-61,90-176` — revision and extreme-disagreement controls; point-in-time fields.
- `core/score.py:31-64,67-181,184-208` — Brier, threshold sweeps, blending, superseded-row handling.
- `core/replay.py:77-105,120-152,208-244` — replay universe, policy visibility, fill filters, forward and ordinary replay.
- `strategy/policy.py:11-63,66-99` — v3 rules and explicit in-sample caveat.
- `journal/operator-notes.md:708-739` — v3 forward-test pre-registration.
- `journal/proposals.md:2252-2257` — v3 forward-test failure.
- `core/real.py:180-250` — real twin gating and order submission.
- `core/validate.py:86-110` — current real-enabled validation behavior; compare stale docstring at lines 8-9.
- `journal/screener-rank-decision.md` — screening rank audit.
- `journal/screener-value-decision.md` — research-value-prior audit.
- `journal/lane-coverage-decision.md` — economic/politics lane coverage and timing.
- `journal/retros/DEEP-2026-09-26.md` — latest supplied deep-retro state.

---

## Appendix B — Snapshot calculations and interpretation

### B.1 Paper ledger

From 47 settled rows:

```text
stake = 235.00
pnl = -8.5391
roi = pnl / stake = -0.0363366
```

Bet Brier comparison:

```text
agent  = mean((est_prob - y)^2)             = 0.2963799
market = mean((market_prob_at_entry - y)^2) = 0.2091454
delta  = +0.0872345
```

Note that `market_prob_at_entry` in `ledger.py` is the **ask**, not midpoint. `core/score.py` correctly keeps bet and forecast Brier sections separate because the forecast baseline is midpoint.

### B.2 Forecast ledger

```text
all rows                       1,161
superseded                       156
non-superseded                 1,005
settled non-superseded           875
open non-superseded              129
```

Headline Brier:

```text
agent  = 0.1708523
market = 0.1626129
delta  = +0.0082394
```

### B.3 Blend

For `p_blend = w * p_market + (1-w) * p_agent`, the least-squares weight on the current same-sample data is:

```text
all rows:          w_market ≈ 0.79055
Brier market       0.1626129
Brier blend        0.1619909
same-sample delta -0.0006220

disagreement >=5pp:
w_market ≈ 0.80750
same-sample delta vs market ≈ -0.0016093
```

This is **not out-of-sample calibration evidence**.

### B.4 Replay leakage check

The replay universe is 861 settled, non-superseded rows with a recorded ask. For each fold, I counted prior-record-time training rows where `settled_ts` occurs after the first test row's `ts`.

```text
5 folds:  [48, 54, 20, 58]                      = 180 inclusions
10 folds: [51, 49, 97, 56, 25, 13, 27, 58, 42] = 418 inclusions
```

Again, these are fold-level inclusions; a row can appear in multiple later training sets.

### B.5 Frozen v3 forward rule on the current snapshot

Using cutoff `2026-09-02T00:14:36Z` and independently reproducing v3 plus replay fill filters:

```text
rows settled after cutoff: 441
bets:                     58
wins:                     37
staked:                   $290
pnl:                      +$20.6243
raw ROI:                  +7.11%
cw_return:                -0.0975
selected-row Brier delta: -0.00187
largest winner:           +$39.6429
```

The rule remains risk/concentration fragile and was already formally rejected at the pre-registered first decision point.

---

## References

**Source quality note:** `[R4]`, `[R7]`, `[R13]`, and `[R14]` are published/proceedings or journal sources; several current agent papers are arXiv preprints and are labelled as such below. `[R18]`–`[R22]` are first-party Polymarket documentation and are authoritative for current platform mechanics, though platform rules can change.

1. **[R1] Kim, Sehee; Choi, Yumin; Kang, Minki; Hwang, Sung Ju. _EvolveTrade: Experience-Driven Policy Refinement for Self-Evolving LLM Trading Agents_.** arXiv:2609.17632, submitted **2026-09-15**. Preprint. https://arxiv.org/abs/2609.17632

2. **[R2] Wang, Saizhuo; Yuan, Hang; Ni, Lionel M.; Guo, Jian. _QuantAgent: Seeking Holy Grail in Trading by Self-Improving Large Language Model_.** arXiv:2402.03755, submitted **2024-02-06**. Preprint. https://arxiv.org/abs/2402.03755

3. **[R3] Google DeepMind. _AlphaEvolve: A Gemini-powered coding agent for designing advanced algorithms_.** **2025-05-14**; related impact update in 2026. https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/  
   Impact update: https://deepmind.google/blog/alphaevolve-impact/

4. **[R4] Yu, Yangyang et al. _FinMem: A Performance-Enhanced LLM Trading Agent with Layered Memory and Character Design_.** Proceedings of the AAAI Symposium Series 3(1), pp. 595–597, published **2024-05-20**. DOI: 10.1609/aaaiss.v3i1.31290. https://ojs.aaai.org/index.php/AAAI-SS/article/view/31290

5. **[R5] Zhang et al. _A Multimodal Foundation Agent for Financial Trading: Tool-Augmented, Diversified, and Generalist_ (FinAgent).** arXiv:2402.18485, submitted **2024-02-28**. Preprint. https://arxiv.org/abs/2402.18485

6. **[R6] Halawi, Danny; Zhang, Fred; Chen, Yueh-Han; Steinhardt, Jacob. _Approaching Human-Level Forecasting with Language Models_.** arXiv:2402.18563, submitted **2024-02-28**. https://arxiv.org/abs/2402.18563

7. **[R7] Karger et al. _ForecastBench: A Dynamic Benchmark of AI Forecasting Capabilities_.** ICLR **2025**. https://proceedings.iclr.cc/paper_files/paper/2025/hash/ea74e45a229dac70b5b63b28d8934db6-Abstract-Conference.html

8. **[R8] Nel, Lukas. _Do Large Language Models Know What They Don't Know? KalshiBench: A New Benchmark for Evaluating Epistemic Calibration via Prediction Markets_.** arXiv:2512.16030, submitted **2025-12-17**. Preprint. https://arxiv.org/abs/2512.16030

9. **[R9] Cheng, Pu; Liu, Juncheng; Long, Yunshen. _PolyBench: Benchmarking LLM Forecasting and Trading Capabilities on Live Prediction Market Data_.** arXiv:2604.14199, submitted **2026-04-03**. Preprint. https://arxiv.org/abs/2604.14199

10. **[R10] Xiao et al. _TradingAgents: Multi-Agents LLM Financial Trading Framework_.** arXiv:2412.20138, submitted **2024-12-28**. Preprint. https://arxiv.org/abs/2412.20138

11. **[R11] Barot, Rajat M.; Borkhatariya, Arjun S. _PolySwarm: A Multi-Agent Large Language Model Framework for Prediction Market Trading and Latency Arbitrage_.** arXiv:2604.03888, submitted **2026-04-04**. Preprint. https://arxiv.org/abs/2604.03888

12. **[R12] Fan, Tianyu et al. _AI-Trader: Benchmarking Autonomous Agents in Real-Time Financial Markets_.** arXiv:2512.10971, submitted **2025-12-01**. Preprint. https://arxiv.org/abs/2512.10971

13. **[R13] Arian, Hamid; Norouzi Mobarekeh, Daniel; Seco, Luis. _Backtest overfitting in the machine learning era: A comparison of out-of-sample testing methods in a synthetic controlled environment_.** Knowledge-Based Systems, Volume 305, Article 112477, **2024-12-03**. https://doi.org/10.1016/j.knosys.2024.112477

14. **[R14] Bailey, David H.; López de Prado, Marcos. _The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality_.** Journal of Portfolio Management 40(5), 94–107, **2014**. https://ssrn.com/abstract=2460551

15. **[R15] López de Prado, Marcos; Fabozzi, Frank. _The False Discovery Rate in Finance: Identification Failure and Search-Adjusted Estimation_.** Written **2026-03-21**, SSRN posted 2026-03-24, revised **2026-09-05**. Working paper. https://ssrn.com/abstract=6450418

16. **[R16] Howard, Steven R. et al. _Time-uniform, nonparametric, nonasymptotic confidence sequences_.** arXiv:1810.08240; later published in Annals of Statistics (2021). https://arxiv.org/abs/1810.08240

17. **[R17] Chen, Yanxu et al. _StockBench: Can LLM Agents Trade Stocks Profitably In Real-world Markets?_** arXiv:2510.02209, submitted **2025-10-02**, revised **2026-03-02**. Preprint. https://arxiv.org/abs/2510.02209

18. **[R18] Polymarket Help Center. _Trading Fees_.** dated **2026-07-10**. https://help.polymarket.com/en/articles/13364478-trading-fees

19. **[R19] Polymarket Help Center. _Maker Rebates Program_.** dated **2026-07-21**. https://help.polymarket.com/en/articles/13364471-maker-rebates-program

20. **[R20] Polymarket Help Center. _Limit Orders_.** dated **2026-04-20**. Documents partial fills and sports order-delay behavior. https://help.polymarket.com/en/articles/13364444-limit-orders

21. **[R21] Polymarket Help Center. _Does Polymarket have trading limits?_** dated **2026-01-11**. Notes that desired size can affect price/fill and points users to order-book depth. https://help.polymarket.com/en/articles/13364481-does-polymarket-have-trading-limits

22. **[R22] Polymarket Help Center. _Liquidity Rewards_.** dated **2026-06-15**. https://help.polymarket.com/en/articles/13364466-liquidity-rewards

23. **[R23] AL-Aldaffaie, Ghusoon Hadi et al. _A survey on LLM-enhanced reinforcement learning in financial markets_.** Discover Artificial Intelligence 6, article 956, published **2026-08-28**. https://link.springer.com/article/10.1007/s44163-026-02018-0

24. **[R24] Qian et al. _When Agents Trade: Live Multi-Market Trading Benchmark for LLM Agents_.** arXiv:2510.11695, submitted **2025-10-13**. Preprint. https://arxiv.org/abs/2510.11695

25. **[R25] Zhu et al. _From Knowing to Doing: A Memory-Controlled Benchmark for LLM Trading Agents on Stock Markets_.** arXiv:2605.28359, submitted **2026-05-27**. Preprint. https://arxiv.org/abs/2605.28359

---

### Reference-link shortcuts used above

[R1]: https://arxiv.org/abs/2609.17632
[R2]: https://arxiv.org/abs/2402.03755
[R3]: https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/
[R4]: https://ojs.aaai.org/index.php/AAAI-SS/article/view/31290
[R5]: https://arxiv.org/abs/2402.18485
[R6]: https://arxiv.org/abs/2402.18563
[R7]: https://proceedings.iclr.cc/paper_files/paper/2025/hash/ea74e45a229dac70b5b63b28d8934db6-Abstract-Conference.html
[R8]: https://arxiv.org/abs/2512.16030
[R9]: https://arxiv.org/abs/2604.14199
[R10]: https://arxiv.org/abs/2412.20138
[R11]: https://arxiv.org/abs/2604.03888
[R12]: https://arxiv.org/abs/2512.10971
[R13]: https://doi.org/10.1016/j.knosys.2024.112477
[R14]: https://ssrn.com/abstract=2460551
[R15]: https://ssrn.com/abstract=6450418
[R16]: https://arxiv.org/abs/1810.08240
[R17]: https://arxiv.org/abs/2510.02209
[R18]: https://help.polymarket.com/en/articles/13364478-trading-fees
[R19]: https://help.polymarket.com/en/articles/13364471-maker-rebates-program
[R20]: https://help.polymarket.com/en/articles/13364444-limit-orders
[R21]: https://help.polymarket.com/en/articles/13364481-does-polymarket-have-trading-limits
[R22]: https://help.polymarket.com/en/articles/13364466-liquidity-rewards
[R23]: https://link.springer.com/article/10.1007/s44163-026-02018-0
[R24]: https://arxiv.org/abs/2510.11695
[R25]: https://arxiv.org/abs/2605.28359
