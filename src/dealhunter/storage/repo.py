"""Persistence + change detection.

NOTE on disappeared offers: a run only sees the first N pages of a search, so an
offer missing from today's results has usually just been pushed out of the window
by newer ones, not sold. We therefore never auto-deactivate listings - doing so
would report constant false "gone" events. Detecting real removals needs a
per-listing detail re-check, which is a deliberate post-MVP step.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from ..models import Attributes, RawListing, ScoreResult

Status = Literal["new", "changed", "seen"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repo:
    def __init__(self, conn):
        self.conn = conn

    # ---------------------------------------------------------------- runs
    def start_run(self, profile: str, source: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO run(profile, source, started_at) VALUES (?,?,?)",
            (profile, source, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, found: int, new: int, changed: int, seen: int) -> None:
        self.conn.execute(
            "UPDATE run SET finished_at=?, n_found=?, n_new=?, n_changed=?, n_seen=? WHERE id=?",
            (_now(), found, new, changed, seen, run_id),
        )
        self.conn.commit()

    def is_first_run(self, profile: str) -> bool:
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM run WHERE profile=? AND finished_at IS NOT NULL", (profile,)
        ).fetchone()
        return row["c"] == 0

    # ------------------------------------------------------------ listings
    def upsert(self, raw: RawListing, run_id: int) -> tuple[Status, list[str]]:
        """Insert or update one offer. Returns its status and what changed."""
        now = _now()
        prev = self.conn.execute(
            "SELECT price, title, content_hash FROM listing_version "
            "WHERE uid=? ORDER BY id DESC LIMIT 1",
            (raw.uid,),
        ).fetchone()

        if prev is None:
            status: Status = "new"
            changes: list[str] = []
            self.conn.execute(
                "INSERT INTO listing(uid, source, external_id, url, title, location, "
                "lat, lon, is_business, created_at, first_seen_at, last_seen_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (raw.uid, raw.source, raw.external_id, raw.url, raw.title, raw.location,
                 raw.lat, raw.lon, int(raw.is_business), raw.created_at, now, now),
            )
        elif prev["content_hash"] != raw.content_hash:
            status = "changed"
            changes = self._diff(prev, raw)
            self.conn.execute(
                "UPDATE listing SET last_seen_at=?, title=?, url=?, lat=?, lon=?, "
                "is_active=1 WHERE uid=?",
                (now, raw.title, raw.url, raw.lat, raw.lon, raw.uid),
            )
        else:
            self.conn.execute(
                "UPDATE listing SET last_seen_at=?, lat=COALESCE(lat, ?), "
                "lon=COALESCE(lon, ?), is_active=1 WHERE uid=?",
                (now, raw.lat, raw.lon, raw.uid),
            )
            self.conn.commit()
            return "seen", []

        self.conn.execute(
            "INSERT INTO listing_version(uid, run_id, seen_at, content_hash, price, currency, "
            "title, description, photos_json, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (raw.uid, run_id, now, raw.content_hash, raw.price, raw.currency, raw.title,
             raw.description, json.dumps(raw.photos), json.dumps(raw.raw, ensure_ascii=False)),
        )
        self.conn.commit()
        return status, changes

    @staticmethod
    def _diff(prev, raw: RawListing) -> list[str]:
        changes = []
        old_price, new_price = prev["price"], raw.price
        if old_price is not None and new_price is not None and old_price != new_price:
            delta = new_price - old_price
            arrow = "spadek" if delta < 0 else "wzrost"
            pct = (delta / old_price * 100) if old_price else 0
            changes.append(
                f"cena: {old_price:.0f} -> {new_price:.0f} zl "
                f"({arrow} {abs(delta):.0f} zl, {pct:+.1f}%)"
            )
        if prev["title"] != raw.title:
            changes.append("tytul zmieniony")
        if not changes:
            changes.append("opis zmieniony")
        return changes

    def save_attrs(self, uid: str, category: str, attrs: Attributes) -> None:
        self.conn.execute(
            "INSERT INTO listing_attrs(uid, category, attrs_json, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(uid) DO UPDATE SET attrs_json=excluded.attrs_json, "
            "category=excluded.category, updated_at=excluded.updated_at",
            (uid, category, json.dumps(attrs, ensure_ascii=False), _now()),
        )

    def save_score(self, uid: str, profile: str, s: ScoreResult,
                   profile_hash: str = "") -> None:
        self.conn.execute(
            "INSERT INTO score(uid, profile, value, verdict, reasons_json, disqualified, "
            "profile_hash, scored_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(uid, profile) DO UPDATE SET "
            "value=excluded.value, verdict=excluded.verdict, reasons_json=excluded.reasons_json, "
            "disqualified=excluded.disqualified, profile_hash=excluded.profile_hash, "
            "scored_at=excluded.scored_at",
            (uid, profile, s.value, s.verdict, json.dumps(s.reasons, ensure_ascii=False),
             int(s.disqualified), profile_hash, _now()),
        )

    def stale(self, profile: str, profile_hash: str) -> list[dict[str, Any]]:
        """Listings whose stored score was computed under different scoring rules.

        The archived payload is enough to rebuild and rescore them offline, so a
        profile change never leaves unreproducible numbers in the ranking.
        """
        rows = self.conn.execute(
            "SELECT l.uid, l.source, v.raw_json FROM listing l "
            "JOIN score s ON s.uid=l.uid AND s.profile=? "
            "LEFT JOIN listing_version v ON v.id=(SELECT id FROM listing_version "
            "        WHERE uid=l.uid ORDER BY id DESC LIMIT 1) "
            "WHERE COALESCE(s.profile_hash, '') != ? AND v.raw_json IS NOT NULL",
            (profile, profile_hash),
        )
        return [{"uid": r["uid"], "source": r["source"],
                 "payload": json.loads(r["raw_json"])} for r in rows]

    def update_coordinates(self, uid: str, lat: float | None, lon: float | None) -> None:
        if lat is not None and lon is not None:
            self.conn.execute(
                "UPDATE listing SET lat=COALESCE(lat, ?), lon=COALESCE(lon, ?) WHERE uid=?",
                (lat, lon, uid))

    def commit(self) -> None:
        self.conn.commit()

    # ------------------------------------------------------------- queries
    def top(self, profile: str, limit: int = 15, uids: list[str] | None = None,
            include_disqualified: bool = False) -> list[dict[str, Any]]:
        sql = (
            "SELECT l.uid, l.url, l.title, l.location, l.lat, l.lon, "
            "       l.is_business, l.first_seen_at, "
            "       s.value, s.verdict, s.reasons_json, s.disqualified, "
            "       a.attrs_json, v.price, v.photos_json "
            "FROM listing l "
            "JOIN score s ON s.uid=l.uid AND s.profile=? "
            "LEFT JOIN listing_attrs a ON a.uid=l.uid "
            "LEFT JOIN listing_version v ON v.id=(SELECT id FROM listing_version "
            "        WHERE uid=l.uid ORDER BY id DESC LIMIT 1) "
            "WHERE l.is_active=1 "
        )
        params: list[Any] = [profile]
        if not include_disqualified:
            sql += "AND s.disqualified=0 "
        if uids is not None:
            if not uids:
                return []
            sql += f"AND l.uid IN ({','.join('?' * len(uids))}) "
            params += uids
        sql += "ORDER BY s.value DESC, v.price ASC LIMIT ?"
        params.append(limit)
        return [self._row(r) for r in self.conn.execute(sql, params)]

    def price_history(self, uid: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT seen_at, price FROM listing_version WHERE uid=? ORDER BY id", (uid,)
        )
        return [dict(r) for r in rows]

    def clear(self, keep_travel_cache: bool = True) -> dict[str, int]:
        """Wipe collected offers. Returns what was removed.

        `travel_cache` is kept by default: it maps coordinates to road distances,
        which never go stale and cost a routing request each to rebuild. It holds
        no information about offers, so keeping it cannot skew anything.
        """
        tables = ["score", "listing_attrs", "listing_version", "listing", "run"]
        if not keep_travel_cache:
            tables.append("travel_cache")
        removed = {t: self.conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                   for t in tables}
        for table in tables:
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.execute("DELETE FROM sqlite_sequence WHERE name IN "
                          "('run','listing_version','score')")
        self.conn.commit()
        self.conn.execute("VACUUM")
        return removed

    @staticmethod
    def _row(r) -> dict[str, Any]:
        d = dict(r)
        d["attrs"] = json.loads(d.pop("attrs_json") or "{}")
        d["reasons"] = json.loads(d.pop("reasons_json") or "[]")
        d["photos"] = json.loads(d.pop("photos_json") or "[]")
        return d
