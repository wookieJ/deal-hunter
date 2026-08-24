"""Data shapes shared across the pipeline.

Deliberately source-agnostic: a Source adapter's only job is to turn whatever a
marketplace returns into RawListing, so everything downstream (normalise, score,
store, report) never learns that OLX exists.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RawListing:
    source: str
    external_id: str
    url: str
    title: str
    description: str
    price: float | None
    currency: str = "PLN"
    negotiable: bool = False
    location: str = ""
    lat: float | None = None
    lon: float | None = None
    created_at: str = ""
    refreshed_at: str = ""
    photos: list[str] = field(default_factory=list)
    params: dict[str, str] = field(default_factory=dict)
    is_business: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.external_id}"

    @property
    def content_hash(self) -> str:
        """Identity of the *content*, not the offer. Drives change detection."""
        blob = f"{self.price}|{self.title.strip()}|{self.description.strip()}"
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    @property
    def text(self) -> str:
        """Everything a normalizer should read, lowercased."""
        params = " ".join(f"{k} {v}" for k, v in self.params.items())
        return f"{self.title}\n{self.description}\n{params}".lower()


@dataclass(slots=True)
class ScoreResult:
    value: int                                    # 0-100
    verdict: str                                  # one-line human summary
    reasons: list[str] = field(default_factory=list)   # signed, human-readable
    disqualified: bool = False
    disqualified_by: str = ""


# Attributes are an open dict, not a dataclass: a new product type adds new keys
# without touching this file or the storage layer (they are persisted as JSON).
Attributes = dict[str, Any]
