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


def _prepare(*groups: list[dict]) -> None:
    """Display fields are attached upstream by report.display, which reads the
    domain's own `display:` block - the reporter stays product-agnostic."""


def render_tabs(path: Path, tabs: list[dict[str, Any]]) -> Path:
    """One report, one tab per search - so several profiles share a single link."""
    for tab in tabs:
        _prepare(tab.get("new", []), tab.get("changed", []), tab.get("top", []))
    html = _ENV.get_template("tabs.html.j2").render(
        tabs=tabs, generated=datetime.now().strftime("%Y-%m-%d %H:%M"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
