#!/usr/bin/env bash
# Run Phil headlessly (Phil v2: one runner, this machine).
# Usage: ./loop.sh [ticks] [tick_minutes] [--real]
#   ticks         how many ticks to run (default 1; e.g. 100000 for 24/7)
#   tick_minutes  minutes between ticks (default 60); the wait is spent
#                 polling core/watch.py every 15 minutes, and a watch trigger
#                 starts the next tick early as a TRIGGERED FULL cycle
#   --real        append REAL.md so live-lane paper bets get a $1 real twin via
#                 Pearl Connect (needs PEARL_CONNECT_STORE and a healthy local
#                 signer; downgrades to paper otherwise)
#
# Each tick: sync -> settle (python, no LLM) -> one of
#   FULL      claude -p CYCLE.md       when strategy/schedule.json says it is due
#   DEEP      claude -p DEEP.md        once per UTC day, after 06:00Z
#   LIGHT     nothing else             otherwise (no LLM call at all)
# -> protected-path guard -> push. Every claude run appends its cost to
# journal/costs.jsonl (--output-format json reports total_cost_usd).
#
# Env: PHIL_MODEL (FULL cycles, default claude-sonnet-5), PHIL_DEEP_MODEL
# (daily deep retro, default claude-opus-5-5). .env is loaded if present
# (ODDS_API_KEY lives there; it is gitignored).
set -euo pipefail
cd "$(dirname "$0")"

# One loop per checkout: two loops in one working tree commit over each other.
LOCK=".loop.pid"
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "ERROR: loop.sh is already running in this checkout (pid $(cat "$LOCK")); refusing to start a second one" >&2
  exit 1
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

if [ -f .env ]; then set -a; . ./.env; set +a; fi
[ -z "${ODDS_API_KEY:-}" ] && echo "NOTE: ODDS_API_KEY unset — the devig lane cannot price (core/odds.py)" >&2

PHIL_MODEL="${PHIL_MODEL:-claude-sonnet-5}"
PHIL_DEEP_MODEL="${PHIL_DEEP_MODEL:-claude-opus-5-5}"
PROTECTED_PATHS=(core/ config/ .github/ CYCLE.md DEEP.md REAL.md loop.sh CLAUDE.md LICENSE README.md .gitignore)
PROTECTED_RE='^(core/|config/|\.github/|CYCLE\.md|DEEP\.md|REAL\.md|loop\.sh|CLAUDE\.md|LICENSE|README\.md|\.gitignore)'

REAL_MODE=0
ARGS=()
for a in "$@"; do
  [ "$a" = "--real" ] && REAL_MODE=1 || ARGS+=("$a")
done
TICKS="${ARGS[0]:-1}"
TICK_MIN="${ARGS[1]:-60}"
mkdir -p work

now() { date -u +%FT%TZ; }

sync_origin() {
  # A detached HEAD makes `git push origin main` push a stale ref (2026-08-17).
  if ! git symbolic-ref -q HEAD >/dev/null; then
    echo "WARNING: HEAD detached — reattaching main to HEAD" >&2
    git checkout -B main HEAD
  fi
  git remote get-url origin >/dev/null 2>&1 || return 0
  if git fetch origin main 2>/dev/null; then
    if git merge-base --is-ancestor HEAD origin/main; then
      git checkout -q -B main origin/main
    elif ! git merge-base --is-ancestor origin/main HEAD; then
      echo "WARNING: local main and origin/main have diverged — resolve manually" >&2
    fi
  else
    echo "WARNING: could not fetch origin/main; ticking on local state" >&2
  fi
}

push_origin() {
  git remote get-url origin >/dev/null 2>&1 || return 0
  if ! git symbolic-ref -q HEAD >/dev/null; then
    git checkout -B main HEAD
  fi
  if ! git push -q origin main; then
    echo "push rejected — rebasing onto origin/main and retrying" >&2
    if git pull -q --rebase origin main; then
      git push -q origin main || echo "WARNING: push still failing after rebase — resolve manually" >&2
    else
      git rebase --abort 2>/dev/null || true
      echo "WARNING: rebase onto origin/main failed — commits are local only, resolve manually" >&2
    fi
  fi
}

guard_protected() {
  if ! git diff --quiet HEAD -- "${PROTECTED_PATHS[@]}"; then
    echo "WARNING: agent touched protected files — reverting" >&2
    git checkout -- "${PROTECTED_PATHS[@]}"
  fi
  local sha
  for sha in $(git log -5 --format=%H); do
    case "$(git log -1 --format=%s "$sha")" in operator:*) continue ;; esac
    if git diff-tree --no-commit-id --name-only -r "$sha" | grep -qE "$PROTECTED_RE"; then
      echo "WARNING: agent commit ${sha:0:8} touches protected files — review manually (CI fails it)" >&2
    fi
  done
}

full_due() {
  # FULL when next_full_cycle_after has passed, or when fewer than
  # min_full_cycles_per_day FULL cycles ran in the last 24h.
  python3 - <<'PY'
import datetime as dt, json, re, sys
now = dt.datetime.now(dt.timezone.utc)
s = json.load(open("strategy/schedule.json"))
hold = s.get("next_full_cycle_after")
if not hold or dt.datetime.fromisoformat(hold.replace("Z", "+00:00")) <= now:
    sys.exit(0)
full = 0
for line in open("journal/cycles.log"):
    m = re.match(r"(\S+Z) cycle done: .*\(FULL", line)
    if not m:
        continue
    try:
        t = dt.datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
    except ValueError:
        continue
    full += now - t <= dt.timedelta(hours=24)
sys.exit(0 if full < s.get("min_full_cycles_per_day", 1) else 1)
PY
}

deep_due() {
  # Once per UTC day, after 06:00Z (the day's overnight settlements are in).
  # The attempt marker stops a failed deep run from re-running every tick.
  [ "$(date -u +%H)" -ge 6 ] || return 1
  [ ! -f "journal/retros/DEEP-$(date -u +%F).md" ] && [ ! -f "work/deep-attempted-$(date -u +%F)" ]
}

ensure_paced() {
  # A FULL cycle must leave next_full_cycle_after in the future; if it did
  # not (crash, forgotten step), pace 2h out so a broken cycle cannot rerun
  # every hour on the subscription.
  python3 - <<'PY'
import datetime as dt, json
p = "strategy/schedule.json"
s = json.load(open(p))
now = dt.datetime.now(dt.timezone.utc)
hold = s.get("next_full_cycle_after")
if not hold or dt.datetime.fromisoformat(hold.replace("Z", "+00:00")) <= now:
    s["next_full_cycle_after"] = (now + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    s["reason"] = "loop.sh fallback: the last FULL cycle left no future pacing"
    open(p, "w").write(json.dumps(s, indent=2) + "\n")
    print("pacing fallback applied (+2h)")
PY
}

run_claude() {  # $1 = tick label, $2 = model, $3 = prompt
  local out="work/claude-last.json" start end
  start=$(date +%s)
  # Isolated from the operator's personal Claude Code setup: project/local
  # settings only (no user hooks, plugins or user CLAUDE.md) and no auto
  # memory (a headless trader must not write the operator's memory dir).
  local cmd=(claude -p "$3" --model "$2" --output-format json --setting-sources project,local
       --allowedTools "Read" "Glob" "Grep" "WebSearch" "WebFetch" "Edit" "Write" "Task"
         "Bash(python3 core/*)" "Bash(python3 strategy/*)"
         "Bash(git add:*)" "Bash(git commit:*)" "Bash(git rev-parse:*)" "Bash(git log:*)"
         "Bash(git diff:*)" "Bash(git status:*)" "Bash(git show:*)"
         "Bash(git checkout -B main HEAD)"
       --permission-mode acceptEdits)
  if [ "$REAL_MODE" -eq 1 ] && [ "${PEARL_UP:-0}" -eq 1 ]; then
    # wallet_info is read-only; real orders go through core/real.py only.
    cmd+=("mcp__pearl-connect__wallet_info" --mcp-config "$STORE/.mcp.json"
          --disallowedTools "Read($STORE/.mcp.json)")
  fi
  CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/usr/bin/true GIT_EDITOR=true \
    "${cmd[@]}" > "$out" 2> work/claude-last.err || echo "claude run ($1) failed; continuing" >&2
  end=$(date +%s)
  python3 - "$1" "$2" "$((end - start))" "$out" <<'PY' || true
import datetime as dt, json, sys
tick, model, secs, path = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
try:
    r = json.load(open(path))
except Exception:
    r = {}
if isinstance(r, list):  # newer CLIs emit the message list; the result is last
    r = next((m for m in reversed(r) if isinstance(m, dict) and m.get("type") == "result"), {})
row = {"ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "tick": tick, "model": model, "seconds": secs,
       "total_cost_usd": r.get("total_cost_usd"), "num_turns": r.get("num_turns"),
       "duration_ms": r.get("duration_ms"), "is_error": r.get("is_error")}
open("journal/costs.jsonl", "a").write(json.dumps(row) + "\n")
print((r.get("result") or "")[-1500:])
PY
}

TRIGGER=""
for i in $(seq 1 "$TICKS"); do
  echo "=== tick $i/$TICKS $(now) ==="
  sync_origin

  PEARL_UP=0
  STORE="${PEARL_CONNECT_STORE:-}"
  if [ "$REAL_MODE" -eq 1 ] && [ -n "$STORE" ] && [ -f "$STORE/.mcp.json" ]; then
    # Only the connect signer's healthcheck body is bare (no "rounds" field).
    HC="$(curl -sf -m 2 http://127.0.0.1:8716/healthcheck 2>/dev/null || true)"
    if echo "$HC" | grep -q '"is_healthy": *true' && ! echo "$HC" | grep -q '"rounds"' \
       && python3 core/real.py doctor 2>/dev/null | grep -q '"ready": true'; then
      PEARL_UP=1
    else
      echo "WARNING: --real requested but Pearl Connect signer not ready — paper only" >&2
    fi
  fi

  if deep_due; then
    echo "tick: DEEP (daily retro, $PHIL_DEEP_MODEL)" >&2
    touch "work/deep-attempted-$(date -u +%F)"
    run_claude DEEP "$PHIL_DEEP_MODEL" "$(cat DEEP.md)"
  elif [ -n "$TRIGGER" ] || full_due; then
    PROMPT="$(cat CYCLE.md)"
    LABEL=FULL
    if [ -n "$TRIGGER" ]; then
      LABEL=TRIGGERED
      PROMPT="$PROMPT

## This tick is TRIGGERED
core/watch.py fired between ticks. Run the full procedure, but put the
markets in this verdict first in step 4, and open the cycle log detail with
\`(TRIGGERED: <keys>\`:
$TRIGGER"
    fi
    if [ "$REAL_MODE" -eq 1 ] && [ "$PEARL_UP" -eq 1 ]; then
      PROMPT="$PROMPT
$(cat REAL.md)"
    fi
    echo "tick: $LABEL ($PHIL_MODEL)" >&2
    run_claude "$LABEL" "$PHIL_MODEL" "$PROMPT"
    if [ -n "$(ensure_paced)" ]; then
      git add strategy/schedule.json && git commit -qm "cycle: $(date -u +%Y%m%d-%H%M) pacing fallback" || true
    fi
  else
    # LIGHT: settle and log without an LLM. Settlements are committed so the
    # next FULL cycle's retro sees them.
    python3 core/resolve.py | tail -1
    CASH=$(python3 core/ledger.py status | python3 -c "import json,sys; print(json.load(sys.stdin)['cash'])")
    echo "$(now) cycle done: LIGHT tick (no LLM), cash \$$CASH (LIGHT)" >> journal/cycles.log
    git add journal/ && git commit -qm "cycle: $(date -u +%Y%m%d-%H%M) LIGHT settle" || true
  fi
  TRIGGER=""

  guard_protected
  push_origin

  [ "$i" -ge "$TICKS" ] && break
  # Wait for the next tick, polling the watcher every 15 minutes.
  waited=0
  while [ "$waited" -lt "$TICK_MIN" ]; do
    step=$(( TICK_MIN - waited < 15 ? TICK_MIN - waited : 15 ))
    sleep $((step * 60))
    waited=$((waited + step))
    VERDICT="$(python3 core/watch.py check 2>/dev/null || true)"
    if echo "$VERDICT" | grep -q '"trigger": *true'; then
      echo "watch: trigger — starting the next tick early" >&2
      TRIGGER="$VERDICT"  # watch.py logged the fire in journal/watch-triggers.jsonl
      break
    fi
  done
done
