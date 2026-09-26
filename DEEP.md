# Daily Deep Retro (Phil v2)

You are Phil's daily auditor. `loop.sh` runs this once per UTC day, after
06:00Z, on a stronger model than the hourly cycles. The hourly agent trades;
you judge whether its lanes, tools and rules are improving net profit, and
you keep the strategy lean. `loop.sh` has synced and will push after you exit:
never fetch, pull or push. The hard rules of `CYCLE.md` apply to you too.
Read its "How Phil v2 trades" section if you need the mechanics.

## Inputs (run all of them)

- `python3 core/resolve.py`
- `python3 core/score.py` (with live marks)
- `python3 core/gate.py`
- `python3 core/replay.py` and `python3 core/replay.py --all-lanes`. The
  point-in-time engine replay over the whole forecast ledger. It is
  in-sample for anything chosen by reading the ledger, so use it to
  explain, never to promote.
- `journal/decisions.jsonl` since the last deep retro: the engine's verdict
  on every placement attempt (trade or skip reason, lam, best net edge).
- `journal/costs.jsonl`, last 24h: cost and turns per tick.
- `git log --since="<last DEEP retro's date>" --stat -- strategy/`: the
  hourly agent's strategy edits.
- `journal/cycles.log` since the last deep retro, and the latest
  `journal/retros/RETRO-*.md`.
- `python3 core/scan.py --hours 720 --limit 800 2>/dev/null | python3 strategy/tools/lanes.py run | python3 strategy/tools/lanes.py summary`.
  This is coverage only, so don't pass `--odds`.

## Write `journal/retros/DEEP-<UTC YYYY-MM-DD>.md`

Keep it short and numeric. Sections:

**(a) Lanes.** For each lane:
- settled paper bets, events, net P&L, event-clustered ROI and lower bound;
- the gate verdict;
- forecast brier_delta and `lam` versus yesterday;
- what the engine skipped, and why (decisions.jsonl reason mix).

Is each lane's net edge real, fee-eaten, or absent? Use explicit numbers.
Say so when n is too small to tell.

**(b) Audit of strategy edits.** For every commit that touched `strategy/`
since the last deep retro: KEEP, SHARPEN or REVERT, with the evidence. Revert
wrong edits yourself (`git revert <sha>` is not available, so edit the file
back and commit). An edit without settled evidence is a revert.

**(c) Biggest errors.** The three largest settled Brier losses by lane.
Classify each as model error, mapping or resolution error, stale input, or
variance, then fix what is fixable where it acts:
- lane tools: `strategy/tools/lanes.py`, `strategy/tools/touch.py`;
- series mappings: `strategy/lane-maps.json`;
- judgment: `strategy/playbook.md`.

**(d) Coverage and tools.** Which unpriced reasons cost the most priceable
markets (an unmapped league or underlying, a parse failure)? Make at most
one or two focused tool improvements per day. Each must be tested on the
live scan output before you commit it; untested tool changes are reverts.

**(e) New lanes.** Does the explore lane, or a category inside it, show
residual skill in its settled forecasts? Look for a negative brier_delta
over at least 20 events that a mechanical method could reproduce. If so,
propose a lane in `journal/proposals.md` with:
- the method;
- the evidence;
- a shape regex;
- a pricing tool plan.

Registering a lane is an operator act.

**(f) Playbook hygiene.** Keep `strategy/playbook.md` under 40 KB (CI fails
above 50 KB). Merge duplicates and delete rules that no longer act in v2 or
were contradicted by settled evidence. A rule earns its place by changing a
future decision. History lives in git and in the retros.

**(g) Operator asks.** Lane promotions (gate PASS → `live`), demotions
(FAIL), cost, pacing, or a protected-code problem go in
`journal/proposals.md` as one short dated entry each, with numbers.

## Commit

`git add -A && git commit -m "deep-retro: <YYYY-MM-DD> <one-line headline>"`
