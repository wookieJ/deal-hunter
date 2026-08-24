"""OLX adapter.

Uses OLX's own JSON API (the endpoint their web frontend calls) rather than HTML
scraping - it returns clean, structured offers including the full description.

The one hard requirement: OLX rejects plain HTTP clients with 403 based on TLS
fingerprint, so we go through curl_cffi impersonating Chrome. requests/httpx will
NOT work here.
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any, Iterator

from curl_cffi import requests

from ..models import RawListing

API = "https://www.olx.pl/api/v1/offers/"
PAGE_SIZE = 40
_TAG_RE = re.compile(r"<[^>]+>")

# Bike categories, for reference when writing a profile:
CATEGORIES = {
    "rowery": 461, "gravel": 4242, "mtb": 1651, "szosowe": 1652,
    "crossowe": 1648, "trekkingowe": 1653, "miejskie": 1650,
    "elektryczne": 1649, "skladane": 4243, "dzieciece": 1681, "pozostale": 1656,
}


def _clean(text: str) -> str:
    return html.unescape(_TAG_RE.sub("\n", text or "")).strip()


class OlxSource:
    name = "olx"

    def __init__(self, settings: dict[str, Any]):
        http = settings.get("http", {})
        self.rate_limit = float(http.get("rate_limit_s", 1.0))
        self.timeout = int(http.get("timeout_s", 30))
        self.retries = int(http.get("retries", 3))
        self.session = requests.Session(impersonate=http.get("impersonate", "chrome"))
        self._last_request = 0.0

    # ------------------------------------------------------------------ http
    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                r = self.session.get(API, params=params, timeout=self.timeout)
                self._last_request = time.monotonic()
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (403, 429, 503):
                    time.sleep(2 ** attempt * 2)
                    last_error = RuntimeError(f"HTTP {r.status_code}")
                    continue
                raise RuntimeError(f"OLX HTTP {r.status_code}: {r.text[:200]}")
            except Exception as exc:  # network hiccup - retry with backoff
                last_error = exc
                time.sleep(2 ** attempt)
        raise RuntimeError(f"OLX request failed after {self.retries} attempts: {last_error}")

    # ---------------------------------------------------------------- search
    def search(self, spec: dict[str, Any]) -> Iterator[RawListing]:
        queries = spec.get("queries") or [""]
        max_pages = int(spec.get("max_pages", 3))
        seen: set[str] = set()

        for query in queries:
            for page in range(max_pages):
                params: dict[str, Any] = {
                    "offset": page * PAGE_SIZE,
                    "limit": PAGE_SIZE,
                    "category_id": spec["category_id"],
                    "sort_by": spec.get("sort_by", "created_at:desc"),
                }
                if query:
                    params["query"] = query
                if spec.get("price_from") is not None:
                    params["filter_float_price:from"] = spec["price_from"]
                if spec.get("price_to") is not None:
                    params["filter_float_price:to"] = spec["price_to"]
                if spec.get("owner_type"):
                    params["owner_type"] = spec["owner_type"]
                # Search area: narrows the hunt AND pushes back the 1000-result
                # cap. OLX accepts distances of 0, 2, 5, 10, 15, 30, 50, 75, 100 km.
                area = spec.get("area") or {}
                if area.get("city_id"):
                    params["city_id"] = area["city_id"]
                    if area.get("radius_km"):
                        params["distance"] = area["radius_km"]
                elif area.get("region_id"):
                    params["region_id"] = area["region_id"]

                payload = self._get(params)
                offers = payload.get("data", [])
                if not offers:
                    break

                for offer in offers:
                    listing = self.parse(offer)
                    if listing.external_id in seen:
                        continue      # promoted ads repeat across pages
                    seen.add(listing.external_id)
                    yield listing

                total = payload.get("metadata", {}).get("total_elements", 0)
                if (page + 1) * PAGE_SIZE >= total:
                    break

    # ----------------------------------------------------------------- parse
    def parse(self, o: dict[str, Any]) -> RawListing:
        """Public: also used to rebuild listings from archived payloads on rescore."""
        price: float | None = None
        negotiable = False
        params: dict[str, str] = {}
        for p in o.get("params", []):
            value = p.get("value")
            if p.get("key") == "price" and isinstance(value, dict):
                price = value.get("value")
                negotiable = bool(value.get("negotiable"))
            elif isinstance(value, dict):
                params[p["key"]] = str(value.get("label") or value.get("key") or "")
            elif value is not None:
                params[p["key"]] = str(value)

        loc = o.get("location") or {}
        location = ", ".join(
            filter(None, [(loc.get("city") or {}).get("name"), (loc.get("region") or {}).get("name")])
        )
        photos = [
            (p.get("link") or "").replace("{width}x{height}", "600x450")
            for p in (o.get("photos") or [])
        ][:6]

        geo = o.get("map") or {}

        return RawListing(
            source=self.name,
            external_id=str(o["id"]),
            url=o.get("url", ""),
            title=o.get("title", ""),
            description=_clean(o.get("description", "")),
            price=price,
            currency="PLN",
            negotiable=negotiable,
            location=location,
            lat=geo.get("lat"),
            lon=geo.get("lon"),
            created_at=o.get("created_time", ""),
            refreshed_at=o.get("last_refresh_time", ""),
            photos=[p for p in photos if p],
            params=params,
            is_business=bool(o.get("business")),
            raw=o,
        )


def archive_raw(listings: list[RawListing], run_id: int, base: Path) -> Path:
    """Keep the untouched payloads - re-parsing history beats re-scraping it."""
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"run-{run_id:05d}.json"
    path.write_text(
        json.dumps([l.raw for l in listings], ensure_ascii=False), encoding="utf-8"
    )
    return path
