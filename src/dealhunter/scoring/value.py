"""Rough market-value estimate for a used bike, used to spot genuine bargains.

This is a heuristic, not comparable-sales data: it prices the spec (groupset tier,
frame material, brakes, age, condition) against typical Polish second-hand levels.
It is good enough to answer "is this cheap for what it is?" - which is the question
that separates a real deal from a merely well-equipped, fully-priced bike - but it
should never be read as an appraisal.

Replacing this with real reference prices computed from listing_version history is
the natural next step; the interface would not change.
"""
from __future__ import annotations

from typing import Any

# Typical Polish used-market asking price for a gravel bike with an aluminium
# frame, disc brakes and this groupset tier, in good condition.
TIER_BASE = [
    (90, 6000),   # GRX 800/820, Force, Ultegra, Dura-Ace
    (75, 4200),   # GRX 600, GRX, 105, Rival, Deore XT
    (60, 3200),   # GRX 400, Tiagra, Apex, SLX
    (45, 2500),   # Deore, CUES, NX, microSHIFT
    (0, 1900),    # Sora, Claris, Altus, Tourney
]
UNKNOWN_GROUPSET_BASE = 2500

MATERIAL_FACTOR = {"carbon": 1.6, "titanium": 1.8, "cromoly": 1.05,
                   "steel": 0.95, "aluminium": 1.0}
BRAKE_FACTOR = {"hydraulic_disc": 1.10, "mechanical_disc": 1.0, "disc": 1.03, "rim": 0.82}
CONDITION_FACTOR = {"nowe": 1.30, "jak nowe": 1.15, "odnowione": 1.0,
                    "używane": 1.0, "uzywane": 1.0, "uszkodzone": 0.5}


def estimate(attrs: dict[str, Any], current_year: int = 2026) -> float | None:
    """Estimated fair asking price in PLN, or None when we know too little."""
    tier = attrs.get("groupset_tier")
    if tier is None:
        base = UNKNOWN_GROUPSET_BASE
    else:
        base = next(price for threshold, price in TIER_BASE if tier >= threshold)

    value = base
    value *= MATERIAL_FACTOR.get(attrs.get("frame_material") or "", 1.0)
    value *= BRAKE_FACTOR.get(attrs.get("brakes") or "", 1.0)
    value *= CONDITION_FACTOR.get((attrs.get("condition") or "").lower(), 1.0)

    year = attrs.get("model_year")
    if year:
        age = max(0, current_year - year)
        if age <= 2:
            value *= 1.10
        elif age <= 5:
            value *= 0.95
        elif age <= 9:
            value *= 0.80
        else:
            value *= 0.65
    return round(value)


def bargain(price: float | None, attrs: dict[str, Any]) -> tuple[float, str]:
    """Points to add for a price well below the spec's market level (or subtract above it)."""
    fair = estimate(attrs)
    if not price or not fair:
        return 0.0, ""
    ratio = fair / price
    if ratio >= 2.0:
        return 12.0, f"+12 okazja: ~{fair:.0f} zl rynkowo vs {price:.0f} zl"
    if ratio >= 1.6:
        return 8.0, f"+8 okazja: ~{fair:.0f} zl rynkowo vs {price:.0f} zl"
    if ratio >= 1.3:
        return 4.0, f"+4 ponizej poziomu rynkowego (~{fair:.0f} zl)"
    if ratio < 0.75:
        return -4.0, f"-4 drogo jak na osprzet (~{fair:.0f} zl rynkowo)"
    return 0.0, ""
