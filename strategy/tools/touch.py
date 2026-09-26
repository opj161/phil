#!/usr/bin/env python3
"""Driftless lognormal price-level probabilities with a SOURCED vol input.

Usage:
  python3 strategy/tools/touch.py --spot 76074 --barrier 75000 --days 13 \
      --ann-vol 0.4725 --vol-source "Deribit DVOL 2026-09-07"            # touch
  python3 strategy/tools/touch.py --mode above --spot 771 --barrier 765 \
      --days 0.3 --ann-vol 0.149 --vol-source "^VIX 2026-09-26"          # close above
  python3 strategy/tools/touch.py --mode between --spot 84060 --barrier 82000 \
      --upper 86000 --days 2 --ann-vol 0.34 --vol-source "Deribit DVOL"  # bracket

Modes (T = days / year_days, sigma = ann-vol):
  touch    P(path touches B before T) = 2 * (1 - Phi(|ln(B/S)| / (sigma sqrt T)))
           (reflection principle; direction-free, so a touch the spot is
           already beyond is a resolved market, not a model question)
  above    P(S_T > K) = Phi((ln(S/K) - sigma^2 T / 2) / (sigma sqrt T))
           (martingale price: ln S_T ~ N(ln S - sigma^2 T/2, sigma^2 T))
  below    1 - above
  between  above(K_low) - above(K_high)

Why (RETRO-20260918-1410): guessed-vol inputs were retired by the touch-family
ruling (DEEP-2026-09-01), so this refuses to run without a named vol source.
It also prints the estimate at 0.75x and 1.25x the vol: if the edge's sign
flips inside that band, the row has no robust disagreement with the market.
For commodity ladders pass the ACTIVE-MONTH contract price as --spot
(playbook, 2026-09-17). strategy/tools/lanes.py imports these functions to
price the barrier lane in bulk.
"""
import argparse
import json
import math
import sys

MODES = ("touch", "above", "below", "between")


def _phi(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def p_touch(spot, barrier, days, ann_vol, year_days=365.0):
    sd = ann_vol * math.sqrt(days / year_days)
    d = abs(math.log(barrier / spot)) / sd
    return math.erfc(d / math.sqrt(2))  # == 2 * (1 - Phi(d))


def p_above(spot, strike, days, ann_vol, year_days=365.0):
    sd = ann_vol * math.sqrt(days / year_days)
    return _phi((math.log(spot / strike) - sd * sd / 2) / sd)


def price(mode, spot, level, days, ann_vol, upper=None, year_days=365.0):
    if mode == "touch":
        return p_touch(spot, level, days, ann_vol, year_days)
    if mode == "above":
        return p_above(spot, level, days, ann_vol, year_days)
    if mode == "below":
        return 1.0 - p_above(spot, level, days, ann_vol, year_days)
    if mode == "between":
        lo, hi = sorted((level, upper))
        return p_above(spot, lo, days, ann_vol, year_days) - p_above(spot, hi, days, ann_vol, year_days)
    raise ValueError(f"mode must be one of {MODES}")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=MODES, default="touch")
    ap.add_argument("--spot", type=float, required=True)
    ap.add_argument("--barrier", type=float, required=True, help="barrier / strike / lower bound")
    ap.add_argument("--upper", type=float, help="upper bound (between mode)")
    ap.add_argument("--days", type=float, required=True)
    ap.add_argument("--ann-vol", type=float, required=True,
                    help="annualized vol as a fraction, e.g. 0.47")
    ap.add_argument("--vol-source", required=True,
                    help="named, dated source of the vol number")
    ap.add_argument("--year-days", type=float, default=365.0)
    a = ap.parse_args(argv)
    if len(a.vol_source.strip()) < 8:
        ap.error("--vol-source must name a dated source (guessed vol is retired)")
    if not (a.spot > 0 and a.barrier > 0 and a.days > 0 and 0 < a.ann_vol < 5):
        ap.error("spot, barrier, days must be > 0 and ann-vol a fraction in (0, 5)")
    if a.mode == "between" and not (a.upper and a.upper > 0):
        ap.error("--upper is required in between mode")

    def p(vol):
        return round(price(a.mode, a.spot, a.barrier, a.days, vol, a.upper, a.year_days), 4)

    print(json.dumps({
        "mode": a.mode, "p": p(a.ann_vol),
        "p_vol_x0.75": p(a.ann_vol * 0.75), "p_vol_x1.25": p(a.ann_vol * 1.25),
        "gap_pct": round(100 * (a.barrier / a.spot - 1), 3),
        "ann_vol": a.ann_vol, "vol_source": a.vol_source.strip(),
    }, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
