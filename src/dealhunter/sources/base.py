"""Source adapter contract.

Adding a marketplace (Allegro, Sprzedajemy, ...) means implementing this Protocol
and registering it in get_source(). Nothing downstream changes.
"""
from __future__ import annotations

from typing import Any, Iterator, Protocol

from ..models import RawListing


class Source(Protocol):
    name: str

    def search(self, spec: dict[str, Any]) -> Iterator[RawListing]:
        """Yield offers matching one profile's search spec, already deduplicated."""
        ...

    def parse(self, payload: dict[str, Any]) -> RawListing:
        """Rebuild a listing from a stored raw payload, so offers can be rescored
        against a changed profile without hitting the network again."""
        ...


def get_source(name: str, settings: dict[str, Any]) -> Source:
    if name == "olx":
        from .olx import OlxSource
        return OlxSource(settings)
    raise ValueError(f"Unknown source: {name!r}")
