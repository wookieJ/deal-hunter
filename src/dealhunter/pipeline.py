"""Orchestration: fetch -> normalise -> (enrich) -> score -> persist -> diff -> report.

The enrich step is intentionally an empty list in the MVP: adding an LLM or image
analyser later means appending to ENRICHERS, not restructuring this function.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import config, domains
from .models import Attributes, RawListing
from .normalize.base import get_normalizer
from .report import console, display, html
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
    domain = profile.get("domain")
    source_name, spec = prepare(profile, settings)

    source = get_source(source_name, settings)
    normalizer = get_normalizer(domain)
    scorer = get_scorer(domain)
    fingerprint = config.profile_fingerprint(profile)

    conn = connect(config.resolve(settings["storage"]["db_path"]))
    repo = Repo(conn)
    run_id = repo.start_run(profile["name"], source_name)
    first_run = repo.is_first_run(profile["name"])

    if not quiet:
        print(f"Searching: '{profile['name']}' on {source_name} "
              f"(category {spec.get('category_id')}, up to {spec.get('max_pages', 3)} pages)...")

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

        repo.save_attrs(raw.uid, domain, attrs)
        repo.save_score(raw.uid, profile["name"], result, fingerprint)

        if status == "new":
            new_uids.append(raw.uid)
        elif status == "changed":
            changed_items.append({"uid": raw.uid, "title": raw.title,
                                  "url": raw.url, "changes": changes})
        if not quiet and stats["found"] % 40 == 0:
            print(f"  ...{stats['found']} offers")
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
    for group in (new_offers, changed_offers, best):
        display.annotate(group, domain)

    # Travel distance is always measured from where the user lives, which is a
    # setting - never from the profile's search area.
    TravelEstimator(conn, settings, settings.get("home")).annotate(
        new_offers, changed_offers, best)

    stats.update(profile=profile["name"], source=source_name,
                 elapsed=time.monotonic() - started, first_run=first_run)

    if not quiet:
        console.summary(stats)
        if first_run:
            print("\n  (first run for this profile - everything is new)")
        console.changes(changed_items)
        if not first_run:
            console.offers(new_offers, "New offers - most interesting")
        console.offers(best, "Best offers in the database")

    if make_report:
        report_cfg = settings.get("report", {})
        report_dir = config.resolve(report_cfg["dir"])
        # One stable path, always overwritten: a new filename per run cannot be
        # bookmarked and just accumulates copies of a view that is only ever
        # interesting in its latest state.
        path = html.render(report_dir / f"{profile['name']}_latest.html",
                           profile["name"], source_name, stats,
                           new_offers, changed_offers, best)
        if report_cfg.get("keep_dated_copies"):
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
            archive = report_dir / f"{profile['name']}_{stamp}.html"
            archive.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        index = build_index(repo, settings, report_dir,
                            current={"name": profile["name"], "stats": stats,
                                     "new": new_offers, "changed": changed_offers})
        stats["report_path"] = index
        if not quiet:
            print(f"\nHTML report: {index}")

    conn.close()
    return stats


def build_index(repo: Repo, settings: dict[str, Any], report_dir: Path,
                current: dict[str, Any] | None = None) -> Path:
    """One report with a tab per search, so every profile shares a single link."""
    top_n = settings.get("report", {}).get("top_n", 15)
    travel = TravelEstimator(repo.conn, settings, settings.get("home"))

    tabs: list[dict[str, Any]] = []
    for row in repo.profiles_with_data():
        name = row["profile"]
        is_current = bool(current and current["name"] == name)
        stats = dict(row)
        if is_current:
            stats.update(current["stats"])
        top = repo.top(name, limit=top_n)
        new = current["new"] if is_current else []
        changed = current["changed"] if is_current else []
        travel.annotate(top, new, changed)
        try:
            tab_domain = config.load_profile(name).get("domain")
        except FileNotFoundError:
            tab_domain = None        # a profile whose file was deleted still has stored offers
        for group in (top, new, changed):
            display.annotate(group, tab_domain)
        tabs.append({"name": name, "source": row["source"] or "olx", "stats": stats,
                     "last_run": row["last_run"], "top": top, "new": new, "changed": changed})

    # Keep the freshly run search first, then the rest alphabetically.
    tabs.sort(key=lambda t: (not (current and t["name"] == current["name"]), t["name"]))
    return html.render_tabs(report_dir / "index.html", tabs)


def prepare(profile: dict[str, Any], settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Normalise one search file into what the engine expects.

    Every search file has the same shape - name, source, search, budget, scoring -
    with no product-specific fields, so nothing has to be mapped per domain. This
    flattens it, folds in the optional domain's defaults, and reconciles the
    search area with the user's home.
    """
    pack = domains.load(profile.get("domain"))
    scoring = profile.setdefault("scoring", {})

    prefs = config.deep_merge((pack.get("profile_schema") or {}).get("defaults") or {},
                              profile.get("preferences") or {})
    prefs["budget"] = profile.get("budget") or prefs.get("budget") or {}
    prefs["rules"] = list(scoring.get("rules") or [])
    prefs["disqualifying"] = list(scoring.get("disqualifying") or prefs.get("disqualifying") or [])
    prefs["required"] = list(scoring.get("required") or prefs.get("required") or [])
    prefs["penalties"] = scoring.get("penalties") or prefs.get("penalties") or {}
    profile["preferences"] = prefs

    scoring["weights"] = config.deep_merge(pack.get("default_weights") or {},
                                           scoring.get("weights") or {})

    source_name = profile.get("source", "olx")
    spec = dict(profile.get("search") or {})
    price = spec.pop("price", None) or {}
    if price.get("from") is not None:
        spec["price_from"] = price["from"]
    if price.get("to") is not None:
        spec["price_to"] = price["to"]

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

    domain = profile.get("domain")
    normalizer = get_normalizer(domain)
    scorer = get_scorer(domain)
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
        repo.save_attrs(raw.uid, domain, attrs)
        repo.save_score(raw.uid, profile["name"], scorer.score(attrs, raw, profile), fingerprint)
        repo.update_coordinates(raw.uid, raw.lat, raw.lon)

    repo.commit()
    if not quiet:
        print(f"  rescored {len(stale)} offers against the current profile")
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
