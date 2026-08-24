"""Normalizer contract: RawListing -> Attributes (a plain dict).

A new product type = a new module here + `category:` in the profile. The MVP
chain is regex-only; an LLM or image enricher would append to the same dict,
which is why Attributes is an open dict rather than a fixed dataclass.
"""
from __future__ import annotations

from typing import Any, Protocol

from ..models import Attributes, RawListing


class Normalizer(Protocol):
    category: str

    def normalize(self, raw: RawListing) -> Attributes: ...


def get_normalizer(category: str) -> Normalizer:
    if category == "bikes":
        from .bikes import BikeNormalizer
        return BikeNormalizer()
    raise ValueError(f"No normalizer for category: {category!r}")
