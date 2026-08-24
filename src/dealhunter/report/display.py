"""What to show for an offer - declared by the domain, not by the reporter.

Without this the reporters would have to know that a bike has a groupset and a
laptop has a CPU, which would put product knowledge straight back into the
engine. A domain's `display:` block names the attributes worth showing; the
reporters just render whatever comes back.
"""
from __future__ import annotations

from typing import Any

from .. import domains


def _pick(entry: dict[str, Any], attrs: dict[str, Any]) -> str:
    """First attribute in the list that has a value, formatted per the domain."""
    for name in entry.get("attrs", []):
        value = attrs.get(name)
        if value in (None, "", []):
            continue
        prefix = (entry.get("prefix") or {}).get(name, "")
        suffix = (entry.get("suffix") or {}).get(name, "")
        return f"{prefix}{value}{suffix}"
    return entry.get("fallback", "")


def annotate(rows: list[dict[str, Any]], domain: str | None) -> None:
    spec = (domains.load(domain).get("display") or {})
    summary = spec.get("summary") or []
    chips = spec.get("chips") or []

    for row in rows:
        attrs = row.get("attrs") or {}
        row["summary_fields"] = [text for text in (_pick(e, attrs) for e in summary) if text]
        row["chip_fields"] = [str(attrs[name]) for name in chips
                              if attrs.get(name) not in (None, "", [])]
