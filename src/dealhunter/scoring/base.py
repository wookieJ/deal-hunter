"""Scorer contract: (Attributes, RawListing, profile) -> ScoreResult.

The profile is data, so retuning what counts as a good deal means editing YAML,
never Python. A future price-history or LLM signal becomes another weighted
dimension in the same sum.
"""
from __future__ import annotations

from typing import Any, Protocol

from ..models import Attributes, RawListing, ScoreResult


class Scorer(Protocol):
    category: str

    def score(self, attrs: Attributes, raw: RawListing, profile: dict[str, Any]) -> ScoreResult: ...


def get_scorer(category: str) -> Scorer:
    if category == "bikes":
        from .bikes import BikeScorer
        return BikeScorer()
    raise ValueError(f"No scorer for category: {category!r}")
