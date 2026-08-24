"""Self-contained HTML report - thumbnails make bike triage a 3-second decision."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    autoescape=select_autoescape(["html"]),
)


def _size_label(attrs: dict[str, Any]) -> str:
    if attrs.get("frame_size_cm"):
        return f"frame {attrs['frame_size_cm']} cm"
    if attrs.get("frame_size_letter"):
        return f"frame {attrs['frame_size_letter']}"
    return attrs.get("frame_size_raw") or "size ?"


def _prepare(*groups: list[dict]) -> None:
    for group in groups:
        for offer in group:
            offer["size_label"] = _size_label(offer.get("attrs", {}))


def render(path: Path, profile: str, source: str, stats: dict[str, Any],
           new: list[dict], changed: list[dict], top: list[dict]) -> Path:
    """Single-profile report."""
    _prepare(new, changed, top)
    html = _ENV.get_template("template.html.j2").render(
        profile=profile, source=source, stats=stats, new=new, changed=changed, top=top,
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def render_tabs(path: Path, tabs: list[dict[str, Any]]) -> Path:
    """One report, one tab per search - so several profiles share a single link."""
    for tab in tabs:
        _prepare(tab.get("new", []), tab.get("changed", []), tab.get("top", []))
    html = _ENV.get_template("tabs.html.j2").render(
        tabs=tabs, generated=datetime.now().strftime("%Y-%m-%d %H:%M"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
