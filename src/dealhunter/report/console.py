"""Terminal summary. No dependencies - plain ANSI."""
from __future__ import annotations

from typing import Any

R = "\033[0m"; B = "\033[1m"; DIM = "\033[2m"
GREEN = "\033[32m"; YELLOW = "\033[33m"; RED = "\033[31m"; CYAN = "\033[36m"; BLUE = "\033[34m"


def _distance(offer: dict[str, Any]) -> str:
    """Driving distance from home, marked when it is only an estimate."""
    km = offer.get("drive_km")
    if km is None:
        return ""
    minutes = offer.get("drive_min")
    label = f"~{km} km" if offer.get("drive_estimated") else f"{km} km"
    if minutes:
        label += f" / {minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f" / {minutes} min"
    return f"autem {label}"


def _colour(value: int) -> str:
    return GREEN if value >= 80 else YELLOW if value >= 60 else RED


def summary(stats: dict[str, Any]) -> None:
    print()
    print(f"{B}=== Podsumowanie ({stats['profile']} @ {stats['source']}) ==={R}")
    print(f"  znalezionych ofert : {B}{stats['found']}{R}")
    print(f"  juz znanych        : {stats['seen']}")
    print(f"  {GREEN}nowych             : {B}{stats['new']}{R}")
    changed_colour = CYAN if stats["changed"] else ""
    print(f"  {changed_colour}zmienionych        : {B}{stats['changed']}{R}")
    if stats.get("rescored"):
        print(f"  {DIM}przeliczonych      : {stats['rescored']} (zmiana profilu){R}")
    if stats.get("disqualified"):
        print(f"  {DIM}odrzuconych        : {stats['disqualified']}{R}")
    if stats.get("elapsed"):
        print(f"  {DIM}czas               : {stats['elapsed']:.1f}s{R}")


def changes(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    print(f"\n{B}{CYAN}--- Zmiany w znanych ofertach ---{R}")
    for it in items:
        print(f"  {it['title'][:60]}")
        for change in it["changes"]:
            print(f"    {YELLOW}{change}{R}")
        print(f"    {DIM}{it['url']}{R}")


def offers(items: list[dict[str, Any]], heading: str, show_reasons: bool = True) -> None:
    if not items:
        print(f"\n{DIM}(brak: {heading}){R}")
        return
    print(f"\n{B}--- {heading} ---{R}")
    for i, it in enumerate(items, 1):
        a = it.get("attrs", {})
        colour = _colour(it["value"])
        price = f"{it['price']:.0f} zl" if it.get("price") else "cena n/d"
        size = (f"{a['frame_size_cm']} cm" if a.get("frame_size_cm")
                else a.get("frame_size_letter") or a.get("frame_size_raw") or "rozmiar ?")

        print(f"\n{B}{i:2}. {it['title'][:70]}{R}")
        print(f"    {colour}{B}score {it['value']}/100{R}   {B}{price}{R}   {size}"
              f"   {a.get('groupset') or 'osprzet ?'}")
        meta = [it.get("location") or "", _distance(it),
                "firma" if it.get("is_business") else "prywatnie"]
        if a.get("brakes"):
            meta.append(a["brakes"])
        if a.get("frame_material"):
            meta.append(a["frame_material"])
        print(f"    {DIM}{' | '.join(filter(None, meta))}{R}")
        print(f"    {it.get('verdict', '')}")
        if show_reasons and it.get("reasons"):
            print(f"    {DIM}{' | '.join(it['reasons'])}{R}")
        print(f"    {BLUE}{it['url']}{R}")
