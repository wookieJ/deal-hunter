"""Orchestration: fetch -> normalise -> (enrich) -> score -> persist -> diff -> report.

The enrich step is intentionally an empty list in the MVP: adding an LLM or image
analyser later means appending to ENRICHERS, not restructuring this function.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import config
from .models import Attributes, RawListing
from .normalize.base import get_normalizer
from .report import console, html
from .scoring.base import get_scorer
from .sources.base import get_source
from .sources.olx import archive_raw
from .storage.db import connect
from .storage.repo import Repo
from .travel import TravelEstimator

# Enrichers run after the regex normalizer and may add/refine attribute keys.
ENRICHERS: list[Callable[[Attributes, RawListing], Attributes]] = []


def run(profile_name: str, settings: dict[str, Any], *, limit: int | None = None,
        make_report: bool = True, quiet: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    profile = config.load_profile(profile_name)
    category = profile.get("category", "bikes")
    source_name, spec = prepare(profile, settings)

    source = get_source(source_name, settings)
    normalizer = get_normalizer(category)
    scorer = get_scorer(category)
    fingerprint = config.profile_fingerprint(profile)

    conn = connect(config.resolve(settings["storage"]["db_path"]))
    repo = Repo(conn)
    run_id = repo.start_run(profile["name"], source_name)
    first_run = repo.is_first_run(profile["name"])

    if not quiet:
        print(f"Szukam: profil '{profile['name']}' w {source_name} "
              f"(kategoria {spec['category_id']}, do {spec.get('max_pages', 3)} stron)...")

    fetched: list[RawListing] = []
    stats = {"found": 0, "new": 0, "changed": 0, "seen": 0, "disqualified": 0}
    new_uids: list[str] = []
    changed_items: list[dict[str, Any]] = []

    for raw in source.search(spec):
        fetched.append(raw)
        stats["found"] += 1

        status, changes = repo.upsert(raw, run_id)
        stats[status] += 1

        attrs = normalizer.normalize(raw)
        for enrich in ENRICHERS:
            attrs = enrich(attrs, raw)
        result = scorer.score(attrs, raw, profile)
        if result.disqualified:
            stats["disqualified"] += 1

        repo.save_attrs(raw.uid, category, attrs)
        repo.save_score(raw.uid, profile["name"], result, fingerprint)

        if status == "new":
            new_uids.append(raw.uid)
        elif status == "changed":
            changed_items.append({"uid": raw.uid, "title": raw.title,
                                  "url": raw.url, "changes": changes})
        if not quiet and stats["found"] % 40 == 0:
            print(f"  ...{stats['found']} ofert")
        if limit and stats["found"] >= limit:
            break

    # Offers that dropped out of the search window still carry scores from whatever
    # rules were current when they were last seen. Rebuild them from the archived
    # payloads so the ranking never mixes scoring models.
    stats["rescored"] = rescore(repo, profile, settings, quiet=quiet)

    repo.commit()
    repo.finish_run(run_id, stats["found"], stats["new"], stats["changed"], stats["seen"])

    if settings.get("storage", {}).get("keep_raw_payloads") and fetched:
        archive_raw(fetched, run_id, config.resolve("data/raw"))

    top_n = settings.get("report", {}).get("top_n", 15)
    new_offers = repo.top(profile["name"], limit=top_n, uids=new_uids)
    changed_offers = _attach_changes(repo, profile["name"], changed_items)
    best = repo.top(profile["name"], limit=top_n)

    # Travel distance is always measured from where the user lives, which is a
    # setting - never from the profile's search area.
    TravelEstimator(conn, settings, settings.get("home")).annotate(
        new_offers, changed_offers, best)

    stats.update(profile=profile["name"], source=source_name,
                 elapsed=time.monotonic() - started, first_run=first_run)

    if not quiet:
        console.summary(stats)
        if first_run:
            print("\n  (pierwsze uruchomienie tego profilu - wszystko jest nowe)")
        console.changes(changed_items)
        if not first_run:
            console.offers(new_offers, "Nowe oferty - najciekawsze")
        console.offers(best, "Najlepsze oferty w bazie")

    if make_report:
        report_dir = config.resolve(settings["report"]["dir"])
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = html.render(report_dir / f"{profile['name']}_{stamp}.html",
                           profile["name"], source_name, stats,
                           new_offers, changed_offers, best)
        latest = report_dir / f"{profile['name']}_latest.html"
        latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        stats["report_path"] = path
        if not quiet:
            print(f"\nRaport HTML: {path}")

    conn.close()
    return stats


def prepare(profile: dict[str, Any], settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Resolve the search spec and reconcile the two locations before scoring."""
    source_name = next(iter(profile["search"]))
    spec = profile["search"][source_name]
    config.resolve_location_anchor(profile, settings, spec)
    return source_name, spec


def rescore(repo: Repo, profile: dict[str, Any], settings: dict[str, Any],
            quiet: bool = False) -> int:
    """Recompute stored scores that were produced by a different profile version.

    Runs entirely offline against archived payloads - no marketplace requests.
    """
    prepare(profile, settings)
    fingerprint = config.profile_fingerprint(profile)
    stale = repo.stale(profile["name"], fingerprint)
    if not stale:
        return 0

    category = profile.get("category", "bikes")
    normalizer = get_normalizer(category)
    scorer = get_scorer(category)
    sources: dict[str, Any] = {}

    for item in stale:
        source = sources.get(item["source"])
        if source is None:
            source = sources[item["source"]] = get_source(item["source"], settings)
        try:
            raw = source.parse(item["payload"])
        except (KeyError, TypeError, ValueError):
            continue
        attrs = normalizer.normalize(raw)
        for enrich in ENRICHERS:
            attrs = enrich(attrs, raw)
        repo.save_attrs(raw.uid, category, attrs)
        repo.save_score(raw.uid, profile["name"], scorer.score(attrs, raw, profile), fingerprint)
        repo.update_coordinates(raw.uid, raw.lat, raw.lon)

    repo.commit()
    if not quiet:
        print(f"  przeliczono {len(stale)} ofert wg aktualnego profilu")
    return len(stale)


def _attach_changes(repo: Repo, profile: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge change descriptions into the scored offer rows for the report."""
    if not items:
        return []
    by_uid = {i["uid"]: i["changes"] for i in items}
    rows = repo.top(profile, limit=len(items), uids=list(by_uid))
    for row in rows:
        row["changes"] = by_uid.get(row["uid"], [])
    return rows
