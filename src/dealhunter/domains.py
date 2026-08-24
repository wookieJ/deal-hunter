"""Domain packs: everything that knows about a particular kind of product.

The engine (scraping, storage, change detection, reporting, the scoring maths)
knows nothing about bikes. What a bike *is* - how to read a frame size out of a
Polish sentence, which groupsets are better than which - lives in a domain pack
under domains/<name>/:

    domains/bikes/
        domain.yml          extraction rules + scoring dimensions + value model
        lookups/*.yml       reference tables (model generation -> real specs)
        hooks.py            optional Python, for what YAML cannot express

Adding a product type means adding a directory here, not editing the engine.
YAML covers the common cases; hooks.py is the escape hatch, registering custom
extractor or dimension types by name so the YAML can refer to them.
"""
from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml

from . import config

# Custom types a domain's hooks.py may register, keyed by domain then type name.
EXTRACTORS: dict[str, dict[str, Callable]] = {}
DIMENSIONS: dict[str, dict[str, Callable]] = {}


def root(name: str) -> Path:
    return config.ROOT / "domains" / name


def available() -> list[str]:
    directory = config.ROOT / "domains"
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir()
                  if p.is_dir() and (p / "domain.yml").exists())


def register_extractor(domain: str, name: str) -> Callable:
    """Decorator used inside a domain's hooks.py to add a custom extractor type."""
    def wrap(fn: Callable) -> Callable:
        EXTRACTORS.setdefault(domain, {})[name] = fn
        return fn
    return wrap


def register_dimension(domain: str, name: str) -> Callable:
    """Decorator used inside a domain's hooks.py to add a custom scoring dimension."""
    def wrap(fn: Callable) -> Callable:
        DIMENSIONS.setdefault(domain, {})[name] = fn
        return fn
    return wrap


@lru_cache(maxsize=8)
def load(name: str) -> dict[str, Any]:
    """Load a domain pack: its YAML rules, plus hooks.py if it has one."""
    path = root(name) / "domain.yml"
    if not path.exists():
        known = ", ".join(available()) or "none"
        raise ValueError(f"Unknown domain {name!r}. Available: {known}")
    with path.open(encoding="utf-8") as fh:
        spec = yaml.safe_load(fh) or {}
    spec["_root"] = root(name)
    _load_hooks(name)
    return spec


def _load_hooks(name: str) -> None:
    hooks = root(name) / "hooks.py"
    if not hooks.exists():
        return
    module_name = f"dealhunter_domain_{name}"
    spec = importlib.util.spec_from_file_location(module_name, hooks)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


def extractor(domain: str, type_name: str) -> Callable | None:
    return EXTRACTORS.get(domain, {}).get(type_name)


def dimension(domain: str, type_name: str) -> Callable | None:
    return DIMENSIONS.get(domain, {}).get(type_name)
