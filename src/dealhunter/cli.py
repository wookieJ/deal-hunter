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
        prog="dealhunter", description="Lokalny deal hunter - OLX / rowery")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="przeszukaj zrodlo i zaktualizuje baze")
    run.add_argument("-p", "--profile", default="gravel")
    run.add_argument("-l", "--limit", type=int, help="zatrzymaj sie po N ofertach (do testow)")
    run.add_argument("--no-report", action="store_true", help="pomin raport HTML")
    run.add_argument("-q", "--quiet", action="store_true")

    top = sub.add_parser("top", help="pokaz najlepsze oferty z bazy (bez pobierania)")
    top.add_argument("-p", "--profile", default="gravel")
    top.add_argument("-n", "--limit", type=int, default=15)
    top.add_argument("--all", action="store_true", help="pokaz tez odrzucone")

    hist = sub.add_parser("history", help="historia ceny jednej oferty")
    hist.add_argument("uid", help='np. "olx:1089311360"')

    rescore = sub.add_parser(
        "rescore", help="przelicz zapisane oferty wg aktualnego profilu (offline, bez pobierania)")
    rescore.add_argument("-p", "--profile", default="gravel")

    reset = sub.add_parser("reset", help="wyczysc baze zebranych ofert")
    reset.add_argument("--yes", action="store_true", help="nie pytaj o potwierdzenie")
    reset.add_argument("--all", action="store_true",
                       help="usun rowniez cache odleglosci drogowych")

    sub.add_parser("profiles", help="lista dostepnych profili")

    args = parser.parse_args(argv)
    settings = config.load_settings()

    if args.command == "run":
        pipeline.run(args.profile, settings, limit=args.limit,
                     make_report=not args.no_report, quiet=args.quiet)
    elif args.command == "top":
        repo = _open_repo(settings)
        rows = repo.top(args.profile, args.limit, include_disqualified=args.all)
        TravelEstimator(repo.conn, settings, settings.get("home")).annotate(rows)
        console.offers(rows, f"Najlepsze oferty ({args.profile})")
    elif args.command == "history":
        repo = _open_repo(settings)
        rows = repo.price_history(args.uid)
        if not rows:
            print(f"Brak historii dla {args.uid}")
            return 1
        print(f"Historia ceny {args.uid}:")
        previous = None
        for row in rows:
            price = row["price"]
            delta = f"  ({price - previous:+.0f} zl)" if previous and price else ""
            print(f"  {row['seen_at']}  {price:.0f} zl{delta}" if price
                  else f"  {row['seen_at']}  cena n/d")
            previous = price
    elif args.command == "rescore":
        repo = _open_repo(settings)
        profile = config.load_profile(args.profile)
        count = pipeline.rescore(repo, profile, settings)
        print(f"Przeliczono {count} ofert." if count else "Wszystkie oceny sa aktualne.")
    elif args.command == "reset":
        repo = _open_repo(settings)
        counts = {t: repo.conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                  for t in ("listing", "run")}
        print(f"Do usuniecia: {counts['listing']} ofert z {counts['run']} przebiegow.")
        if not args.all:
            print("Cache odleglosci drogowych zostanie zachowany (--all usuwa rowniez jego).")
        if not args.yes and input("Na pewno? [t/N] ").strip().lower() not in ("t", "y"):
            print("Anulowano.")
            return 1
        removed = repo.clear(keep_travel_cache=not args.all)
        for table, count in removed.items():
            print(f"  usunieto {count:>5} z {table}")
        print("Baza wyczyszczona.")
    elif args.command == "profiles":
        for name in config.list_profiles():
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
