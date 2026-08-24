"""Resolve a listing to manufacturer geometry (reach / stack).

Nominal frame sizes are not comparable across brands: a Merida Silex L and a
race-geometry L put the rider in very different positions. Where we can identify
the exact model and generation, real geometry beats the size label - so this
module tries that first and reports how confident the match is.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .. import config


@lru_cache(maxsize=1)
def _table() -> dict[str, list[dict[str, Any]]]:
    path = config.ROOT / "config" / "geometry.yml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve(brand: str, title: str, size_letter: str, year: int | None) -> dict[str, Any]:
    """Look up reach/stack for this bike, or return an empty result.

    Confidence degrades when the model year is unknown and the model spans several
    generations with different geometry - which is common and worth being honest
    about rather than silently picking one.
    """
    empty = {"geo_reach": None, "geo_stack": None, "geo_model": "",
             "geo_confidence": "", "geo_note": ""}
    if not brand or not size_letter:
        return empty

    entries = _table().get(brand.lower())
    if not entries:
        return empty

    text = title.lower()
    matching = [e for e in entries if re.search(rf"\b{re.escape(e['model'])}\b", text)]
    if not matching:
        return empty

    # Narrow by model year when the listing gave us one.
    dated = [e for e in matching
             if year and e.get("years") and e["years"][0] <= year <= e["years"][1]]
    ambiguous = False
    if dated:
        chosen = dated[0]
    else:
        # No year, or no generation covers it: prefer the newest generation, but
        # say so, because generations of the same model differ by >15 mm of reach.
        chosen = max(matching, key=lambda e: (e.get("years") or [0])[0])
        ambiguous = len(matching) > 1

    spec = (chosen.get("sizes") or {}).get(size_letter.upper())
    if not spec:
        return empty

    if ambiguous:
        confidence, note = "ambiguous", f"model year unknown, assumed {chosen['generation']}"
    elif not chosen.get("verified", False):
        confidence, note = "unverified", "geometry unverified"
    else:
        confidence, note = "exact", chosen["generation"]

    return {
        "geo_reach": spec.get("reach"),
        "geo_stack": spec.get("stack"),
        "geo_model": f"{brand} {chosen['model']} {size_letter.upper()}",
        "geo_confidence": confidence,
        "geo_note": note,
    }
