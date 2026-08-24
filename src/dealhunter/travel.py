"""Driving distance and time from home to an offer.

Straight-line distance is already computed during scoring; this adds the number
you actually care about when deciding whether to go and look at a bike.

Two design points worth knowing:

* Lookups happen only for offers that made it into a report, and results are
  cached on a coarse coordinate grid, so a run costs a handful of requests at
  most - many offers share a city.
* The public OSRM server rejects browser-impersonating clients, which is the
  exact opposite of what OLX demands. This module therefore uses plain urllib
  with an honest User-Agent, and must not reuse the curl_cffi session.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .scoring.engine import haversine_km

USER_AGENT = "deal-hunter/0.1 (personal use; https://github.com/wookieJ/deal-hunter)"


class TravelEstimator:
    def __init__(self, conn, settings: dict[str, Any], home: dict[str, Any] | None):
        cfg = settings.get("travel", {})
        self.conn = conn
        self.home = home or {}
        self.enabled = bool(cfg.get("enabled", False)) and bool(self.home)
        self.url = cfg.get("url", "https://router.project-osrm.org").rstrip("/")
        self.rate_limit = float(cfg.get("rate_limit_s", 1.0))
        self.budget = int(cfg.get("max_lookups_per_run", 40))
        self.road_factor = float(cfg.get("road_factor", 1.35))
        self._last_call = 0.0

    # ------------------------------------------------------------------ cache
    @staticmethod
    def _key(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
        return f"{lat1:.2f},{lon1:.2f}|{lat2:.2f},{lon2:.2f}"

    def _cached(self, key: str) -> tuple[float, float] | None:
        row = self.conn.execute(
            "SELECT km, minutes FROM travel_cache WHERE key=?", (key,)).fetchone()
        return (row["km"], row["minutes"]) if row else None

    def _store(self, key: str, km: float, minutes: float) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO travel_cache(key, km, minutes, fetched_at) VALUES (?,?,?,?)",
            (key, km, minutes, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self.conn.commit()

    # ----------------------------------------------------------------- lookup
    def _route(self, lat: float, lon: float) -> tuple[float, float] | None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        url = (f"{self.url}/route/v1/driving/"
               f"{self.home['lon']},{self.home['lat']};{lon},{lat}?overview=false")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.load(response)
            self._last_call = time.monotonic()
            route = payload["routes"][0]
            return route["distance"] / 1000.0, route["duration"] / 60.0
        except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError):
            self._last_call = time.monotonic()
            return None    # fall back to the straight-line estimate

    def annotate(self, *groups: list[dict[str, Any]]) -> None:
        """Add straight_km, drive_km, drive_min and drive_estimated to offer rows."""
        if not self.home:
            return
        seen: dict[str, dict[str, Any]] = {}
        for group in groups:
            for row in group:
                seen.setdefault(row["uid"], row)

        remaining = self.budget
        for row in sorted(seen.values(), key=lambda r: -r.get("value", 0)):
            lat, lon = row.get("lat"), row.get("lon")
            if lat is None or lon is None:
                continue
            straight = haversine_km(self.home["lat"], self.home["lon"], lat, lon)
            row["straight_km"] = round(straight)

            result = None
            if self.enabled:
                key = self._key(self.home["lat"], self.home["lon"], lat, lon)
                result = self._cached(key)
                if result is None and remaining > 0:
                    remaining -= 1
                    fetched = self._route(lat, lon)
                    if fetched:
                        self._store(key, *fetched)
                        result = fetched

            if result:
                row["drive_km"], row["drive_min"] = round(result[0]), round(result[1])
                row["drive_estimated"] = False
            else:
                row["drive_km"] = round(straight * self.road_factor)
                row["drive_min"] = None
                row["drive_estimated"] = True

        # Rows sharing a city can reuse a neighbour's answer for free.
        for group in groups:
            for row in group:
                enriched = seen.get(row["uid"])
                if enriched is not row and enriched and "drive_km" in enriched:
                    row.update({k: enriched[k] for k in
                                ("straight_km", "drive_km", "drive_min", "drive_estimated")})
