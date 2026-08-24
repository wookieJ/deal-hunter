"""Generic reference lookup: brand + model generation + variant -> known values.

Listings name a model, not its specification. Where a reference table exists, the
real numbers beat whatever the seller typed. The table itself is domain-specific
by nature and lives inside the domain file that owns it, under `lookups:`; this
module only knows how to read one.

Table shape, under `lookups: <table name>:`

    <brand>:
      - model: <name matched as a word in the title>
        generation: <human label, shown when the match is uncertain>
        years: [from, to]
        verified: true|false
        variants:
          <VARIANT>: { <key>: <value>, ... }
"""
from __future__ import annotations

import re
from typing import Any

from .. import domains


def _table(domain: str, name: str) -> dict[str, list[dict[str, Any]]]:
    return (domains.load(domain).get("lookups") or {}).get(name) or {}


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

    # `sizes` is accepted as a legacy alias for `variants`.
    values = (chosen.get("variants") or chosen.get("sizes") or {}).get(variant.upper())
    if not values:
        return None

    if ambiguous:
        confidence = "ambiguous"
        note = f"model year unknown, assumed {chosen['generation']}"
    elif not chosen.get("verified", False):
        confidence, note = "unverified", "reference data unverified"
    else:
        confidence, note = "exact", chosen["generation"]

    return {"values": values, "confidence": confidence, "note": note,
            "model": f"{brand} {chosen['model']} {variant.upper()}"}
