"""Command line entry point."""
from __future__ import annotations

import argparse
import sys

from . import config, pipeline
from .report import console
from .storage.db import connect
from .storage.repo import Repo
from .travel import TravelEstimator


def _open_repo(settings):
    return Repo(connect(config.resolve(settings["storage"]["db_path"])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deal", description="Local marketplace deal hunter")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="search the source and update the database")
    run.add_argument("-p", "--profile", default="gravel")
    run.add_argument("-l", "--limit", type=int, help="stop after N offers (for testing)")
    run.add_argument("--no-report", action="store_true", help="skip the HTML report")
    run.add_argument("-q", "--quiet", action="store_true")

    top = sub.add_parser("top", help="show the best stored offers (no fetching)")
    top.add_argument("-p", "--profile", default="gravel")
    top.add_argument("-n", "--limit", type=int, default=15)
    top.add_argument("--all", action="store_true", help="include rejected offers")

    hist = sub.add_parser("history", help="price history of a single offer")
    hist.add_argument("uid", help='e.g. "olx:1089311360"')

    rescore = sub.add_parser(
        "rescore", help="recompute stored scores against the current profile (offline)")
    rescore.add_argument("-p", "--profile", default="gravel")

    reset = sub.add_parser("reset", help="wipe the collected offers")
    reset.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    reset.add_argument("--all", action="store_true",
                       help="also drop the driving-distance cache")

    sub.add_parser("profiles", help="list the available profiles")

    args = parser.parse_args(argv)
    settings = config.load_settings()

    if args.command == "run":
        pipeline.run(args.profile, settings, limit=args.limit,
                     make_report=not args.no_report, quiet=args.quiet)
    elif args.command == "top":
        repo = _open_repo(settings)
        rows = repo.top(args.profile, args.limit, include_disqualified=args.all)
        TravelEstimator(repo.conn, settings, settings.get("home")).annotate(rows)
        console.offers(rows, f"Best offers ({args.profile})")
    elif args.command == "history":
        repo = _open_repo(settings)
        rows = repo.price_history(args.uid)
        if not rows:
            print(f"No history for {args.uid}")
            return 1
        print(f"Price history for {args.uid}:")
        previous = None
        for row in rows:
            price = row["price"]
            delta = f"  ({price - previous:+.0f} PLN)" if previous and price else ""
            print(f"  {row['seen_at']}  {price:.0f} PLN{delta}" if price
                  else f"  {row['seen_at']}  no price")
            previous = price
    elif args.command == "rescore":
        repo = _open_repo(settings)
        profile = config.load_profile(args.profile)
        count = pipeline.rescore(repo, profile, settings)
        print(f"Rescored {count} offers." if count else "All scores are up to date.")
    elif args.command == "reset":
        repo = _open_repo(settings)
        counts = {t: repo.conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                  for t in ("listing", "run")}
        print(f"About to delete: {counts['listing']} offers from {counts['run']} runs.")
        if not args.all:
            print("The driving-distance cache will be kept (--all drops it too).")
        if not args.yes and input("Are you sure? [y/N] ").strip().lower() not in ("y", "t"):
            print("Cancelled.")
            return 1
        removed = repo.clear(keep_travel_cache=not args.all)
        for table, count in removed.items():
            print(f"  deleted {count:>5} from {table}")
        print("Database cleared.")
    elif args.command == "profiles":
        for name in config.list_profiles():
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
