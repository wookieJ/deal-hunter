"""Config loading. Settings are global; a profile is one search + scoring intent."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml


def _find_root() -> Path:
    """Locate the directory holding config/, data/ and reports/.

    Order matters so the tool works from a clone, from `pip install -e .`, and
    from a real wheel install where the package no longer sits next to config/.
    """
    override = os.environ.get("DEALHUNTER_HOME")
    if override:
        return Path(override).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[2]   # <repo>/src/dealhunter/config.py
    if (checkout / "config").is_dir():
        return checkout
    return Path.cwd()


ROOT = _find_root()


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    """Load settings.yml, then overlay the gitignored settings.local.yml.

    The local file is where personal details live - a home address must never be
    committed to a public repository, so the tracked file only carries a
    placeholder and the real value stays on this machine.
    """
    settings = _load(Path(path) if path else ROOT / "config" / "settings.yml")
    local = ROOT / "config" / "settings.local.yml"
    if path is None and local.exists():
        with local.open(encoding="utf-8") as fh:
            settings = _deep_merge(settings, yaml.safe_load(fh) or {})
    return settings


def load_profile(name: str, use_local: bool = True) -> dict[str, Any]:
    """Load a profile, then overlay its gitignored `<name>.local.yml` sibling.

    A profile encodes personal things - your body measurements, your budget, the
    city you shop in - so the tracked file is a generic example and the real
    values stay on this machine, exactly like settings.local.yml.
    """
    path = Path(name)
    if not path.suffix:
        path = ROOT / "config" / "profiles" / f"{name}.yml"
    profile = _load(path)

    # Tests pass use_local=False: a suite whose expectations depend on a
    # gitignored personal file passes here and fails in CI, or vice versa.
    local = path.with_name(f"{path.stem}.local.yml")
    if use_local and local.exists():
        with local.open(encoding="utf-8") as fh:
            profile = _deep_merge(profile, yaml.safe_load(fh) or {})

    profile.setdefault("name", path.stem)
    return profile


def list_profiles_with_overrides() -> list[tuple[str, bool]]:
    directory = ROOT / "config" / "profiles"
    return [(p.stem, (directory / f"{p.stem}.local.yml").exists())
            for p in sorted(directory.glob("*.yml")) if not p.stem.endswith(".local")]


def list_profiles() -> list[str]:
    return sorted(p.stem for p in (ROOT / "config" / "profiles").glob("*.yml")
                  if not p.stem.endswith(".local"))


def resolve(path: str | Path) -> Path:
    """Resolve a settings-relative path against the project root."""
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def profile_fingerprint(profile: dict[str, Any]) -> str:
    """Identity of the scoring rules, so stored scores can be invalidated when the
    profile changes. Without this, offers that fall out of the search window keep
    scores computed under rules that no longer apply - and quietly pollute the
    ranking with numbers that cannot be reproduced."""
    relevant = {k: profile.get(k) for k in ("category", "preferences", "weights", "bonuses")}
    blob = json.dumps(relevant, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def resolve_location_anchor(profile: dict[str, Any], settings: dict[str, Any],
                            spec: dict[str, Any]) -> None:
    """Reconcile the two distinct locations this tool deals with.

    * The **search area** (a search parameter) is where offers are hunted.
    * **Home** (a setting) is where the user lives, and only ever drives the
      travel distances shown in reports.

    They are not the same thing - you can hunt in another city - so proximity
    scoring has to be told which one it measures against. The resolved anchor
    lands inside `preferences`, so it is part of the profile fingerprint and a
    change to it correctly invalidates stored scores.
    """
    prefs = profile.setdefault("preferences", {}).setdefault("location", {})
    default_radius = prefs.get("preferred_radius_km", 100)
    area = spec.get("area") or {}
    home = settings.get("home") or {}

    if prefs.get("proximity_to", "search_area") == "home" and home.get("lat") is not None:
        prefs["anchor"] = {"name": home.get("name", "dom"), "lat": home["lat"],
                           "lon": home["lon"], "radius_km": default_radius}
    elif area.get("lat") is not None:
        prefs["anchor"] = {"name": area.get("name", "obszar wyszukiwania"),
                           "lat": area["lat"], "lon": area["lon"],
                           "radius_km": area.get("radius_km", default_radius)}
    else:
        prefs["anchor"] = {}
