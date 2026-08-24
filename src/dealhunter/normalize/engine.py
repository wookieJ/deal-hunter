"""Config-driven extraction: free text -> structured attributes.

This module contains no knowledge of any product. It executes extraction rules
declared by a domain pack (domains/<name>/domain.yml), so supporting a new kind
of product is a YAML file, not a code change. A domain that needs something the
declarative types cannot express registers a custom type in its hooks.py.

Extractor types
---------------
patterns          ordered regexes -> first matching label
dictionary        a list of names matched as words, title preferred
tiered            ordered regexes -> label plus a 0-100 quality tier
numeric           regexes capturing a number, with range validation, an optional
                  unit conversion fallback and marketplace-bucket fallback
enum_regex        a regex capturing one token from a closed set
regex_value       a single regex whose first group is the value
year              all four-digit years in range, newest wins
param             straight from a marketplace-supplied parameter
model_after_brand the words following a recognised brand in the title
lookup            a reference table: brand + model + variant -> known specs
"""
from __future__ import annotations

import re
from typing import Any, Callable

from .. import domains
from ..models import Attributes, RawListing
from .lookup import resolve as lookup_resolve


# Every marketplace offer has these regardless of what is being sold, so the
# engine reads them itself. This is knowledge of the source, not of the product.
# See scoring.engine.DEFAULT_NEGATION - the same guard, for the same reason.
from ..scoring.engine import DEFAULT_NEGATION

UNIVERSAL_EXTRACT = [
    {"key": "condition", "type": "param", "param": "state"},
]


class Engine:
    """Runs a domain's extraction rules over a listing. The domain is optional."""

    def __init__(self, domain: str | None):
        self.domain = domain
        self.spec = domains.load(domain)
        self.category = self.spec.get("name", domain)
        self._negation = re.compile(self.spec.get("negation") or DEFAULT_NEGATION)
        self._components = (re.compile(self.spec["component_context"])
                            if self.spec.get("component_context") else None)

    # ------------------------------------------------------------------ public
    def normalize(self, raw: RawListing) -> Attributes:
        text = raw.text
        title = raw.title.lower()
        params = {k: v.lower() for k, v in raw.params.items()}
        attrs: Attributes = {"is_business": raw.is_business}

        for rule in UNIVERSAL_EXTRACT + list(self.spec.get("extract") or []):
            handler = self._handler(rule["type"])
            handler(rule, attrs, text, title, params, raw)

        attrs["flags"] = self._flags(attrs, text)
        attrs["disqualifiers"] = self._disqualifiers(text, title)
        return attrs

    # ---------------------------------------------------------------- dispatch
    def _handler(self, type_name: str) -> Callable:
        custom = domains.extractor(self.domain, type_name)
        if custom:
            return lambda rule, attrs, text, title, params, raw: attrs.update(
                custom(rule, attrs, text, title, params, raw) or {})
        try:
            return getattr(self, f"_x_{type_name}")
        except AttributeError:
            raise ValueError(
                f"Domain {self.domain!r}: unknown extractor type {type_name!r}. "
                f"Declare it in domains/{self.domain}/hooks.py to add your own."
            ) from None

    # --------------------------------------------------------------- utilities
    def _affirmative(self, text: str, pattern: str) -> bool:
        """True only where the pattern occurs somewhere that is not negated.

        Sellers advertise the absence of defects far more often than their
        presence, and reading "bez pęknięć ramy" as damage rejects the
        best-described offers - the worst possible failure for a deal hunter.
        """
        for m in re.finditer(pattern, text):
            if not self._negation.search(text[max(0, m.start() - 45):m.start()]):
                return True
        return False

    @staticmethod
    def _from_param(rule: dict, params: dict) -> str | None:
        name = rule.get("param")
        if not name or not params.get(name):
            return None
        value = params[name]
        if value in (rule.get("param_ignore") or []):
            return None
        mapping = rule.get("param_map")
        if mapping is not None:
            return mapping.get(value)
        return value

    def _set_raw(self, rule: dict, attrs: Attributes, value: str) -> None:
        key = rule.get("raw_key")
        if key and not attrs.get(key):
            attrs[key] = value.strip()

    # ------------------------------------------------------------- extractors
    def _x_patterns(self, rule, attrs, text, title, params, raw) -> None:
        from_param = self._from_param(rule, params)
        if from_param:
            attrs[rule["key"]] = from_param
            return

        values = rule["values"]
        # Explicit context wins: "carbon fork" must not be read as a carbon frame.
        context = rule.get("require_context")
        if context:
            for entry in values:
                explicit = (rf"{context}\w*\s+(?:\w+\s+){{0,2}}?(?:{entry['pattern']})"
                            rf"|(?:{entry['pattern']})\w*\s+{context}")
                if re.search(explicit, text):
                    attrs[rule["key"]] = entry["label"]
                    return
            if rule.get("explicit_extra") and re.search(rule["explicit_extra"], text):
                attrs[rule["key"]] = values[0]["label"]
                return

        for entry in values:
            if rule.get("exclude_near_components") and self._components:
                for m in re.finditer(entry["pattern"], text):
                    window = text[max(0, m.start() - 30):m.end() + 30]
                    if not self._components.search(window):
                        attrs[rule["key"]] = entry["label"]
                        return
            elif re.search(entry["pattern"], text):
                attrs[rule["key"]] = entry["label"]
                return
        attrs.setdefault(rule["key"], "")

    def _x_dictionary(self, rule, attrs, text, title, params, raw) -> None:
        from_param = self._from_param(rule, params)
        if from_param:
            attrs[rule["key"]] = from_param
            return
        haystacks = (title, text) if rule.get("prefer_title") else (text,)
        for haystack in haystacks:
            for name in rule["values"]:
                if re.search(rf"\b{re.escape(name)}\b", haystack):
                    attrs[rule["key"]] = name
                    return
        attrs[rule["key"]] = ""

    def _x_tiered(self, rule, attrs, text, title, params, raw) -> None:
        for entry in rule["values"]:
            if re.search(entry["pattern"], text):
                attrs[rule["key"]] = entry["label"]
                attrs[rule["tier_key"]] = entry["tier"]
                return
        attrs[rule["key"]] = ""
        attrs[rule["tier_key"]] = None

    def _x_numeric(self, rule, attrs, text, title, params, raw) -> None:
        key = rule["key"]
        attrs.setdefault(key, None)
        estimated_key = rule.get("estimated_key")
        if estimated_key:
            attrs.setdefault(estimated_key, False)

        for pattern in rule.get("patterns", []):
            m = re.search(pattern, text)
            if m and rule.get("min", 0) <= int(m.group(1)) <= rule.get("max", 10 ** 9):
                attrs[key] = int(m.group(1))
                self._set_raw(rule, attrs, m.group(0))
                return

        blockers = [attrs.get(k) for k in rule.get("fallback_requires_unset", [])]
        if any(blockers):
            return

        unit = rule.get("unit_fallback")
        if unit:
            m = re.search(unit["pattern"], text)
            if m:
                attrs[key] = round(int(m.group(1)) * unit["multiply"])
                if estimated_key:
                    attrs[estimated_key] = True
                self._set_raw(rule, attrs, m.group(0))
                return

        buckets = rule.get("param_buckets")
        if buckets and params.get(buckets["param"]):
            value = params[buckets["param"]]
            self._set_raw(rule, attrs, value)
            span = (buckets["map"] or {}).get(value)
            if span:
                attrs[key] = (span[0] + span[1]) // 2
                if estimated_key:
                    attrs[estimated_key] = True

    def _x_enum_regex(self, rule, attrs, text, title, params, raw) -> None:
        m = re.search(rule["pattern"], text)
        value = ""
        if m:
            value = m.group(1).upper() if rule.get("uppercase") else m.group(1)
            self._set_raw(rule, attrs, m.group(0))
        attrs[rule["key"]] = value

    def _x_regex_value(self, rule, attrs, text, title, params, raw) -> None:
        from_param = self._from_param(rule, params)
        if from_param:
            attrs[rule["key"]] = from_param.replace(rule.get("strip", ""), "") if rule.get("strip") \
                else from_param
            return
        m = re.search(rule["pattern"], text)
        attrs[rule["key"]] = m.group(1).replace(" ", "") if m else ""

    def _x_year(self, rule, attrs, text, title, params, raw) -> None:
        years = [int(y) for y in re.findall(rule["pattern"], text)
                 if rule["min"] <= int(y) <= rule["max"]]
        attrs[rule["key"]] = (max(years) if rule.get("pick", "max") == "max" else min(years)) \
            if years else None

    def _x_param(self, rule, attrs, text, title, params, raw) -> None:
        attrs[rule["key"]] = params.get(rule["param"], "")

    def _x_model_after_brand(self, rule, attrs, text, title, params, raw) -> None:
        brand = attrs.get(rule["brand_key"]) or ""
        attrs[rule["key"]] = ""
        if not brand:
            return
        m = re.search(rf"\b{re.escape(brand)}\b(.*)", raw.title, re.IGNORECASE)
        if not m:
            return
        stop = set(rule.get("stop_words", []))
        model: list[str] = []
        for token in re.findall(r"[A-Za-z0-9\-\.]+", m.group(1))[:rule.get("scan_tokens", 4)]:
            if token.lower() in stop or len(token) < 2:
                break
            model.append(token)
        attrs[rule["key"]] = " ".join(model[:rule.get("max_tokens", 3)])

    def _x_lookup(self, rule, attrs, text, title, params, raw) -> None:
        for target in rule["outputs"].values():
            attrs.setdefault(target, None)
        attrs.setdefault(rule["model_key"], "")
        attrs.setdefault(rule["confidence_key"], "")
        attrs.setdefault(rule["note_key"], "")

        found = lookup_resolve(
            table=rule["table"],
            domain=self.domain,
            brand=attrs.get(rule["brand_key"]) or "",
            title=raw.title,
            variant=attrs.get(rule["variant_key"]) or "",
            year=attrs.get(rule["year_key"]),
        )
        if not found:
            return
        for source, target in rule["outputs"].items():
            attrs[target] = found["values"].get(source)
        attrs[rule["model_key"]] = found["model"]
        attrs[rule["confidence_key"]] = found["confidence"]
        attrs[rule["note_key"]] = found["note"]

    # ------------------------------------------------------- flags & rejects
    def _flags(self, attrs: Attributes, text: str) -> list[str]:
        found = {name for name, pattern in (self.spec.get("flags") or {}).items()
                 if re.search(pattern, text)}
        for attr, mapping in (self.spec.get("flags_from_attr") or {}).items():
            flag = mapping.get(attrs.get(attr) or "")
            if flag:
                found.add(flag)
        return sorted(found)

    def _disqualifiers(self, text: str, title: str) -> list[str]:
        found = {name for name, pattern in (self.spec.get("disqualifiers") or {}).items()
                 if self._affirmative(text, pattern)}
        # Title-scoped rules: a word in a description often describes usage, not
        # category ("used it for fitness"), but in a title it names the product.
        found |= {name for name, pattern in (self.spec.get("title_disqualifiers") or {}).items()
                  if self._affirmative(title, pattern)}
        return sorted(found)
