"""Normalizer contract: RawListing -> Attributes (a plain dict).

The implementation is generic; what it extracts comes from a domain pack. See
`dealhunter.domains` and docs/extending.md.
"""
from __future__ import annotations

from typing import Protocol

from ..models import Attributes, RawListing


class Normalizer(Protocol):
    category: str

    def normalize(self, raw: RawListing) -> Attributes: ...


def get_normalizer(domain: str) -> Normalizer:
    from .engine import Engine
    return Engine(domain)
