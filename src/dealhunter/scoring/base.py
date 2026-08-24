"""Scorer contract: (Attributes, RawListing, profile) -> ScoreResult.

The maths is generic; the dimensions come from a domain pack and their weights
from the profile. See `dealhunter.domains` and docs/extending.md.
"""
from __future__ import annotations

from typing import Any, Protocol

from ..models import Attributes, RawListing, ScoreResult


class Scorer(Protocol):
    category: str

    def score(self, attrs: Attributes, raw: RawListing, profile: dict[str, Any]) -> ScoreResult: ...


def get_scorer(domain: str | None) -> Scorer:
    from .engine import Engine
    return Engine(domain)
