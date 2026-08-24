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


def estimate(attrs: dict[str, Any], spec: dict[str, Any] | None = None,
             current_year: int = 2026) -> float | None:
    """Estimated fair asking price, or None when we know too little.

    Driven entirely by the domain's `value_model` block, so a new product type
    prices its own spec without touching this file.
    """
    spec = spec or {}
    tier = attrs.get(spec.get("tier_attr", "groupset_tier"))
    if tier is None:
        base = spec.get("unknown_base", UNKNOWN_GROUPSET_BASE)
    else:
        table = spec.get("base_by_tier") or TIER_BASE
        base = next((price for threshold, price in table if tier >= threshold),
                    spec.get("unknown_base", UNKNOWN_GROUPSET_BASE))

    value = float(base)
    for attr, factors in (spec.get("factors") or {}).items():
        value *= factors.get((attrs.get(attr) or "").lower(), 1.0)

    age_cfg = spec.get("age")
    year = attrs.get(spec.get("year_attr", "model_year"))
    if age_cfg and year:
        age = max(0, current_year - year)
        for max_age, factor in age_cfg.get("bands", []):
            if age <= max_age:
                value *= factor
                break
        else:
            value *= age_cfg.get("older", 1.0)
    return round(value)


def bargain(price: float | None, attrs: dict[str, Any],
            spec: dict[str, Any] | None = None) -> tuple[float, str]:
    """Points to add for a price well below the spec's market level (or subtract above it)."""
    fair = estimate(attrs, spec)
    if not price or not fair:
        return 0.0, ""
    ratio = fair / price
    if ratio >= 2.0:
        return 12.0, f"+12 bargain: ~{fair:.0f} PLN market vs {price:.0f} PLN"
    if ratio >= 1.6:
        return 8.0, f"+8 bargain: ~{fair:.0f} PLN market vs {price:.0f} PLN"
    if ratio >= 1.3:
        return 4.0, f"+4 below market level (~{fair:.0f} PLN)"
    if ratio < 0.75:
        return -4.0, f"-4 expensive for the spec (~{fair:.0f} PLN market)"
    return 0.0, ""
