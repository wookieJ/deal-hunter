"""Rough market-value estimate, used to spot genuine bargains.

Entirely driven by the domain's `value_model` block: a quality tier maps to a
base price, categorical attributes scale it, and age discounts it. The engine
supplies no defaults of its own - without a value model there is nothing to
compare an asking price against, so no estimate is made and no bargain bonus is
awarded. Guessing would be worse than staying silent.

This is a heuristic, not comparable-sales data. It answers "is this cheap for
what it is?", never "what is this worth?". Replacing it with reference prices
computed from `listing_version` history is the natural next step, and would not
change this interface.
"""
from __future__ import annotations

from typing import Any


def estimate(attrs: dict[str, Any], spec: dict[str, Any] | None = None,
             current_year: int = 2026) -> float | None:
    """Estimated fair asking price, or None when the domain declares no model."""
    if not spec or not spec.get("base_by_tier"):
        return None

    tier = attrs.get(spec["tier_attr"]) if spec.get("tier_attr") else None
    if tier is None:
        base = spec.get("unknown_base")
        if base is None:
            return None
    else:
        base = next((price for threshold, price in spec["base_by_tier"] if tier >= threshold),
                    spec.get("unknown_base"))
        if base is None:
            return None

    value = float(base)
    for attr, factors in (spec.get("factors") or {}).items():
        value *= factors.get((attrs.get(attr) or "").lower(), 1.0)

    age_cfg = spec.get("age")
    year = attrs.get(spec["year_attr"]) if spec.get("year_attr") else None
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
    """Points for a price well below the spec's market level, or a nudge above it."""
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
