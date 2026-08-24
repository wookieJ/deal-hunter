"""Generic spec lookup: brand + model generation + variant -> known attributes.

Marketplace listings name a model, not its specification. Where a reference table
exists, real numbers beat whatever the seller wrote - a bike's reach and stack
beat its size label, just as a laptop's real panel beats "14 inch". This module
resolves that lookup for any category; the tables live in config/lookups/.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml

from .. import config


@lru_cache(maxsize=8)
def _table(domain: str, name: str) -> dict[str, list[dict[str, Any]]]:
    path = config.ROOT / "domains" / domain / "lookups" / f"{name}.yml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve(table: str, domain: str, brand: str, title: str, variant: str,
            year: int | None) -> dict[str, Any] | None:
    """Return the matching entry's values plus how confident the match is.

    Confidence degrades when the year is unknown and the model spans several
    generations with different numbers - common, and worth being honest about
    rather than silently picking one.
    """
    if not brand or not variant:
        return None
    entries = _table(domain, table).get(brand.lower())
    if not entries:
        return None

    text = title.lower()
    matching = [e for e in entries if re.search(rf"\b{re.escape(e['model'])}\b", text)]
    if not matching:
        return None

    dated = [e for e in matching
             if year and e.get("years") and e["years"][0] <= year <= e["years"][1]]
    ambiguous = False
    if dated:
        chosen = dated[0]
    else:
        chosen = max(matching, key=lambda e: (e.get("years") or [0])[0])
        ambiguous = len(matching) > 1

    values = (chosen.get("sizes") or chosen.get("variants") or {}).get(variant.upper())
    if not values:
        return None

    if ambiguous:
        confidence = "ambiguous"
        note = f"model year unknown, assumed {chosen['generation']}"
    elif not chosen.get("verified", False):
        confidence, note = "unverified", "geometry unverified"
    else:
        confidence, note = "exact", chosen["generation"]

    return {"values": values, "confidence": confidence, "note": note,
            "model": f"{brand} {chosen['model']} {variant.upper()}"}
