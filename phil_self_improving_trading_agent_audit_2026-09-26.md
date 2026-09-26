# Phil Self-Improving Trading Agent: Technical Audit, Research Review, and Profitability Improvement Plan

**Research date:** 2026-09-26  
**Repository supplied by user:** `phil-main.zip`  
**Repository data window observed:** paper ledger 2026-07-30 to 2026-09-25; forecast ledger 2026-08-09 to 2026-09-26  
**Uploaded ZIP SHA-256:** `26dc92123d4ca62cf8e4a3bcf6334720080bbb473e7c3cce20cbadec9116bc49`  
**Important limitation:** the ZIP does not contain `.git` metadata, so I could not independently recover the repository's HEAD commit. Individual journal rows do contain `strategy_rev` values, and the source itself records dated policy revisions.

> **Bottom line:** Phil is a thoughtful experimental scaffold for *self-improving forecasting and trading*, but the supplied evidence does **not yet demonstrate durable profitable alpha**. Its best architectural idea is the separation of stake-free forecast scoring from trading P&L. Its biggest current weakness is that the policy being optimized in replay is not the same policy the live paper loop is instructed to execute. The next largest issues are data-snooping in policy selection, incomplete point-in-time evaluation, portfolio/correlation-blind replay, and a cost model that omits the fee regime Polymarket introduced in July 2026. The most plausible path to profitability is therefore not “make the LLM more aggressive”; it is: **make the experiment harder to fool, shrink forecasts toward the market, specialize research where residual skill is actually measurable, add mechanistic cross-market signals, and make execution fee/depth/latency-aware.**

This report analyzes the supplied system as software and as an experimental design. It is not investment, legal, or gambling advice. Prediction-market access and treatment vary by jurisdiction; any real-money deployment should be independently checked for legal, operational, and financial risk.

---

## 1. Executive findings

### 1.1 What Phil actually is

Phil is **not a standard reinforcement-learning trader**. There is no policy network receiving gradients from reward. It is closer to a combination of:

- a **Reflexion-style language agent** that learns through retrospectives and persistent textual memory;
- an **evolutionary/program-search system** in which the LLM edits its own playbook, risk rules, sensing code, prompts, and tools;
- a **forecasting benchmark** that records stake-free probabilities and later scores them against the market;
- a **paper broker** with a protected engine and a small real-money twin path;
- a **closed-loop research process** in which settled outcomes alter future strategy text.

The operator deliberately separates an agent-editable `strategy/` layer from a protected `core/` and `config/` layer. `loop.sh` also reverts protected edits after an agent run. This is a strong safety and scientific-design choice. See `README.md:20-83`, `CYCLE.md:6-36`, and `loop.sh:193-201`.

### 1.2 The strongest design choice

The best part of the architecture is the **stake-free forecast ledger**. Every researched market for which the agent reaches a concrete probability can be recorded even when no bet is taken. `core/forecast.py` snapshots the book and market midpoint at record time, and `core/score.py` evaluates forecasting skill separately from realized trading results. This matters because P&L mixes together prediction accuracy, side selection, timing, price, sizing, luck, and risk.

That separation is consistent with current forecasting research. ForecastBench uses future-only questions to prevent leakage, and Foresight Arena explicitly argues that P&L is not a clean measure of predictive skill because it mixes forecasting with timing, sizing, and risk. [E01] [E05]

### 1.3 The empirical picture is much weaker than the replay headline

I reran the supplied evaluators rather than relying on prose in the journal.

| Metric | Recomputed result | Interpretation |
|---|---:|---|
| Settled actual paper bets | 47 | Very small financial sample |
| Actual paper P&L | **-$8.54** | Slightly negative |
| Actual paper ROI | **-3.6%** | Negative |
| Actual paper bet Brier delta | **+0.0872** | Agent estimates on bet sample were much worse than the paper-entry market baseline |
| Expected wins from own estimates | 30.28 | Agent was strongly overconfident relative to 19 actual wins |
| Luck-adjusted win z | **-3.98** | Severe miscalibration on the actual-bet subset |
| Settled stake-free forecasts | 875 | Better sample for forecast skill |
| Forecast Brier delta vs contemporaneous MID | **+0.0082** | Agent trails market slightly overall; reported z +0.43 is not compelling evidence of a difference |
| Current `policy.py`, 5-fold replay | +$111.61, cw_return +0.1136 | Attractive, **but not selection-OOS** |
| Current `policy.py`, 10-fold replay | +$142.30, cw_return +0.1765 | Same caveat |
| True forward test after frozen 2026-09-02 cutoff | +$20.62 raw P&L; **cw_return -0.0975** | Fails the repository's own pre-registered robustness criterion |
| Cheap screener, 29,584 scored rows | Brier delta +0.0033; excess directional information ~0 | Screener does not add useful directional probability information beyond market mids |

The central fact is in `strategy/policy.py` itself: lines 42-45 explicitly state that **every threshold was selected with all 420 settled rows visible**, and that the walk-forward split therefore holds nothing out from *rule selection*. That means the positive replay is a hypothesis-generating backtest, not clean evidence of alpha.

The repository did the right thing by pre-registering a later forward test. That test now has enough bets to score and it says **FAIL**: 58 policy bets over 441 usable post-cutoff rows, raw P&L +$20.62 but confidence-weighted return `-0.0975`. See `.github/scripts/forward_test.py` and the recomputed `core/replay.py --after 2026-09-02T00:14:36Z` output.

### 1.4 The most important architectural bug: “shadow policy”

There are currently **two materially different decision policies**:

1. `strategy/policy.py`, the object scored by `core/replay.py`, uses both YES and NO candidates, edge 2-7¢, price 10-90¢, a 20-45¢ dead zone, max spread 3¢, and flat $5.
2. The live cycle procedure (`CYCLE.md:298-306`) tells the agent to place trades when edge meets `strategy/risk.json`. That file currently says base minimum edge **4¢**, book-devig edge **7¢**, max spread **6¢**, wide-book edge **30¢**, and includes event/category rules not represented in `policy.py`.

A repository-wide search shows `strategy/policy.py` is referenced by the replay and forward-test machinery, not by the live paper broker decision path. The protected `core/ledger.py` accepts `--est-prob`, `--stake`, category, and edge-class; it does **not** call `policy.py` or enforce `risk.json` strategy thresholds.

Therefore, the system is currently capable of “improving” a policy in replay that is **not the policy actually producing the live paper bets**. This undermines causal learning from strategy changes: the thing being optimized and the thing generating outcomes can diverge.

### 1.5 The profitability thesis I would pursue

Phil should become a **market-relative, uncertainty-aware, cost-aware hybrid system**:

1. Treat the market midpoint/order book as the prior.
2. Ask specialist research components to estimate only the **residual information not already in price**.
3. Calibrate that residual with heavy hierarchical shrinkage toward zero.
4. Trade only when the **lower-confidence-bound net edge** remains positive after taker fee, spread, expected slippage, latency, and model uncertainty.
5. Prefer deterministic/mechanistic signals where possible: cross-market logical constraints, bookmaker no-vig relationships, official-data release models, options/barrier models, weather ensembles, and count-process models.
6. Use LLMs mainly for retrieval, semantic interpretation, resolution-rule parsing, source verification, and rejecting spurious statistical signals—not as the sole numerical probability engine.
7. Promote strategy changes only through a sealed champion/challenger protocol with event-grouped, point-in-time evaluation.

This is closer to what the strongest contemporary work suggests: retrieval plus aggregation for forecasting [E02]; realistic, timestamp-locked order books for prediction-market evaluation [E03]; LLM semantic filters on top of statistical discovery [E14]; cost-aware temporally gated trading benchmarks [E07]; and self-evolving policies with disjoint held-out tests [E06].

---

## 2. Scope and methodology

### 2.1 What I inspected

I inspected the supplied repository directly, including:

- `README.md`, `CYCLE.md`, `loop.sh`, `REAL.md`, `CLAUDE.md`;
- protected execution/scoring code under `core/`;
- `config/protected.json`;
- `strategy/policy.py`, `strategy/risk.json`, `strategy/playbook.md`, `strategy/discovery.py`, `strategy/schedule.json`, screener config and tools;
- `journal/forecasts.jsonl`, `journal/ledger.jsonl`, `journal/real-ledger.jsonl`, funnel/screener data, operator notes, proposals, and retrospectives;
- the forward-test workflow and script.

I also reran the system's own scoring, replay, screening, counterfactual, and status commands against the supplied journal.

### 2.2 Commands recomputed

```bash
python3 core/ledger.py status
python3 core/score.py --skip-mtm
python3 core/replay.py --folds 5
python3 core/replay.py --folds 10
python3 core/replay.py --after 2026-09-02T00:14:36Z
python3 .github/scripts/forward_test.py --force
python3 core/screen_replay.py score
python3 core/screen_value.py fit
python3 core/counterfactual.py ledger --skip-reason outside-view-veto --folds 5
```

### 2.3 External research methodology

I prioritized, in roughly this order:

1. peer-reviewed forecasting/calibration/backtest literature;
2. official Polymarket documentation for current execution economics;
3. current 2025-2026 live or contamination-resistant agent benchmarks;
4. recent preprints/working papers on self-evolving trading agents and program search.

Recent preprints are useful design evidence, but their reported profits should not be treated as established facts until independently replicated. I mark evidence maturity in the research comparison section.

---

## 3. How the agent works, exactly

### 3.1 Trust boundary

The repository implements a deliberate **two-layer constitution**.

**Protected operator layer**

- `core/`: ledger, resolution, scoring, scanning, replay, CI, real execution, etc.
- `config/protected.json`: bankroll and hard risk ceilings.
- top-level cycle/operator files and `.github/`.

**Agent-editable layer**

- `strategy/playbook.md`: accumulated rules and hypotheses;
- `strategy/risk.json`: agent-level sizing/edge thresholds;
- `strategy/discovery.py`: market sensing;
- `strategy/schedule.json`: pacing;
- `strategy/tools/`: quantitative/reconciliation helpers;
- screener prompts/filters/strata/value files.

`CYCLE.md:8-21` explicitly prohibits editing protected code and requires every strategy edit to cite settled evidence. `loop.sh:193-201` provides a second enforcement layer by reverting protected edits after an agent session and warning if protected paths appear in recent commits.

That is a good pattern: **self-improvement occurs inside a bounded search space**, while the judge and bankroll constraints are meant to remain immutable.

### 3.2 Runtime control loop

At a high level:

```text
             ┌────────────────────────────┐
             │  Protected market + judge  │
             │ scan / books / settlement  │
             │ ledger / score / replay    │
             └─────────────┬──────────────┘
                           │ observations
                           ▼
              ┌─────────────────────────┐
              │ Claude trading agent    │
              │ search / reason / tools │
              └────────────┬────────────┘
                           │
             ┌─────────────┼──────────────────┐
             │             │                  │
             ▼             ▼                  ▼
      stake-free       paper trade       strategy edits
      forecast         at live ask       playbook/risk/
      ledger           (if chosen)       sensing/tools
             │             │                  │
             └──────┬──────┘                  │
                    ▼                         │
              settlement/outcome              │
                    │                         │
                    ▼                         │
             score + retrospective ───────────┘
```

This is a **closed feedback loop**: observations lead to decisions; decisions and non-decisions are recorded; future settlements generate feedback; feedback updates text/code used in subsequent decisions.

### 3.3 Tick types and pacing

`CYCLE.md` defines three modes:

- **FULL:** full market scan, research, forecasting, possible betting, logging, commits;
- **LIGHT:** settlement/open-position monitoring with minimal work;
- **TRIGGERED:** watch-driven narrow research around a specific event/market trigger.

There are collision and lease guards to reduce duplicate concurrent runs. `strategy/schedule.json` lets the agent pace full cycles. This is unusually operationally mature for an experimental agent because it recognizes that concurrent autonomous runs can otherwise double-enter markets or mutate shared state inconsistently.

### 3.4 Market discovery and screening

A full cycle scans a short-horizon Polymarket universe using protected scanning plus agent-editable `strategy/discovery.py`. A cheap LLM screening tier ranks a large candidate pool so the more expensive agent can focus research.

The screener produces probability-like outputs and divergence from market price, but its real intended economic role is **triage**: find markets worth spending research budget on.

The supplied evidence says the current screener is not actually informative as a forecaster. Across 29,584 scored rows in 1,945 batches, its Brier score was 0.3483 versus 0.3450 for the supplied mids (`delta +0.0033`). More importantly, the screener's “excess” component after accounting for the mechanical penalty from disagreeing with the market was approximately zero (`exc_z +0.1`). A fitted blend placed essentially 100% weight on the market (`w_opt 1.006` overall; `0.982` on high-disagreement rows), and event-held-out blend performance did not beat mids.

That means the screener should **not be interpreted as a source of probability alpha**. It may still be useful as a semantic classifier or value-of-information router.

### 3.5 Research

For selected candidates, the agent searches the web, invokes specialist local tools, may compare bookmaker lines, evaluates sibling markets, and can request a second opinion from Olas/Mech when that tool path is available.

The playbook has grown into a very large episodic knowledge base—about 6,700 lines by the latest deep retro. It contains edge classes, source standards, failure examples, category bars, pre-registrations, counterfactual findings, and operational rules.

This is conceptually similar to **Reflexion**: outcomes are converted into natural-language lessons that influence later behavior rather than changing model weights. [E15]

### 3.6 Stake-free forecasting

For **every researched candidate with a concrete probability**, including skips, `CYCLE.md:285-297` tells the agent to record a forecast before betting.

`core/forecast.py` then:

- refetches the market;
- resolves the exact outcome token;
- snapshots best bid and ask;
- computes the contemporaneous midpoint;
- stores the agent's `est_prob` and category/skip metadata;
- rejects an estimate more than 40 percentage points from midpoint unless explicitly confirmed;
- allows an open forecast to be superseded only after a material 5-point belief change or skip-reason change.

This produces a much more useful learning dataset than the trade ledger because it avoids selection solely on what the agent happened to bet.

### 3.7 Paper execution

`core/ledger.py` is the only protected writer for paper positions.

It:

- checks protected max open positions and stake cap;
- checks simulated cash;
- prevents duplicate open positions on the same market/outcome;
- refetches the live market and order book;
- buys at the **current best ask**, i.e. models a taker crossing the spread;
- rejects entries outside protected price bounds;
- records shares as `stake / ask`.

This is materially more honest than filling at the midpoint.

However, it currently **does not**:

- enforce `strategy/policy.py`;
- enforce `strategy/risk.json` thresholds itself;
- re-check whether the agent's edge still exceeds the strategy threshold at the new ask;
- model taker fees;
- model depth/VWAP for a stake larger than top-of-book size;
- model latency between forecast snapshot and order submission;
- choose maker versus taker execution.

This is one of the most important places to improve.

### 3.8 Settlement and retrospectives

Settled trades and forecasts are scored. The agent writes retrospectives and daily deep retros, and uses those to edit its playbook/risk/sensing/tools. Examples in the current playbook show specific losing trades being converted into general rules about source finality, state-media corroboration, sibling consistency, provisional data, and category-specific research methods.

This is the system's actual **self-improvement mechanism**: not gradient descent, but **experience → textual diagnosis → policy/tool mutation → future behavior**.

### 3.9 Strategy-policy replay

`core/replay.py` provides a second self-improvement channel. It freezes the forecast beliefs and asks: *given the beliefs the agent already produced, could a different betting rule have converted them into better trades?*

`strategy/policy.py` implements that decision rule. This decomposition is clever because it separates:

- **forecasting quality** (`est_prob`), from
- **decision quality** (which side/price/edge band to trade), from
- **sizing**.

But the current replay has scientific limitations discussed below.

### 3.10 Real-money twin

`core/real.py` mirrors eligible paper bets into tiny real positions through a local signing service. The current protected config allows only the `cross-market` edge class, with max $1 per trade, 10 open positions, and $5 daily stake.

The supplied `journal/real-ledger.jsonl` contains 56 rows, all of type `settle`; I did not find an executed real trade record in the supplied snapshot. So the profitability analysis below is essentially paper/forecast analysis, not evidence of live execution profit.

The real path itself uses a generic `trade.py buy --token-id ... --usd ...` action after topping up. It does not appear to decide maker vs taker or reprice the trade against the latest edge immediately before submission.

---

## 4. What “self-improving” means here—and what it does not

### 4.1 It is semantic policy iteration, not RL

Phil's state includes persistent code and text. Its “reward” arrives as settled P&L, Brier score, calibration, counterfactual results, and retrospective diagnoses. The LLM then modifies the instructions/tools that generate future actions.

A useful formalization is:

```text
θ_t = {playbook text, risk settings, discovery code, tools, prompts, schedule}
D_t = accumulated market/forecast/trade/outcome record
J(θ, D) = forecast skill + trading utility + risk/discipline diagnostics

Agent proposes:   θ' = M(θ_t, diagnostics(D_t))
Judge evaluates:  J(θ', held-out D)
Then future cycles use θ' if retained.
```

The critical distinction from RL is that `M` is an LLM doing natural-language/code search, not a gradient optimizer.

### 4.2 The closest research analogues

Phil resembles several recent lines of work:

- **Reflexion:** verbal reflection plus episodic memory rather than weight updates. [E15]
- **GEPA:** prompt/policy mutation driven by trajectory reflection and candidate selection. [E16]
- **Darwin Gödel Machine / AlphaEvolve:** propose code changes, evaluate them empirically, retain strong variants, maintain search diversity/archive. [E17] [E18]
- **EvolveTrade:** explicitly treats a tool-using trader's system prompt as a text policy that a policy agent revises using decision traces and realized portfolio feedback. This is extremely close conceptually to Phil. [E06]
- **ProFiT / MadEvolve / Continuous Program Search:** LLM/evolutionary search over trading programs, using out-of-sample evaluation or p-hacking diagnostics. [E19] [E20] [E21]
- **AutoScientist-Quant:** self-evolving quantitative-research search process with an explicit concern that loop feedback can leak the test window; keeps feedback and held-out windows disjoint. [E08]

The biggest difference is that Phil already has a comparatively strong protected runtime boundary and a large real journal. Its largest deficit is not lack of self-reflection; it is that **the judge is not yet strict enough to guarantee that apparent improvements are genuine and executable**.

---

## 5. Empirical audit of the supplied snapshot

## 5.1 Actual paper trades

`core/score.py --skip-mtm` reports:

```text
settled=47
win_rate=0.404
pnl=-$8.54
roi=-0.036
brier: agent=0.2964 market=0.2091 delta=+0.0872
expected wins from own probabilities=30.28
actual wins=19
z=-3.98
```

The most important line is not the small negative P&L. With only 47 trades, P&L is noisy. The more alarming signal is **overconfidence**: the probabilities attached to the chosen bets implied about 30 wins; only 19 occurred.

The bet sample's Brier comparison is a different construction from the stake-free forecast-mid benchmark, so the two Brier deltas should not be numerically compared as though they were the same experiment. The repo itself is aware of this. Still, both tell a consistent qualitative story: the agent is not currently showing clean probability superiority over price.

### 5.2 Stake-free forecasts

There are 875 settled, non-superseded stake-free forecasts in the scoring output, plus 129 open.

Overall:

- agent Brier minus market-mid Brier = **+0.0082**;
- the reported z statistic is **+0.43**;
- negative is good, so the point estimate is slightly worse than the market, but the aggregate difference is not strong evidence of a stable gap.

This is the correct population to look at when asking, “does the research process itself add probability information?” The answer, so far, is: **not in aggregate**.

Some exploratory category slices are better than price and some are much worse. For example, in the supplied sample:

- `mlb-moneyline`: -0.0499 over 15 forecasts;
- `commodities-touch`: -0.0378 over 14;
- `product-release`: -0.0921 over 4;
- `soccer`: -0.0052 over 99;
- `ai-model-release`: +0.0838 over 35;
- `social-media-postcount`: +0.0489 over 37;
- `weather`: +0.0495 over 34.

These are **hypothesis-generating slices**, not standalone evidence. Multiple categories are being inspected, sample sizes are often small, and event dependence can reduce effective sample size. The right next step is hierarchical shrinkage and sealed validation, not hardcoding the best retrospective categories.

### 5.3 Calibration shape

The overall forecast calibration table has several visible distortions. For example:

- estimates in 10-20% occurred about 25% of the time;
- estimates in 20-30% occurred about 17%;
- estimates in 40-50% occurred about 38%;
- estimates in 50-60% occurred about 60%;
- estimates in 90-100% occurred about 93%.

The system is not uniformly miscalibrated; it has **local calibration errors**. This argues for a calibrated/shrunk market-relative model rather than a single global “LLM confidence penalty.”

### 5.4 Simple edge sweeps do not validate raw YES-side edge

The supplied scorer examines counterfactual trades based only on claimed edge. On the YES side, every tested positive-edge threshold from 2¢ through 15¢ produced negative raw ROI in this historical sample. That is an important warning: **larger disagreement with the market is not currently synonymous with larger alpha**.

The complementary NO-side sweep shows positive raw ROI across several thresholds, but its Brier deltas are worse than the market. It would be a mistake to conclude “always buy NO.” The pattern can arise from sample luck, event composition, price asymmetry, side mapping, or correlated outcomes. It should be subjected to an event-grouped sealed test before any policy change.

### 5.5 The in-sample blend says the market should dominate

A simple full-sample blend:

```text
q = w * market_mid + (1-w) * agent_probability
```

fits at approximately `w = 0.791` overall and `w = 0.807` on disagreement rows. In other words, the in-sample optimum gives only about **20% weight to the agent**.

Even that small improvement is in-sample and must be tested forward. But it is directionally important: the current data says **the market should be the prior and the agent should be a modest residual adjustment**, not the other way around.

### 5.6 `strategy/policy.py` replay looks good—but is explicitly selected in-sample

Current policy v3 does:

- both YES and NO;
- min edge 2¢;
- max edge 7¢;
- fill 10-90¢;
- no token priced 20-45¢;
- spread ≤3¢;
- flat $5.

Current full-history replays:

**5 folds**

- 688 held-out rows after the initial train chunk;
- 71 bets;
- +$111.61;
- ROI +31.4%;
- cw_return +0.1136;
- selected-bet Brier delta -0.0060.

**10 folds**

- 774 scored rows;
- 77 bets;
- +$142.30;
- ROI +37.0%;
- cw_return +0.1765;
- Brier delta -0.0075.

These are interesting but **not honest model-selection OOS** because `policy.py:42-45` says the thresholds were chosen after reading all 420 then-settled rows. This is a textbook multiple-testing/backtest-overfitting problem: the winning rule cannot be evaluated as if it had been pre-specified. The Deflated Sharpe Ratio and Probability of Backtest Overfitting literature exists specifically because strategy search inflates apparent historical performance. [E22] [E23]

### 5.7 The true forward test is the more important result

The repo pre-registered 2026-09-02T00:14:36Z as the cutoff after policy v3 selection. Recomputed today:

```text
441 usable rows settled after cutoff
58 policy bets
raw P&L +20.62
Brier delta -0.0019
cw_return -0.0975
```

The included forward-test script declares **FAIL** because the pre-registered requirement was `cw_return > 0` and at least 15 forward bets.

This is exactly the kind of result that should dominate decision-making. It does not prove the policy has no alpha; the forward sample is still finite and raw P&L is positive. But it does mean the current evidence is insufficient to claim robust positive trading performance.

### 5.8 Recent replay folds are not uniformly healthy

The 5-fold current replay has negative cw_return in both of its most recent folds:

- 2026-09-05..16: -0.345;
- 2026-09-16..26: -0.035.

The 10-fold run similarly has multiple negative folds. This can be noise, regime shift, or the original selection edge decaying. Either way it strengthens the case for a champion/challenger architecture and drift monitoring rather than silently mutating one live strategy.

### 5.9 Screener: lots of compute, almost no incremental probability information

The screener dataset is large:

- 73,800 rows;
- 19,742 markets;
- 29,584 scored rows;
- 5,852 event clusters among scored market groups.

Yet its all-row Brier delta is `+0.0033`, and its “excess” directional component is approximately zero. Fixed blends with the screener worsen the midpoint on high-disagreement rows. The event-held-out optimum weight is essentially all market.

The lesson is **not** “delete screening.” The lesson is to stop asking the cheap screener to be a miniature forecaster. Reframe it as a **research-allocation model**: predict whether expensive research is likely to produce a validated net edge.

### 5.10 Counterfactual veto analysis is informative but easy to overfit

The outside-view-veto counterfactual shows +$87.41 raw P&L over 165 fillable hypothetical $5 trades, while its forecast Brier delta is +0.0312 (worse than market). Certain tiny subgroups look extremely profitable.

This is precisely the sort of table from which a self-improver can accidentally data-mine exceptions. The report should be used to propose a hypothesis, then freeze the hypothesis and test it prospectively. The repo has already begun doing pre-registered carve-outs; that discipline should become mechanical and universal.

### 5.11 Operational stale position

`core/ledger.py status` reports four open paper positions. One has an `end_date` of 2026-09-13 even though this audit is 2026-09-26.

That does not necessarily mean the underlying market should already be resolvable—prediction-market resolution can be delayed—but it does mean the system needs an explicit **stale-resolution/reconciliation state** rather than simply counting it as an ordinary open position indefinitely. Otherwise stale rows can distort cash, open-position caps, and exposure accounting.

---

## 6. Structural problems that currently limit trustworthy profitability

### 6.1 P0: evaluated policy ≠ executed policy

This is the most important issue.

**Replay:** `strategy/policy.py`  
**Live cycle:** `strategy/risk.json` plus free-form playbook judgment  
**Broker:** accepts any values that pass only protected hard caps

A self-improving system requires a closed identity:

```text
policy evaluated = policy promoted = policy executed = policy whose outcomes are learned from
```

Phil currently violates that identity.

**Consequence:** a replay improvement can be real but never affect live trades; a live loss can be caused by a playbook/risk rule that replay never tested; and attribution by `strategy_rev` cannot fully reconstruct the actual machine decision function.

### 6.2 P0: policy selection is exposed to the same data it is scored on

`strategy/policy.py` candidly documents this. The agent/operator tried many thresholds and variants on the same settled history and kept a good one.

A policy search with `N` attempts has more opportunities to fit noise than a single pre-specified strategy. Classic work on backtest overfitting and the Deflated Sharpe Ratio warns that the “winner of the search” requires a multiple-testing correction or untouched forward evidence. [E22] [E23]

The recent finance literature continues to find this a major problem, and AutoScientist-Quant specifically identifies test-window feedback/leakage as a failure mode of self-evolving quantitative agents. [E08]

### 6.3 P0: current walk-forward fitting is not fully point-in-time safe for learned policies

`core/replay.py` sorts rows by **record time**, partitions them into chunks, and for fold `k` passes all prior chunks to optional `fit()` *with their outcomes*. It does not check whether each prior-row outcome had actually settled by the time a test-row decision was recorded.

For the current static policy, this does not create active leakage because there is no `fit()`. But the policy interface explicitly supports `fit(history)`, and the agent has already experimented with calibration shrinkage. A future adaptive policy could therefore learn from outcomes that were not known at the historical decision time.

The correct rule is:

```text
At decision timestamp t, training data may contain only observations whose labels were known by t.
```

That means `settled_ts <= decision_ts`, not merely `record_ts in an earlier fold`.

### 6.4 P0: replay is row-independent, not portfolio-stateful

`score_rows()` calls the policy independently on every forecast row. Replay does not evolve:

- cash;
- max concurrent positions;
- max new positions per cycle;
- event-level stake caps;
- category exposure;
- sibling/mutually-exclusive exposure;
- overlapping holding periods.

This can score a set of trades that could not all have been entered by the actual portfolio.

A trustworthy backtest needs to process decisions chronologically and maintain exactly the same state machine as live execution.

### 6.5 P0: uncertainty is calculated per bet, not per independent event

`cw_return` uses a stake-weighted standard error over individual bet returns. But prediction markets often contain many sibling contracts for one underlying event. Those are correlated observations.

The screener code already recognizes this and performs event clustering. The trading replay should do the same. Otherwise a policy that makes several related bets can look more statistically certain than it really is.

The unit of resampling/inference should usually be the **independent event or event-time cluster**, not the individual binary row.

### 6.6 P0: post-July-2026 fees are missing

Polymarket's current official documentation states that certain market categories charge **taker fees at match time**, with makers charged zero. The formula is: [E24]

```text
fee = shares × feeRate × price × (1 - price)
```

Current documented taker fee rates range from 4% to 7% depending on category, while geopolitics is documented as fee-free. Fees apply only to fee-enabled markets deployed after activation; the market object exposes `feesEnabled`. [E24] [E25]

Phil's paper/replay economics currently contain no such deduction.

This is material because the current replay policy trades very small gross edges. At a 50¢ token price:

- 5% category rate → fee/share = `0.05 × 0.5 × 0.5 = $0.0125` = **1.25¢**;
- 4% category rate → **1.00¢** per share.

So a nominal 2¢ edge can lose **50-62.5% of its gross expected edge** to the taker fee alone, before spread, slippage, and latency.

I would **not** retroactively charge every historical row this fee because the supplied forecast ledger does not preserve a historical `feesEnabled` flag and fees apply only to eligible markets after activation. The correct fix is to record the fee state point-in-time going forward and only backfill historical fees where deployment/fee metadata can be proven.

### 6.7 P0: top-of-book fill is not enough when scaling

At $5 stakes the top-of-book approximation may often be close, but the repo is designed to improve and potentially scale. Polymarket's own documentation notes that size can cause price impact or fail to fill if book depth is insufficient. [E28]

Replay should store and simulate a depth ladder and compute VWAP, not merely best ask, once stakes become meaningful relative to displayed liquidity.

### 6.8 P0: no decision-to-fill edge revalidation

The stake-free forecast records one book snapshot. Later, `ledger.py place` refetches the live ask and fills there. The recorded probability remains fixed, but no protected strategy function asks:

```text
Does q - current_ask still clear the required net edge right now?
```

A 3¢ move while the agent is researching or issuing commands can eliminate a 2¢ replay edge completely.

This is especially dangerous in exactly the “information race” situations Phil seeks, because those are the situations in which prices move fastest.

### 6.9 P1: raw probabilities should be market-relative and shrunk

The overall forecast record does not show aggregate superiority to the market. Therefore the economically rational starting point is not `p = agent`, but something like:

```text
logit(p_final) = logit(p_market) + λ_g × δ_agent
```

where `δ_agent` is the agent's estimated residual information and `λ_g` is a category/method-specific shrinkage coefficient learned only from settled point-in-time data. With weak evidence, `λ_g` should be near zero.

The in-sample blend already suggests about 80% market weight. The exact shrinkage must be selected without reusing the test outcomes.

### 6.10 P1: category rules are high-dimensional and vulnerable to narrative overfitting

The playbook has accumulated many category-specific lessons. Some are excellent mechanistic lessons; others can become a huge implicit parameter set.

A 6,700-line evolving playbook creates an **untracked hypothesis count**. The agent can subtly change many decisions without a machine-readable record of how many rules were tried and rejected.

This is where an evolutionary candidate registry becomes important: every policy mutation should be a first-class candidate with lineage, training data cutoff, validation result, and promotion status.

### 6.11 P1: weak taxonomy reduces learning quality

18 of the 47 settled paper bets are `unclassified` in edge class. The outside-view-veto counterfactual has 112 of 173 rows with no recognized subclass.

If the self-improvement loop is supposed to learn **which mechanisms work**, every decision needs canonical, machine-validated attribution at record time. Free-form prose is not enough.

### 6.12 P1: research/model cost is absent from economic P&L

The experiment scores market P&L, but a production autonomous trader has another cost stack:

```text
net economic profit
= trading P&L
- exchange/protocol fees
- spread/slippage
- infrastructure/model/search/tool costs
- operational failure costs
```

The current screener has processed tens of thousands of rows despite showing no incremental forecast information. Research ROI therefore needs to become an explicit optimization objective.

---

## 7. What current research says about similar systems

The following table emphasizes what is transferable to Phil rather than simply listing papers.

| Approach | Evidence maturity | Core idea | Closest Phil analogue | Main lesson for Phil |
|---|---|---|---|---|
| ForecastBench (ICLR 2025) [E01] | Peer-reviewed | Dynamic future-only forecast benchmark | Stake-free forecast ledger | Keep a continuously rolling, contamination-resistant forward score; do not treat retrospective replays as equivalent |
| Halawi et al., NeurIPS 2024 [E02] | Peer-reviewed | Retrieval + forecast generation + aggregation | Web research + own forecast + mech | Retrieval and aggregation can materially improve forecasting; architecture matters more than raw prompting |
| Reflexion, NeurIPS 2023 [E15] | Peer-reviewed | Verbal reflection + episodic memory | Retros + playbook | Phil already uses a valid learning paradigm; improve the evaluator rather than replacing reflection |
| LLM as a Risk Manager, ACL Industry 2026 [E14] | Peer-reviewed venue | Statistical discovery first, LLM semantic filter second | Sibling/cross-market analysis | Use LLM to reject spurious relationships and verify causal/semantic links, not to replace the quantitative signal |
| PolyBench 2026 [E03] | Preprint / benchmark | Timestamp-locked CLOB + news; realistic execution | Forecast + order-book ledger | Evaluate at exact point-in-time market state; strong confidence often fails to translate to positive returns |
| WC2026 Agents 2026 [E04] | Preprint / prospective live | Future-only sports forecasts vs bookmaker | Sports lane | Frontier LLM agents did not beat market Brier and were highly correlated; market baseline is hard to beat |
| Specialist multi-agent World Cup study 2026 [E29] | Preprint / prospective | Quant specialist + news specialist + critic/meta-agent | Mech/own/tool ensemble | Specialists can differ in value; extra critic/meta layers do not automatically add information |
| Foresight Arena 2026 [E05] | Working paper | Proper-score live prediction-market benchmark | Forecast ledger | Separate forecasting alpha from trading P&L and reason about statistical power |
| EvolveTrade 2026 [E06] | Preprint | System prompt as an evolving trading policy | Phil playbook/risk mutation | Very close analogue; policy evolution can work, but Phil needs stricter held-out promotion before trusting it |
| CLQT 2026 [E07] | Preprint | TimeGate + costs + strategy consistency + audit trail | Protected core/replay | Direct support for temporal gating, cost-aware evaluation, and measuring whether executed behavior matches declared strategy |
| AutoScientist-Quant 2026 [E08] | Preprint | Self-evolving quant search with disjoint feedback/test windows | Replay-driven strategy edits | Treat held-out data as sealed; loop feedback must never read the final test window |
| Agentic Trading survey 2026 [E09] | Survey/preprint | Audits 77 LLM trading studies | Whole architecture | Evaluation quality is the field's bottleneck: only 2/19 primary studies had extractable time-consistent splits; only 1/19 explicit transaction costs |
| KTD-Fin 2026 [E10] | Preprint | Leakage masking + return attribution | Forecast vs P&L split | Ask where P&L actually comes from; raw returns can reflect exposure/regime rather than transferable alpha |
| AI-Trader 2025 [E11] | Preprint/live benchmark | Autonomous live trading across markets | Full-loop live agent | General intelligence does not imply trading skill; risk control is central |
| Agent Market Arena 2025 [E12] | Preprint/live benchmark | Multiple agent architectures/backbones | Phil architecture choices | Agent/risk scaffolding can influence behavior more than backbone model choice |
| Production fleet study 2026 [E13] | Preprint + public artifacts | Hundreds/thousands of live agents | Operational layer | Operating controls can dominate strategy text; sizing and exit mechanics deserve direct engineering |
| GEPA 2025 [E16] | Preprint | Reflective prompt evolution + Pareto candidate set | Playbook evolution | Maintain multiple candidate prompts/policies and a Pareto frontier instead of one continuously overwritten policy |
| Darwin Gödel Machine 2025 [E17] | Preprint | Self-modifying code + empirical validation + archive | Editable strategy/tools | Open-ended improvement is safer/more productive with archive diversity and sandboxed evaluation |
| AlphaEvolve 2025 [E18] | Technical report/preprint | Evolutionary code search with automated evaluators | Strategy/tool mutation | Use multiple automated evaluators and preserve a population/archive of candidates |
| ProFiT 2025/26 [E19] | Working paper | LLM evolutionary trading-program search | `policy.py` search | Constrain strategy mutations to explicit program objects and evaluate them walk-forward |
| MadEvolve 2026 [E20] | Preprint | Evolution of features + execution strategy; p-hacking evaluation | Agent edits tools/rules | Jointly optimize signal and execution, but report p-hacking probability/search size |
| Continuous Program Search 2026 [E21] | Preprint | Behavior-local mutation in trading DSL | Policy mutation | Small, semantically localized mutations can be more sample-efficient and attributable than wholesale playbook rewrites |
| Preference Optimization Monoculture 2026 [E30] | Preprint | LLM forecaster errors highly correlated; cross-model diversity helps | Multiple mech/persona forecasts | Do not assume same-family “swarm” agents create independent evidence; measure error correlation |
| PolySwarm 2026 [E31] | Preprint | Multi-agent aggregation + market prior + fractional Kelly + cross-market signals | Potential future ensemble | Useful architecture ideas, but profitability claims need independent validation; diversity should be empirical, not persona-only |
| Bailey et al., PBO [E23] | Established finance methodology | Estimate probability a selected backtest is overfit | `policy.py` search | Track all candidate trials; a winner selected after many tries needs a multiple-testing-aware evaluation |
| Bailey & López de Prado, DSR [E22] | Peer-reviewed finance | Adjust Sharpe for selection bias and non-normality | Strategy selection score | Add search-aware significance, but do not use it as a substitute for untouched forward data |
| Arian et al. 2024 [E32] | Peer-reviewed | Synthetic comparison of financial CV methods | Replay design | In their controlled setting CPCV reduced overfit risk relative to walk-forward; use purging/embargo/event blocks as robustness diagnostics |
| Beta calibration 2017 [E33] | Peer-reviewed | Flexible probability calibration | Forecast calibration | Small datasets make nonparametric calibration easy to overfit; use identity-preserving/shrunk calibration and strict validation |
| Baker & McHale 2013 [E34] | Peer-reviewed | Kelly under parameter uncertainty | Future sizing | Plug-in Kelly oversizes uncertain edges; shrink bets when probability estimates are uncertain |

### 7.1 Synthesis: the common pattern

The strongest current work converges on five principles:

1. **Future-only or temporally gated evaluation.**
2. **Market/external baselines are extremely difficult to beat.**
3. **Agent architecture and control scaffolding matter as much as or more than the underlying LLM.**
4. **Transaction/execution costs change conclusions.**
5. **Self-improvement is credible only when the improvement process cannot repeatedly see the final test.**

Phil already has pieces of all five, but not yet in one airtight evaluator/executor.

---

## 8. A better profitability model for Phil

The key conceptual change is to stop treating “agent probability minus displayed market probability” as the primitive tradable edge.

### 8.1 Separate four quantities

For a YES token:

- `m`: market midpoint at research time;
- `q_raw`: agent's independent probability estimate;
- `q_cal`: calibrated/shrunk probability used for decisions;
- `a`: executable YES ask immediately before trade.

For a NO trade using the YES book:

- NO executable price is approximately `1 - bid_yes`;
- belief for NO is `1 - q_cal`.

Gross per-share edge is therefore:

```text
YES gross_edge = q_cal - ask_yes
NO  gross_edge = (1 - q_cal) - (1 - bid_yes) = bid_yes - q_cal
```

This is better than treating midpoint disagreement as executable edge.

### 8.2 Start from the market and model the residual

Instead of asking the LLM for an unconstrained absolute probability and trusting it directly, model:

```text
residual_raw = logit(q_raw) - logit(m)
logit(q_cal) = logit(m) + λ_group × calibrated(residual_raw)
```

Where `λ_group` is learned for a sufficiently broad mechanism/category group and heavily shrunk toward zero.

Benefits:

- the market prior automatically dominates when the agent has weak historical residual skill;
- extreme LLM disagreements are compressed;
- the model directly learns the quantity that matters: **incremental information beyond price**;
- category-specific skill can emerge gradually without hardcoding noisy slices.

A simpler first implementation is:

```text
q_cal = m + λ_group × (q_raw - m)
```

with clipping and `λ` estimated only from past settled events.

### 8.3 Make uncertainty explicit

A point probability is not enough. The trading rule should estimate uncertainty around the residual, for example by:

- event-cluster bootstrap;
- beta-binomial/hierarchical Bayesian residual model;
- calibrated ensemble dispersion from heterogeneous forecasters;
- model disagreement plus historical calibration error.

Then define:

```text
conservative_q_yes = lower credible/confidence bound for q_cal
```

for a YES buy, and the corresponding conservative bound for NO.

Trade only if the conservative edge survives all costs.

### 8.4 Subtract executable costs

For fee-enabled taker trades, use the live Polymarket fee parameters. [E24] [E25]

Approximate fee equivalent per share:

```text
fee_per_share = feeRate × execution_price × (1 - execution_price)
```

Then:

```text
net_edge
= gross_edge
- fee_per_share
- expected_slippage_per_share
- latency_buffer
- model_uncertainty_buffer
```

The correct threshold is therefore **dynamic**, not a universal 2¢ or 4¢.

### 8.5 Add maker/taker choice as a strategy dimension

Official documentation currently says makers pay zero fees and may earn maker rebates; qualifying limit orders may also earn liquidity rewards. [E24] [E25] [E26]

That does **not** mean “always make.” A maker order introduces:

- probability of no fill;
- queue position;
- adverse selection (you get filled precisely when the world moves against your quote);
- opportunity cost during fast repricing.

So the executor should compare two expected utilities:

```text
EU_taker = immediate fill value - taker fee - slippage
EU_maker = P(fill) × value_if_filled + expected rebate/reward - adverse_selection - miss_cost
```

Information-race trades may still justify taker execution because fill urgency is high. Slow structural relative-value trades may benefit from passive orders.

### 8.6 Only then size

Do not apply raw Kelly to the current probabilities. The actual paper bet sample is overconfident, and Baker & McHale show why plug-in Kelly with uncertain probability estimates can be too aggressive. [E34]

Once calibrated net edges are demonstrated forward, a binary-market full-Kelly fraction for a YES share at price `s` and belief `q` (before fees) is:

```text
f* = (q - s) / (1 - s)
```

A practical system should use something like:

```text
f = α × shrinkage(uncertainty) × max(0, f*_net)
```

with a small `α` (fractional Kelly), hard event risk caps, and portfolio correlation controls.

Until Phil demonstrates robust calibrated edge, **flat small stakes are safer than sophistication masquerading as precision**.

---

## 9. Highest-potential alpha sources to develop

### 9.1 Mechanistic cross-market consistency engine

This is probably the best strategic fit for Phil because:

- the repository already recognizes cross-market inconsistency as a structural edge class;
- real-money config currently allows only `cross-market`;
- logical relationships can be verified deterministically rather than guessed by an LLM;
- the LLM is well suited to parsing natural-language resolution rules and proposing candidate relationships.

Build an event graph with machine-checkable constraint types:

```text
mutually exclusive + exhaustive:
    Σ p_i ≈ 1

nested event A ⊂ B:
    p(A) ≤ p(B)

exact negation/equivalence:
    p(A) + p(not A) ≈ 1

ordered thresholds:
    P(X ≥ 10) ≤ P(X ≥ 5)

deadline nesting:
    P(by date1) ≤ P(by later date2)

conditional implications:
    A => B  implies p(A) ≤ p(B)
```

Use executable bid/ask intervals, not mids, and solve for:

1. **true arbitrage:** a guaranteed payout after all costs under exact resolution equivalence;
2. **relative-value inconsistency:** no guaranteed arbitrage, but probabilities violate a structural model enough to justify a directional trade.

The LLM can propose/parse the relationship; a deterministic constraint checker should verify it before execution. This follows the “LLM as semantic risk manager on top of statistical/mechanistic discovery” pattern supported by the ACL 2026 lead-lag paper. [E14]

### 9.2 Domain-specific quantitative specialists

The forecast ledger suggests that general narrative research is not uniformly valuable. A better architecture routes markets to **mechanistic estimators**:

- sports moneylines → bookmaker consensus/no-vig + injury/lineup news residual;
- sports spreads/totals → bookmaker line model, not generic LLM intuition;
- macro releases → consensus distribution/nowcast and release-calendar mechanics;
- price/barrier markets → options-implied distributions or explicit stochastic barrier model;
- weather → official ensemble forecast distributions;
- speech/post-count markets → Poisson/negative-binomial or intensity/hazard model with time remaining;
- scheduled product launches → base-rate survival/hazard model + verified official milestones;
- sibling bracket markets → normalized discrete distribution/constraint solver.

The LLM's job becomes: identify the correct model, retrieve inputs, check mapping/resolution semantics, and explain uncertainty.

### 9.3 Heterogeneous forecast ensemble

Current research warns that multiple agents from similar training/alignment regimes can have highly correlated errors. One 2026 prediction-market study reports high pairwise error correlation among DPO agents and finds cross-model diversity reduces it substantially. [E30]

Therefore, “50 personas using the same model” is much less attractive than:

- one market prior;
- one quantitative/mechanistic specialist;
- one retrieval-heavy language forecaster;
- one distinct-model forecaster;
- possibly one blinded forecaster that does not see the market price.

Measure pairwise residual correlation on settled events. Only keep ensemble members that add incremental held-out information.

### 9.4 Lead-lag and semantic filtering

The ACL 2026 paper on prediction-market lead-lag trading uses a two-stage pipeline:

1. statistical discovery of candidate relationships;
2. LLM semantic filtering for plausible transmission mechanisms.

The reported improvement came importantly from filtering out large losers, not merely finding more winners. [E14]

Phil could apply this pattern to:

- macro-release → central-bank decision markets;
- primary-election / nomination sibling markets;
- asset-price threshold families;
- official decision → downstream policy/market outcomes;
- source market on another venue → stale Polymarket contract.

This is more defensible than asking an LLM to invent a directional relationship from scratch.

### 9.5 Information-latency edges

Phil's “information race” class is theoretically plausible, but the current playbook has learned painful lessons about provisional facts and source finality.

Make this class machine-structured:

```text
source published_at
source fetched_at
fact finality level
resolution-source match
market last book change
market repricing velocity
trade decision time
submission time
fill time
```

A latency trade should require a finalized fact that maps deterministically to the resolution rule and a book that demonstrably has not incorporated it. If the market moves before submission, revalidation should cancel automatically.

### 9.6 Resolution-rule ambiguity as a first-class risk factor

A large prediction-market edge can be fake because the trader is forecasting the real-world event while the contract resolves on a narrower wording, source, cutoff, or adjudication rule.

Use an LLM to parse the resolution text into structured fields, but then enforce a checklist:

- exact outcome predicate;
- timezone/cutoff;
- named resolution source;
- fallback source;
- rounding convention;
- whether preliminary/revised data count;
- dispute/UMA conditions;
- cancellation/void rules.

Assign a resolution-risk score. Large numerical “edge” with high rule ambiguity should require a larger buffer or be vetoed.

---

## 10. Redesign the screener around value of information

The current cheap screener does not add directional forecast information. That does not mean screening is valueless; it means the target is wrong.

### 10.1 New target

Predict:

```text
VOI(candidate)
= P(deep research produces a validated executable net edge)
  × expected utility if it does
  - expected research/tool cost
```

or simpler:

```text
P(|residual edge after research| > cost threshold)
```

### 10.2 Pre-research features

Use features available **before** expensive research:

- spread and depth;
- market age and time-to-resolution;
- recent price movement/volatility;
- category and resolution-rule complexity;
- number/type of sibling markets;
- availability of external quantitative benchmark;
- presence of scheduled information release;
- likely official primary source accessibility;
- current market price extremity;
- historical residual skill of the appropriate research method;
- whether a fresh prior forecast already exists for the event.

### 10.3 Training label

After research, label the candidate with:

- improvement in Brier relative to pre-research baseline;
- absolute market-relative residual learned;
- whether executable net edge cleared costs;
- eventual realized proper-score improvement;
- research cost and latency.

This makes screening an **active learning / resource allocation** problem instead of a weak duplicate forecaster.

---

## 11. Proposed Phil v2 architecture

```text
                           ┌─────────────────────────────┐
                           │ Immutable protected judge   │
                           │ PIT data / fees / depth     │
                           │ settlement / event clusters │
                           └──────────────┬──────────────┘
                                          │
                        ┌─────────────────▼─────────────────┐
                        │ Candidate discovery / VOI router │
                        │ cheap, non-directional screener  │
                        └─────────────────┬─────────────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
      quantitative specialist     retrieval/news specialist    cross-market graph
      deterministic model         independent LLM forecast     constraint solver
              │                           │                           │
              └───────────────┬───────────┴───────────────┬───────────┘
                              ▼                           ▼
                    evidence/provenance store      heterogeneous ensemble
                              │                           │
                              └───────────┬───────────────┘
                                          ▼
                            market-relative calibrator
                         q_market + shrunken residual
                                          │
                                          ▼
                            protected decision engine
                      same code in replay AND live execution
                         fees / depth / latency / event risk
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                         maker quote              taker trade
                              │                       │
                              └───────────┬───────────┘
                                          ▼
                            settlement + attribution
                                          │
                         ┌────────────────┴────────────────┐
                         ▼                                 ▼
                 champion scorecard               challenger archive
                         │                                 │
                         └──── sealed promotion gate ──────┘
```

The crucial property is that the **protected decision engine is one implementation used in replay, paper, and real execution**.

---

## 12. Prioritized implementation plan

The ordering below is based on (a) how much a flaw can create false confidence, (b) expected impact on real net P&L, (c) implementation difficulty, and (d) evidence strength.

### P0 — fix before trusting any new profitability optimization

#### 1. Make one canonical decision policy and use it everywhere

**Change**  
Create a machine-readable active-policy object/function consumed by:

- historical replay;
- paper execution;
- real execution;
- forward testing.

Do not let `CYCLE.md` free-form judgment bypass it. The LLM may propose a forecast and metadata; the protected decision engine decides whether/how to trade.

**Why**  
Today `policy.py` and `risk.json` disagree. A self-improver cannot learn causally when evaluated and executed behavior differ.

**Implementation sketch**

```text
strategy/policy.py              agent-editable candidate logic
strategy/policy_manifest.json   active version + hash + training cutoff
core/decision.py                protected adapter/enforcer
core/replay.py                  calls core/decision.py in simulated mode
core/ledger.py                  accepts forecast_id, not arbitrary probability/stake
core/real.py                    mirrors an approved paper decision only after revalidation
```

Every order/fill should record `policy_hash` and `forecast_id`.

**Validation**  
For a frozen historical snapshot, compare “live-decision emulation” and replay decisions byte-for-byte. Any mismatch is a failing CI test.

**Expected impact:** very high on experimental validity; indirect but foundational on profitability.  
**Evidence:** CLQT's strategy-consistency emphasis [E07]; production evidence that operating-layer controls strongly shape behavior [E13].

#### 2. Build a truly point-in-time, stateful replay engine

**Change**  
Replay decisions chronologically. At each decision timestamp:

- policy training sees only labels with `settled_ts <= t`;
- portfolio cash/open positions are reconstructed;
- per-event/category/cycle caps are enforced;
- overlapping positions remain open until actual settlement;
- all actions use the book/fees/depth available at that timestamp.

**Why**  
The current row-independent replay can learn from labels that would have been unknown to a future `fit()` policy and can take a set of positions the live portfolio could not simultaneously hold.

**Validation**  
A “historical simulator parity” test should reproduce the actual paper ledger when fed the exact historical decisions.

**Expected impact:** very high on validity.  
**Evidence:** ForecastBench future-only design [E01], PolyBench timestamp locking [E03], AutoScientist-Quant disjoint feedback/test [E08], CLQT TimeGate [E07].

#### 3. Introduce an immutable trial registry and sealed promotion protocol

**Change**  
Every attempted strategy mutation becomes a candidate record:

```text
candidate_id
parent_id
created_at
training_cutoff
code/prompt hash
hypothesis
parameters
all discovery/validation scores
promotion status
```

No candidate can disappear from the trial count.

**Why**  
Policy v3 is openly selected after many retrospective tries. Without tracking `N`, apparent “best policy” performance is biased upward.

**Protocol**

- discovery window: mutate/search freely;
- internal validation: event-blocked/purged evaluation;
- choose a small set of challengers;
- freeze them;
- shadow on future events;
- promote only after pre-specified criteria are met;
- never change the criteria after seeing shadow outcomes.

Use DSR/PBO/CPCV as **diagnostics**, not substitutes for the sealed forward window. [E22] [E23] [E32]

**Expected impact:** very high on avoiding false alpha.

#### 4. Add current fee metadata and net-of-cost scoring

**Change**  
At every book snapshot store:

```text
fees_enabled
fee_rate
maker_rebate parameters if available
liquidity reward metadata if relevant
```

Replay and paper settlement should report both gross and net P&L.

**Why**  
Current small-edge rules can be materially changed by 4-7% fee-rate formulas in fee-enabled categories. [E24]

**Validation**  
Unit-test known fee examples, and verify historical snapshots against the market's `feesEnabled` state.

**Expected impact:** high and direct on real profitability.

#### 5. Revalidate price, fee, depth, and net edge immediately before fill

**Change**  
Paper/real `place` should receive a `forecast_id`, refetch current order book and fee state, recompute calibrated probability and net edge, and reject if the trade no longer clears the active policy.

**Why**  
The current forecast and fill can occur at different prices. Small edges are fragile to milliseconds/minutes of repricing.

**Expected impact:** high for information-race trades and small-edge policies.

#### 6. Cluster risk and inference by event

**Change**  
Create a canonical `event_id`/risk-group ID for every trade and forecast. Use it for:

- max exposure per event;
- mutually exclusive sibling accounting;
- bootstrap confidence intervals;
- replay standard errors;
- performance attribution.

**Why**  
Several contracts can be different views of one underlying uncertainty. Counting them independently inflates statistical confidence and can silently concentrate risk.

**Expected impact:** high on risk-adjusted performance and inference quality.

#### 7. Repair stale settlement/reconciliation states

**Change**  
Add statuses such as:

```text
open
market_closed_pending_resolution
resolved_pending_redeem
settled
void/disputed
```

Escalate positions that are past scheduled end but unresolved, instead of leaving them indistinguishable from ordinary open trades.

**Why**  
One supplied open paper position is 13 days past its `end_date`. Stale positions can consume cash/caps and distort the learning state.

**Expected impact:** medium operationally, high for correctness.

---

### P1 — likely sources of genuine incremental alpha

#### 8. Replace raw LLM probabilities with market-relative hierarchical calibration

**Change**  
Use the market as prior and learn only residual skill. Fit shrinkage by broad mechanism/category with a global prior toward zero residual.

**Why**  
Overall agent Brier is behind the market, while the in-sample blend gives ~79-81% weight to market. Raw agent disagreement should therefore be discounted heavily.

**Candidate model**

```text
r_i = logit(q_agent_i) - logit(m_i)
r_cal_i = shrink_group(r_i | settled historical events)
q_cal_i = logistic(logit(m_i) + r_cal_i)
```

Use rolling point-in-time fitting and event-blocked validation. A beta-calibration layer is a reasonable candidate, but simple shrinkage may be safer at current sample size. [E33]

**Expected impact:** high; likely reduces large-loss overconfidence.

#### 9. Add explicit probability uncertainty and a “net-edge lower bound” trade rule

**Change**  
Trade on conservative net edge, not point-estimate edge.

```text
LCB_net_edge = lower_bound(gross_edge) - fees - slippage - latency
trade only if LCB_net_edge > 0
```

**Why**  
The actual bet sample is overconfident. Parameter uncertainty should reduce both trade frequency and size.

**Expected impact:** high on drawdown and false-positive edges.

#### 10. Turn cross-market consistency into a deterministic solver

**Change**  
Build a graph/linear-programming engine for sibling, nested, deadline, threshold, equivalence, and negation constraints.

**Why**  
This is one of the few edge classes with a mechanistic reason to exist and is already the only real-eligible class in protected config. LLMs are useful for semantic relationship detection, while deterministic code should verify payoff logic.

**Expected impact:** potentially very high, with lower epistemic risk than pure narrative forecasting.

#### 11. Redesign the screener to predict research value, not probabilities

**Change**  
Train/rank on realized research lift or probability of finding an executable net edge.

**Why**  
Current screener adds essentially no directional information beyond price despite 29,584 scored rows.

**Expected impact:** medium-high through better use of expensive research tokens/time.

#### 12. Add specialist quantitative models and use the LLM as orchestrator

**Change**  
Implement dedicated estimators for sports, macro, barriers, weather, counts, and sibling distributions.

**Why**  
Forecasting research supports tool/retrieval scaffolds [E02], while current prediction-market evidence shows raw frontier models often fail to beat market probabilities [E03] [E04].

**Expected impact:** high where a strong outside-view model exists; low where no defensible model exists.

#### 13. Build a genuinely heterogeneous ensemble and measure marginal information

**Change**  
Combine market prior, mechanistic model, retrieval LLM, and distinct-model forecast; remove any component whose held-out residual contribution is zero.

**Why**  
Same-family agents can be strongly correlated; persona diversity is not the same as information diversity. [E30]

**Expected impact:** medium-high if true diversity is achieved.

#### 14. Enforce structured evidence provenance

**Change**  
Every material fact used in a forecast should store:

```text
source URL / identifier
publication/observation time
fetch time
primary vs secondary
quoted/extracted fact
fact-finality class
resolution-rule relevance
```

**Why**  
The playbook already contains repeated lessons about stale/provisional/ambiguous evidence. Make those lessons machine-checkable.

**Expected impact:** medium-high, especially in information-race trades.

#### 15. Canonicalize edge and method taxonomy at forecast time

**Change**  
Replace free-form/unclassified labels with validated enums and a hierarchical taxonomy.

Example:

```text
edge_family: structural | benchmark | informational | model
method: cross_market_constraint | lead_lag | bookmaker_devig | official_release | weather_ensemble | count_model | narrative_research ...
source_finality: final | provisional | inferred | ambiguous
```

**Why**  
You cannot reliably learn which methods work if a large fraction of historical decisions are unclassified.

**Expected impact:** medium through better attribution and less retrospective storytelling.

---

### P2 — optimize once the P0/P1 measurement layer is credible

#### 16. Add maker/taker execution policy and fill-quality learning

**Change**  
Record decision book, submitted order, queue/limit price, fill time, fill VWAP, fee/rebate, and subsequent short-horizon price move.

Train/estimate:

- fill probability by distance from midpoint;
- adverse selection after maker fills;
- taker slippage by depth;
- urgency class by edge type.

**Why**  
Polymarket now has zero maker fees plus maker rebates and separate liquidity rewards on eligible markets. [E25] [E26] A strategy with modest forecast edge may make or lose its economics in execution.

**Expected impact:** potentially high, but only after clean net-edge estimates exist.

#### 17. Introduce fractional, uncertainty-shrunk Kelly with event risk budgets

**Change**  
Move from flat stakes only after demonstrating forward-calibrated edge. Use posterior/shrunken probabilities, fractional Kelly, and event-level exposure limits.

**Why**  
Current probabilities are too uncertain for raw Kelly, and the literature directly supports shrinking Kelly stakes under parameter uncertainty. [E34]

**Expected impact:** medium-high on long-run capital growth if edge is real; dangerous if implemented prematurely.

#### 18. Add exits/rebalancing as a separately evaluated policy

**Change**  
For markets where positions are tradable before resolution, compare:

- hold to settlement;
- exit when edge closes;
- take-profit/stop rules;
- information-update rebalancing.

**Why**  
A production study of LLM trading agents found large favorable excursions were often not captured, suggesting operating/execution policy can matter as much as entry logic. [E13] This evidence comes from perpetual markets, so it should be treated as a hypothesis, not directly transplanted.

**Expected impact:** uncertain but potentially meaningful.

#### 19. Track model/search cost per unit of information gained

**Change**  
For each candidate and method, record compute/search/tool cost and measure:

```text
cost per researched forecast
cost per Brier improvement vs market
cost per executable net-edge discovery
net economic P&L after research cost
```

**Why**  
The current screener produces huge volume but negligible incremental directionality. A profitable autonomous system must allocate research like capital.

**Expected impact:** medium on real net economics.

#### 20. Add repeated-run stochasticity and ablations

**Change**  
For selected historical *point-in-time* episodes, rerun the same agent configuration multiple times with no outcome access. Measure decision variance. Run ablations removing news, market price, mech, tools, or particular playbook blocks.

**Why**  
LLM agents are stochastic. A single run can make a strategy change look causal when it is just sampling variance. CLQT explicitly includes a repeated-run noise floor. [E07]

**Expected impact:** medium on confidence in improvements.

#### 21. Add regime/drift monitoring

**Change**  
Track rolling event-clustered residual skill and calibration by method. Decay old evidence or trigger challenger review when a statistically meaningful drift occurs.

**Why**  
Recent policy replay folds are weaker than earlier ones, and prediction markets are non-stationary. Self-improvement should distinguish “new rule needed” from “temporary noise.”

**Expected impact:** medium; prevents stale alpha assumptions.

---

## 13. A concrete promotion protocol that would make self-improvement scientifically credible

### Stage A — discovery

The agent may freely:

- reflect;
- change prompts/tools;
- generate policy candidates;
- run exploratory tables;
- search thresholds.

But **all candidates and their results are logged**.

No discovery result is called OOS.

### Stage B — internal blocked validation

Use only historical data available before the validation endpoint, with:

- point-in-time label availability;
- event groups kept together;
- purging/embargo around overlapping resolution windows where appropriate;
- stateful portfolio simulation;
- fee/depth model;
- cluster bootstrap confidence intervals.

CPCV/PBO/DSR can be reported here as robustness diagnostics. [E22] [E23] [E32]

### Stage C — candidate freeze

Select, for example, a champion plus at most 2-3 challengers. Freeze:

- code hash;
- prompt hash;
- parameters;
- calibration model;
- decision thresholds;
- promotion criteria.

### Stage D — prospective shadow window

Run all frozen candidates on the same future markets. They may generate paper decisions, but no candidate may read the window's outcomes until its window is closed or the outcomes settle naturally.

Minimum evidence should be based on **independent event count and power**, not merely raw bet count. Foresight Arena's power calculation is a useful reminder that modest forecast edges can require hundreds of resolved binary forecasts to distinguish reliably. Its numerical power result is specific to its scoring assumptions, so Phil should compute its own. [E05]

### Stage E — promotion

A challenger promotes only if it satisfies pre-registered Pareto criteria such as:

- forecast residual skill not worse than champion beyond tolerance;
- net-after-cost trading utility better;
- event-clustered uncertainty acceptable;
- drawdown/exposure constraints satisfied;
- no single event dominates gains;
- sufficient independent-event coverage;
- no integrity/strategy-consistency failures.

Do **not** collapse everything into one opaque score if a Pareto comparison is possible.

### Stage F — archive and rollback

Never overwrite history. Keep:

```text
champion
active challengers
retired-but-good candidates
failed hypotheses
lineage graph
```

This borrows the useful archive/diversity idea from DGM, AlphaEvolve, and GEPA. [E17] [E18] [E16]

---

## 14. Specific experiments I would run next

### Experiment 1 — canonical-policy parity

**Question:** How different are the trades produced by `risk.json`/playbook versus `policy.py` on the same historical forecasts?

**Method:** replay both as explicit machine policies on the same stateful event chronology.

**Decision value:** tells you how much current strategy evidence is being attributed to the wrong decision rule.

### Experiment 2 — fee-aware replay

**Question:** Does v3's small-edge band remain profitable after fee-enabled-market costs?

**Method:** only use rows for which historical fee state can be proven; otherwise start a prospective fee-aware window.

**Prediction:** 2¢ edges near 50¢ are likely to be substantially weakened by taker fees.

### Experiment 3 — market-shrinkage challenger

**Question:** Does a market-heavy calibrated probability outperform raw agent estimates?

**Candidates:** fixed 10/20/30% agent residual plus a hierarchically fitted residual model.

**Evaluation:** Brier/log score first, then net trading utility.

### Experiment 4 — screener VOI

**Question:** Can pre-research features predict which candidates benefit from deep research?

**Label:** final reduction in Brier relative to market and whether a cost-clearing trade emerged.

**Success criterion:** event-held-out improvement in research yield per FULL-cycle research slot.

### Experiment 5 — mechanistic cross-market engine

**Question:** Does a deterministic constraint solver produce cleaner edges than LLM-only sibling reasoning?

**Start with:** exact mutually-exclusive sets, ordered thresholds, deadline nesting, and obvious negations.

**Success criterion:** positive after-cost forward P&L plus near-zero semantic mapping error.

### Experiment 6 — specialist vs generalist

For each domain with enough volume, compare:

```text
market only
LLM only
mechanistic model only
market + LLM residual
market + mechanistic residual
market + both
```

Measure marginal contribution and residual correlation.

### Experiment 7 — maker/taker simulation

On prospective orders, shadow both:

- immediate taker;
- passive quote at one or more distances.

Record whether/when the passive order would fill and what happens to the mid immediately after. This produces the data needed to estimate adverse selection rather than assuming maker is free money.

### Experiment 8 — rule-ablation study

The playbook is now large enough that it can contain redundant or contradictory rules. On future-only or safe PIT historical episodes, ablate blocks and measure behavioral change. This can identify rules that add complexity without measurable benefit.

---

## 15. Metrics the agent should optimize and report

### Forecast layer

- Brier score vs same-time market midpoint;
- log score;
- market-relative Brier/log-score improvement;
- calibration slope/intercept and reliability diagram;
- residual information contribution beyond market;
- event-clustered confidence interval;
- coverage by category/method.

### Selection/decision layer

- percentage of forecasts traded;
- net expected edge at decision;
- lower-bound net edge;
- counterfactual regret versus no-trade;
- performance by edge *mechanism*, not merely category.

### Execution layer

- decision bid/ask;
- submission bid/ask;
- fill price/VWAP;
- latency;
- spread crossed;
- taker fee or maker rebate;
- depth consumed;
- post-fill adverse selection.

### Portfolio layer

- net P&L after all trading costs;
- return on capital at risk;
- max drawdown;
- event-clustered return distribution;
- maximum event exposure;
- exposure concentration;
- capital utilization;
- turnover.

### Self-improvement/search layer

- number of candidate policies tried;
- lineage and parent;
- discovery vs validation vs sealed-forward scores;
- PBO/DSR diagnostic where appropriate;
- number of independent events;
- promotion/rollback history.

### Economic layer

- model/search/tool spend;
- cost per forecast;
- cost per useful research escalation;
- market P&L minus research/infrastructure cost.

---

## 16. What I would **not** do

1. **Do not raise stakes because the full-history replay is positive.** The selection-forward test fails its own robustness criterion and actual bet probabilities have been overconfident.
2. **Do not promote the positive historical NO-side sweep directly.** Its probability accuracy is worse than market and the result is a retrospective slice.
3. **Do not carve out categories simply because a small historical subgroup has high P&L.** Use hierarchical shrinkage and forward gates.
4. **Do not add more same-family LLM personas and call it diversification.** Measure residual correlation; contemporary evidence suggests aligned models can be monocultural. [E30]
5. **Do not use raw Kelly on current probabilities.** Probability uncertainty is too large, and parameter-uncertainty research supports shrinkage. [E34]
6. **Do not optimize only P&L.** It can reward luck, concentration, and timing while forecast skill deteriorates.
7. **Do not retroactively backfill fees with guessed category rules.** Preserve scientific integrity; only use fee metadata that can be reconstructed point-in-time.
8. **Do not let the self-improver edit the judge based on a disappointing result.** Judge changes should be operator-reviewed and versioned, with old results preserved.

---

## 17. Final prioritized improvement list

This is the concise “do this in order” version.

1. **Unify the evaluated and executed policy.** One decision engine must govern replay, paper, and real trades. This is the single most important architecture fix.
2. **Rewrite replay as a point-in-time, stateful portfolio simulator.** Only labels known at each historical decision time; enforce cash/open/event/cycle state.
3. **Add a permanent trial registry and sealed champion/challenger promotion.** Every tried rule counts; forward windows stay untouched.
4. **Make all economics net of current fees.** Record `feesEnabled` and fee rates at decision/fill; gross edge is not tradable edge.
5. **Revalidate net edge atomically at execution.** Refetch book, fees, depth, and cancel if the edge has decayed.
6. **Cluster both risk and statistical inference by underlying event.** Do not count sibling markets as independent evidence.
7. **Fix stale-resolution states and reconciliation.** Closed-but-unresolved is a distinct state; prevent stale positions distorting cash/caps.
8. **Use the market as the prior and shrink the LLM residual heavily.** Current aggregate forecast evidence says the market deserves most of the weight.
9. **Attach uncertainty to every calibrated probability and trade only conservative net edge.** Point estimates are currently overconfident on the trade sample.
10. **Build a deterministic cross-market constraint engine.** Let the LLM parse semantics; let code verify logic and executable arbitrage/relative value.
11. **Redesign the cheap screener for research value-of-information.** It currently has essentially zero incremental directional forecasting information.
12. **Route markets to domain-specific quantitative specialists.** Bookmakers, macro nowcasts, weather ensembles, count models, barrier/option models, and sibling distributions should provide numerical anchors.
13. **Use heterogeneous ensembles and test marginal information.** Diversity should mean independent residual signal, not different personas.
14. **Make evidence provenance structured and point-in-time.** Store source publication time, fetch time, finality, and resolution relevance.
15. **Canonicalize edge/method labels.** Eliminate `unclassified` wherever possible so the system can learn which mechanisms actually work.
16. **Add maker/taker optimization only after fee-aware net-edge modeling exists.** Makers can avoid fees and earn rebates/rewards, but adverse selection must be learned.
17. **Introduce fractional uncertainty-shrunk Kelly only after robust forward calibration.** Flat small stakes are preferable until then.
18. **Test exit/rebalancing policies separately.** Entry alpha and exit skill are different hypotheses.
19. **Track research/model cost and optimize net economic profit.** Expensive research that adds no marginal information is negative alpha operationally.
20. **Run repeated-seed and ablation tests.** Distinguish a genuine strategy improvement from LLM sampling variance.
21. **Monitor drift and decay old evidence.** An adaptive system should detect when a formerly useful method stops contributing.

---

## 18. Overall conclusion

Phil is more sophisticated than a typical “LLM reads news and trades” demo. It has several unusually good ideas already in place: a protected execution/scoring core, honest cross-the-spread paper fills, stake-free forecast logging, explicit market benchmarking, counterfactual analysis, retrospective learning, source-quality lessons, and a pre-registered forward test. Those are worth preserving.

But the current system is in a revealing phase: **its instrumentation is becoming good enough to show that much of its apparent edge is not yet robust**.

The evidence currently says:

- the broad research process does not beat the market midpoint in aggregate;
- actual paper trades have lost slightly and were substantially overconfident;
- the cheap screener adds almost no directional information beyond price;
- the attractive v3 replay was selected in-sample;
- the clean forward test does not pass the repo's own confidence-weighted criterion;
- and the policy being replay-optimized is not identical to the live paper decision rule.

That is not a reason to abandon the architecture. It is a reason to **tighten the loop**.

The most promising version of Phil is not an LLM that becomes increasingly convinced it can outguess every market. It is a system that becomes increasingly good at recognizing **when it possesses information or structure the market has not yet priced**, quantifying how uncertain that residual is, and declining to trade the rest.

If the P0 measurement/execution fixes are implemented first, the next generation of improvements—market-relative calibration, cross-market constraints, specialist quantitative models, heterogeneous ensembles, value-of-information research allocation, and maker/taker optimization—can be assessed without fooling the system. Only then does more sophisticated sizing make sense.

In short: **the highest-return improvement right now is improving the truthfulness of the self-improvement loop itself.** A self-improving trader becomes profitable only if it can tell the difference between genuine transferable edge and an attractive story fitted to its own history.

---

# Appendix A — Local repository evidence map

These are the main repository locations supporting the audit.

| Finding | Repository evidence |
|---|---|
| Agent can edit strategy but not core/config | `CYCLE.md:6-36`; `loop.sh:193-201` |
| Forecast every researched concrete probability | `CYCLE.md:285-297` |
| Live betting instruction uses `risk.json` | `CYCLE.md:298-306` |
| Paper fills at current live best ask | `core/ledger.py:8-10`, `68-119` |
| Broker does not enforce `policy.py` | `core/ledger.py:68-119`; no policy import/call |
| Forecast stores bid/ask/mid | `core/forecast.py:114-146` |
| Extreme disagreement confirmation | `core/forecast.py:125-132` |
| Replay's stated purpose | `core/replay.py:1-50` |
| Replay fill logic | `core/replay.py:120-152` |
| Replay per-bet cw_return SE | `core/replay.py:165-184` |
| Row-independent policy application | `core/replay.py:187-205` |
| Forward split by settlement knowledge | `core/replay.py:208-222` |
| Walk-forward train uses prior record-time chunks with outcomes | `core/replay.py:225-244` |
| Policy v3 thresholds | `strategy/policy.py:66-99` |
| Policy selection explicitly in-sample | `strategy/policy.py:42-56` |
| Current live risk thresholds | `strategy/risk.json` |
| Real-money caps / allowed edge class | `config/protected.json:22-29` |
| Real trade mirrors paper row | `core/real.py:191-228` |
| Real buy path | `core/real.py:230-250` |
| Forward-test preregistration/verdict | `.github/scripts/forward_test.py` |
| Playbook is agent-editable episodic knowledge | `strategy/playbook.md:1-12` and subsequent dated sections |

---

# Appendix B — Recomputed audit outputs

## B.1 Paper ledger status

```text
cash: $971.46
open positions: 4
settled positions: 47
wins: 19
realized P&L: -$8.54
```

One open row has scheduled `end_date=2026-09-13T00:00:00Z` in the 2026-09-26 snapshot.

## B.2 Stake-free forecast score

```text
settled = 875
open = 129
brier_delta vs market mid = +0.0082
z = +0.43
```

## B.3 Policy replay

```text
5 folds:
  held rows 688
  bets 71
  staked $355
  P&L +$111.61
  ROI +0.314
  cw_return +0.1136
  Brier delta -0.0060

10 folds:
  held rows 774
  bets 77
  staked $385
  P&L +$142.30
  ROI +0.370
  cw_return +0.1765
  Brier delta -0.0075
```

These are not selection-OOS because the policy file itself says its thresholds were selected with all then-settled rows visible.

## B.4 True forward test

```text
cutoff: 2026-09-02T00:14:36Z
usable rows settled after cutoff: 441
policy bets: 58
P&L: +$20.62
Brier delta: -0.0019
cw_return: -0.0975
pre-registered verdict: FAIL
```

## B.5 Screener

```text
73,800 total screener rows
19,742 markets
29,584 scored rows
5,852 event clusters
ALL Brier: 0.3483
market mids Brier: 0.3450
delta: +0.0033
excess directional component: ~0.0000, z +0.1
blend market weight w_opt: 1.006 overall
```

---

# Appendix C — Source quality notes

- **Peer-reviewed** sources are strongest for general principles but may be older than the current agent ecosystem.
- **Official Polymarket documentation** is authoritative for current platform mechanics, but fee/reward parameters can change and should be fetched live in production.
- **2025-2026 preprints and working papers** are useful because the field is moving rapidly, but their profitability claims should be treated as provisional until replicated.
- **Phil's own journal** is the strongest evidence for what this specific system did, but retrospective slices are subject to search/selection bias.

---

# References

## Forecasting and prediction-market evaluation

**[E01]** Karger, E. et al. (2025). *ForecastBench: A Dynamic Benchmark of AI Forecasting Capabilities*. ICLR 2025.  
https://proceedings.iclr.cc/paper_files/paper/2025/hash/ea74e45a229dac70b5b63b28d8934db6-Abstract-Conference.html

Current benchmark site (dynamic, continuously updated):  
https://forecastbench.org/

**[E02]** Halawi, D. et al. (2024). *Approaching Human-Level Forecasting with Language Models*. NeurIPS 2024.  
https://proceedings.neurips.cc/paper_files/paper/2024/hash/5a5acfd0876c940d81619c1dc60e7748-Abstract-Conference.html

**[E03]** Cheng, P., Liu, J., Long, Y. (2026). *PolyBench: Benchmarking LLM Forecasting and Trading Capabilities on Live Prediction Market Data*. arXiv:2604.14199.  
https://arxiv.org/abs/2604.14199

**[E04]** Ding, J., Guo, C., Xu, J. (2026). *FIFA World Cup 2026 as a Contamination-Free Benchmark for LLM Forecasting Agents*. arXiv:2607.17765.  
https://arxiv.org/abs/2607.17765

**[E05]** Nechepurenko, M., Shuvalov, P. (2026). *Foresight Arena: An On-Chain Benchmark for Evaluating AI Forecasting Agents*. SSRN 6674059.  
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6674059

**[E29]** Varghese, J., Bickmann, L., Sandmann, S. (2026). *Information Specialization and Constrained Synthesis in Multi-Agent LLM Forecasting: A Prospective Live-Study of the 2026 FIFA World Cup*. arXiv:2609.12495.  
https://arxiv.org/abs/2609.12495

**[E30]** Begin, J. et al. (2026). *Preference Optimization Drives Monoculture in LLM Prediction Markets*. arXiv:2606.26583.  
https://arxiv.org/abs/2606.26583

**[E31]** Barot, R. M., Borkhatariya, A. S. (2026). *PolySwarm: A Multi-Agent Large Language Model Framework for Prediction Market Trading and Latency Arbitrage*. arXiv:2604.03888.  
https://arxiv.org/abs/2604.03888

## Self-improving / agentic trading systems

**[E06]** Kim, S. et al. (2026). *EvolveTrade: Experience-Driven Policy Refinement for Self-Evolving LLM Trading Agents*. arXiv:2609.17632.  
https://arxiv.org/abs/2609.17632

**[E07]** Qu, B., Chen, M. (2026). *CLQT: A Closed-Loop, Cost-Aware, Strategy-Consistent Benchmark for Diagnostic Evaluation of LLM Portfolio-Management Agents*. arXiv:2606.29771.  
https://arxiv.org/abs/2606.29771

**[E08]** Li, Z. et al. (2026). *AutoScientist-Quant: Self-Evolving Coding Agents for Automatic Research in Quantitative Investment*. arXiv:2608.28632.  
https://arxiv.org/abs/2608.28632

**[E09]** Xia, Y. et al. (2026). *Agentic Trading: When LLM Agents Meet Financial Markets*. arXiv:2605.19337.  
https://arxiv.org/abs/2605.19337

**[E10]** Zhu, T. et al. (2026). *From Knowing to Doing: A Memory-Controlled Benchmark for LLM Trading Agents on Stock Markets (KTD-Fin)*. arXiv:2605.28359.  
https://arxiv.org/abs/2605.28359

**[E11]** Fan, T. et al. (2025). *AI-Trader: Benchmarking Autonomous Agents in Real-Time Financial Markets*. arXiv:2512.10971.  
https://arxiv.org/abs/2512.10971

**[E12]** Qian, L. et al. (2025). *When Agents Trade: Live Multi-Market Trading Benchmark for LLM Agents*. arXiv:2510.11695.  
https://arxiv.org/abs/2510.11695

**[E13]** Barton, T. J. et al. (2026). *What LLM Trading Agents Actually Do in Production: A Six-Month, Population-Scale Record from Two Fleets*. arXiv:2609.05663.  
https://arxiv.org/abs/2609.05663

**[E14]** Kim, S. et al. (2026). *LLM as a Risk Manager: LLM Semantic Filtering for Lead-Lag Trading in Prediction Markets*. ACL 2026 Industry Track / arXiv:2602.07048.  
https://arxiv.org/abs/2602.07048  
https://aclanthology.org/volumes/2026.acl-industry/

## Self-improvement, prompt/program evolution

**[E15]** Shinn, N. et al. (2023). *Reflexion: Language Agents with Verbal Reinforcement Learning*. NeurIPS 2023.  
https://papers.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html

**[E16]** Agrawal, L. A. et al. (2025). *GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning*. arXiv:2507.19457.  
https://arxiv.org/abs/2507.19457

**[E17]** Zhang, J. et al. (2025). *Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents*. arXiv:2505.22954.  
https://arxiv.org/abs/2505.22954

**[E18]** Novikov, A. et al. (2025). *AlphaEvolve: A Coding Agent for Scientific and Algorithmic Discovery*. arXiv:2506.13131.  
https://arxiv.org/abs/2506.13131

**[E19]** Siper, M. et al. (2025/2026). *ProFiT: Program Search for Financial Trading*. SSRN 5889762.  
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5889762

**[E20]** Kvasiuk, Y. et al. (2026). *MadEvolve: Evolutionary Optimization of Trading Systems with Large Language Models*. arXiv:2605.23007.  
https://arxiv.org/abs/2605.23007

**[E21]** Siper, M. et al. (2026). *Continuous Program Search*. arXiv:2602.07659.  
https://arxiv.org/abs/2602.07659

## Backtest overfitting and validation

**[E22]** Bailey, D. H., López de Prado, M. (2014). *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality*. Journal of Portfolio Management.  
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

**[E23]** Bailey, D. H., Borwein, J., López de Prado, M., Zhu, Q. J. (2015). *The Probability of Backtest Overfitting*. Journal of Computational Finance.  
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

**[E32]** Arian, H., Norouzi Mobarekeh, D., Seco, L. (2024). *Backtest overfitting in the machine learning era: A comparison of out-of-sample testing methods in a synthetic controlled environment*. Knowledge-Based Systems 305, 112477.  
https://doi.org/10.1016/j.knosys.2024.112477

## Calibration and sizing

**[E33]** Kull, M., Silva Filho, T., Flach, P. (2017). *Beta calibration: a well-founded and easily implemented improvement on logistic calibration for binary classifiers*. AISTATS 2017.  
https://proceedings.mlr.press/v54/kull17a.html

**[E34]** Baker, R. D., McHale, I. G. (2013). *Optimal Betting Under Parameter Uncertainty: Improving the Kelly Criterion*. Decision Analysis 10(3).  
https://pubsonline.informs.org/doi/10.1287/deca.2013.0271

**[E35]** Turtel, B. et al. (2026). *How Proper Scoring Rules Shape LLM Forecasting*. arXiv:2608.28482.  
https://arxiv.org/abs/2608.28482

## Current Polymarket execution mechanics

**[E24]** Polymarket Help Center (2026-07-10). *Trading Fees*.  
https://help.polymarket.com/en/articles/13364478-trading-fees

**[E25]** Polymarket Help Center (2026-07-21). *Maker Rebates Program*.  
https://help.polymarket.com/en/articles/13364471-maker-rebates-program

**[E26]** Polymarket Help Center (2026-06-15). *Liquidity Rewards*.  
https://help.polymarket.com/en/articles/13364466-liquidity-rewards

**[E27]** Polymarket Help Center (2026-03-13). *How Are Prices Calculated?*  
https://help.polymarket.com/en/articles/13364488-how-are-prices-calculated

**[E28]** Polymarket Help Center (2026-01-11). *Does Polymarket Have Trading Limits?*  
https://help.polymarket.com/en/articles/13364481-does-polymarket-have-trading-limits

---

*End of report.*
