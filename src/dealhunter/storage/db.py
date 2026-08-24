"""SQLite schema.

The listing / listing_version split is the heart of the design: an offer is stored
once, but every time its content hash changes a new version row is appended. That
single mechanism gives deduplication, new-offer detection, price-change detection
and full price history at once.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile     TEXT NOT NULL,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    n_found     INTEGER DEFAULT 0,
    n_new       INTEGER DEFAULT 0,
    n_changed   INTEGER DEFAULT 0,
    n_seen      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS listing (
    uid           TEXT PRIMARY KEY,          -- "olx:1089311360"
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    location      TEXT,
    lat           REAL,
    lon           REAL,
    is_business   INTEGER DEFAULT 0,
    created_at    TEXT,                      -- as reported by the marketplace
    first_seen_at TEXT NOT NULL,             -- first time WE saw it
    last_seen_at  TEXT NOT NULL,
    is_active     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS listing_version (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uid          TEXT NOT NULL REFERENCES listing(uid) ON DELETE CASCADE,
    run_id       INTEGER REFERENCES run(id),
    seen_at      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    price        REAL,
    currency     TEXT,
    title        TEXT,
    description  TEXT,
    photos_json  TEXT,
    raw_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_version_uid ON listing_version(uid, seen_at DESC);

CREATE TABLE IF NOT EXISTS listing_attrs (
    uid         TEXT PRIMARY KEY REFERENCES listing(uid) ON DELETE CASCADE,
    category    TEXT,
    attrs_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS score (
    uid          TEXT NOT NULL REFERENCES listing(uid) ON DELETE CASCADE,
    profile      TEXT NOT NULL,
    value        INTEGER NOT NULL,
    verdict      TEXT,
    reasons_json TEXT,
    disqualified INTEGER DEFAULT 0,
    profile_hash TEXT,
    scored_at    TEXT NOT NULL,
    PRIMARY KEY (uid, profile)
);
CREATE INDEX IF NOT EXISTS idx_score_profile ON score(profile, value DESC);

-- Driving distances are cached on a coarse coordinate grid, because many offers
-- share a city and the routing service is a free public one we should not hammer.
CREATE TABLE IF NOT EXISTS travel_cache (
    key        TEXT PRIMARY KEY,      -- "52.41,16.93|51.24,22.55"
    km         REAL,
    minutes    REAL,
    fetched_at TEXT NOT NULL
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations. CREATE TABLE IF NOT EXISTS never adds columns to an
    existing database, so new columns have to be applied explicitly."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(listing)")}
    for column, ddl in (("lat", "ALTER TABLE listing ADD COLUMN lat REAL"),
                        ("lon", "ALTER TABLE listing ADD COLUMN lon REAL")):
        if column not in columns:
            conn.execute(ddl)
    score_columns = {r["name"] for r in conn.execute("PRAGMA table_info(score)")}
    if "profile_hash" not in score_columns:
        conn.execute("ALTER TABLE score ADD COLUMN profile_hash TEXT")
    conn.commit()


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    _migrate(conn)
    conn.commit()
    return conn
