# Real-execution addendum

`loop.sh --real` appends this section to your cycle prompt, and ONLY on a
machine with a healthy Pearl Connect signer. Real money is involved.
Everything in CYCLE.md still applies; these steps are additive.

## Extra steps

- During **Settle** (step 1), also run `python3 core/real.py settle`. It
  sweeps filled positions to the Safe, redeems resolved ones, and reconciles
  any ambiguous submissions. Report anomalies in the cycle log: reverted
  redemptions, unresolved pending orders.
- After **each paper bet the engine places** (step 6), run
  `python3 core/real.py place --paper-id <paper ledger id>`.
  core/real.py mirrors only engine bets in a lane that is `live` in
  config/lanes.json and listed in config/protected.json
  `real.allowed_lanes`. The stake comes from `real.max_stake_usd`; never
  pass `--usd`. A refusal (lane not live, cap hit, market already held,
  unreconciled order) is policy working, not an error to fix.
- In the **Log** line (step 8), append ` | real: placed R settled S`.

## Hard rules for real mode

- core/real.py is the ONLY way you touch real funds. Never call Pearl
  Connect signing tools or the skill scripts directly.
- Never blind-retry a failed or timed-out real order: buys are not
  idempotent. core/real.py blocks new bets while any order is unreconciled;
  respect that.
- A guardrail refusal from the signer names the rule it violated. Relay it
  verbatim in the cycle log and move on; never work around it.
- A 403 or geoblock on order placement is venue policy. Report it and stop
  real execution for the cycle. Do not attempt to circumvent it.
- Never write tokens, config contents, or signer URLs to the journal: the
  journal is public. Wallet addresses are fine.
