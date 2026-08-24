"""Config-driven scoring.

Contains no knowledge of any product: it executes scoring dimensions declared by
a domain pack, weighted by a profile. Two principles shape the maths.

**Budget fit is a multiplier, not a dimension.** In a flat weighted sum, an
expensive well-specified item outranks a sensibly priced one purely on spec,
which is the opposite of what a deal hunter should do:

    final = spec_score x budget_fit + bonuses

**Unknown is not the same as bad.** A terse listing is not a worse product. If a
dimension cannot be determined, it is dropped from the weight normalisation
rather than scored low, so the result reflects what is known instead of how
talkative the seller was. This matters doubly because the extraction is regex
over inflected Polish: a missed pattern must cost nothing beyond uncertainty.
That uncertainty is reported separately, as a confidence figure, instead of
being smuggled into the score.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .. import domains
from ..models import Attributes, RawListing, ScoreResult

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class Result:
    """One dimension's outcome. `known` false means: we could not tell."""

    __slots__ = ("sub", "note", "known")

    def __init__(self, sub: float, note: str, known: bool = True):
        self.sub, self.note, self.known = sub, note, known


class Engine:
    def __init__(self, domain: str):
        self.domain = domain
        self.spec = domains.load(domain)
        self.category = self.spec.get("name", domain)

    # ------------------------------------------------------------------ public
    def score(self, attrs: Attributes, raw: RawListing, profile: dict[str, Any]) -> ScoreResult:
        prefs = profile.get("preferences", {})
        weights = profile.get("weights", {})
        bonuses = profile.get("bonuses", {})
        dimensions = {**(self.spec.get("dimensions") or {}),
                      **(profile.get("dimensions") or {})}

        blocked = self._disqualify(attrs, raw, prefs)
        if blocked:
            return ScoreResult(0, f"Rejected: {blocked}", [f"DISQUALIFIED: {blocked}"],
                               disqualified=True, disqualified_by=blocked)

        results: list[tuple[str, float, Result]] = []
        for name, weight in weights.items():
            config_for = dimensions.get(name)
            if not config_for or not weight:
                continue
            results.append((name, float(weight), self._run(config_for, attrs, raw, prefs)))

        known_weight = sum(w for _, w, r in results if r.known)
        total_weight = sum(w for _, w, _ in results) or 1
        # Renormalise over what we actually know, so silence costs certainty, not points.
        scale = 100.0 / known_weight if known_weight else 0.0

        reasons: list[str] = []
        spec_score = 0.0
        for name, weight, result in results:
            if result.known:
                points = result.sub * weight * scale
                spec_score += points
                reasons.append(f"{points:+.0f}/{weight * scale:.0f} {result.note}")
            else:
                reasons.append(f"?    {result.note}")

        confidence = known_weight / total_weight
        # Renormalising alone would let 22% of the weight decide 100% of the score,
        # so a near-empty listing could top the ranking - the mirror image of
        # punishing it. Instead, regress toward a neutral prior in proportion to
        # what we do not know: unknown means uncertain, not good and not bad.
        prior = float(self.spec.get("unknown_prior", 55))
        if confidence < 1.0:
            blended = spec_score * confidence + prior * (1 - confidence)
            reasons.append(f"confidence {confidence * 100:.0f}% "
                           f"({known_weight:.0f}/{total_weight:.0f} of weight known) "
                           f"-> {spec_score:.0f} blended toward {prior:.0f} = {blended:.0f}")
            spec_score = blended

        budget_fit, budget_note = self._budget_fit(raw, prefs)
        reasons.append(f"x{budget_fit:.2f} {budget_note}")

        extra, extra_reasons = self._extras(attrs, raw, prefs, bonuses)
        reasons.extend(extra_reasons)

        value = max(0, min(100, round(spec_score * budget_fit + extra)))
        return ScoreResult(value, self._verdict(value, attrs, raw, budget_fit, confidence), reasons)

    # ---------------------------------------------------------------- dispatch
    def _run(self, cfg: dict[str, Any], attrs: Attributes, raw: RawListing,
             prefs: dict[str, Any]) -> Result:
        custom = domains.dimension(self.domain, cfg["type"])
        if custom:
            return custom(cfg, attrs, raw, prefs)
        try:
            handler = getattr(self, f"_d_{cfg['type']}")
        except AttributeError:
            raise ValueError(
                f"Domain {self.domain!r}: unknown dimension type {cfg['type']!r}. "
                f"Declare it in domains/{self.domain}/hooks.py to add your own."
            ) from None
        return handler(cfg, attrs, raw, prefs)

    @staticmethod
    def _pref(prefs: dict[str, Any], path: str, default: Any = None) -> Any:
        """Read `a.b.c` out of the profile's preferences."""
        node: Any = prefs
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def _cfg(self, cfg: dict[str, Any], prefs: dict[str, Any], key: str, default: Any = None) -> Any:
        """A dimension setting, optionally redirected into the profile via `<key>_from`."""
        path = cfg.get(f"{key}_from")
        if path:
            return self._pref(prefs, path, default)
        return cfg.get(key, default)

    # -------------------------------------------------------------- dimensions
    def _d_tier(self, cfg, attrs, raw, prefs) -> Result:
        tier = attrs.get(cfg["attr"])
        label = attrs.get(cfg.get("label_attr", "")) or ""
        if tier is None:
            return Result(0.0, cfg.get("unknown_note", f"{cfg['attr']} not recognised"), known=False)
        sub = tier / 100.0
        for wanted in self._cfg(cfg, prefs, "preferred_contains", []) or []:
            if wanted.lower() in label.lower():
                return Result(min(1.0, sub + cfg.get("preferred_bonus", 0.0)),
                              f"{cfg['label']} {label} (preferred)")
        return Result(sub, f"{cfg['label']} {label}")

    def _d_preference_list(self, cfg, attrs, raw, prefs) -> Result:
        value = (attrs.get(cfg["attr"]) or "").lower()
        if not value:
            return Result(0.0, cfg.get("unknown_note", f"{cfg['label']} not recognised"), known=False)
        lower = lambda items: [str(i).lower() for i in (items or [])]
        if value in lower(self._cfg(cfg, prefs, "avoid", [])):
            return Result(0.0, f"{cfg['label']} {value} (avoided)")
        if value in lower(self._cfg(cfg, prefs, "preferred", [])):
            return Result(1.0, f"{cfg['label']} {value} (preferred)")
        return Result(cfg.get("known_score", 0.7), f"{cfg['label']} {value}")

    def _d_enum_map(self, cfg, attrs, raw, prefs) -> Result:
        value = (attrs.get(cfg["attr"]) or "").lower()
        if not value:
            return Result(0.0, cfg.get("unknown_note", f"{cfg['label']} unspecified"), known=False)
        labels = cfg.get("labels") or {}
        scores = cfg.get("scores") or {}
        return Result(scores.get(value, cfg.get("default_score", 0.65)),
                      f"{cfg['label']}: {labels.get(value, value)}")

    def _d_flag_coverage(self, cfg, attrs, raw, prefs) -> Result:
        flags = set(attrs.get("flags", []))
        weights = cfg["weights"]
        sub, have, miss, unknown = 0.0, [], [], 0.0

        for feature, weight in weights.items():
            negative = (cfg.get("negative") or {}).get(feature)
            if feature in flags:
                sub += weight
                have.append(feature)
            elif negative and attrs.get(negative["attr"]) in negative["values"]:
                miss.append(f"no {feature} ({attrs.get(negative['attr'])})")
            else:
                # Absence of evidence is not evidence of absence: a short listing
                # simply did not say, so this share of the dimension is unknown.
                unknown += weight

        total = sum(weights.values()) or 1
        if unknown >= total * cfg.get("unknown_threshold", 0.999):
            return Result(0.0, cfg.get("unknown_note", f"{cfg['label']}: nothing stated"),
                          known=False)

        known_total = total - unknown
        note = f"{cfg['label']}: " + (", ".join(have) if have else "none confirmed")
        if miss:
            note += " | " + ", ".join(miss)
        if unknown:
            note += f" | {unknown / total * 100:.0f}% not stated"
        return Result(min(1.0, sub / known_total) if known_total else 0.0, note)

    def _d_distance(self, cfg, attrs, raw, prefs) -> Result:
        anchor = self._pref(prefs, cfg.get("anchor_from", "location.anchor"), {}) or {}
        if not anchor or raw.lat is None or raw.lon is None:
            return Result(0.0, f"location: {raw.location or 'unknown'}", known=False)
        km = haversine_km(anchor["lat"], anchor["lon"], raw.lat, raw.lon)
        radius = anchor.get("radius_km", 100)
        name = anchor.get("name", "the search area")
        for multiplier, score, suffix in cfg.get("bands", []):
            if km <= radius * multiplier:
                label = f"{km:.0f} km from {name}"
                return Result(score, f"{label} ({suffix})" if suffix else label)
        return Result(cfg.get("far_score", 0.4), f"{km:.0f} km from {name} (shipping required)")

    def _d_range_chain(self, cfg, attrs, raw, prefs) -> Result:
        """Try each source in order; the first that yields a value wins.

        Sources are ordered most trustworthy first - a reference table beats the
        seller's own label - and each carries a confidence cap so a weaker source
        can never score as highly as a stronger one.
        """
        for source in cfg["sources"]:
            result = self._chain_source(source, cfg, attrs, prefs)
            if result:
                return result
        return Result(0.0, cfg.get("unknown_note", f"{cfg['label']} unknown"), known=False)

    def _chain_source(self, source, cfg, attrs, prefs) -> Result | None:
        value = attrs.get(source["attr"])
        if value in (None, ""):
            return None
        cap = source.get("cap", 1.0)
        estimated = source.get("estimated_attr") and attrs.get(source["estimated_attr"])
        if estimated:
            cap *= source.get("estimated_cap", 0.8)
        tag = " ~estimated" if estimated else ""

        if source["kind"] == "numeric_range":
            ideal = self._cfg(source, prefs, "ideal", [])
            acceptable = self._cfg(source, prefs, "acceptable", [])
            if ideal and ideal[0] <= value <= ideal[1]:
                sub, fit = 1.0, "ideal"
            elif acceptable and acceptable[0] <= value <= acceptable[1]:
                sub, fit = source.get("acceptable_score", 0.65), "acceptable"
            else:
                sub, fit = source.get("out_of_range_score", 0.2), "poor"
            note = f"{source['label']} {value}"

            companion = source.get("companion")
            if companion and attrs.get(companion["attr"]) is not None:
                other = attrs[companion["attr"]]
                note = (f"{source['label']} {attrs.get(source.get('name_attr'), '')}: "
                        f"{source['unit_label']} {value}/{companion['label']} {other} "
                        f"{companion.get('unit', '')}").replace("  ", " ")
                minimum = self._cfg(companion, prefs, "min", 0)
                if other >= minimum:
                    sub = min(1.0, sub + companion.get("bonus", 0.0))
                    fit += f", {companion['good_note']}"
                elif other < minimum - companion.get("tolerance", 0):
                    sub *= companion.get("penalty", 1.0)
                    fit += f", {companion['bad_note']}"
            note = f"{note} ({fit})"

            confidence = attrs.get(source.get("confidence_attr", ""), "")
            caveat = ""
            if confidence and confidence != "exact":
                cap *= source.get("confidence_caps", {}).get(confidence, 1.0)
                caveat = f" [{attrs.get(source.get('note_attr', ''), '')}]"
            return Result(sub * cap, f"{note}{caveat}")

        if source["kind"] == "value_set":
            preferred = [str(v) for v in (self._cfg(source, prefs, "preferred", []) or [])]
            acceptable = [str(v) for v in (self._cfg(source, prefs, "acceptable", []) or [])]
            text = str(value)
            if text in preferred:
                return Result(cap, f"{source['label']} {text} ({source['preferred_note']}{tag})")
            if text in acceptable:
                return Result(source.get("acceptable_score", 0.65) * cap,
                              f"{source['label']} {text} ({source['acceptable_note']})")
            return Result(source.get("out_of_range_score", 0.25) * cap,
                          f"{source['label']} {text} ({source['poor_note']})")
        return None

    # ------------------------------------------------------------ hard gates
    def _disqualify(self, attrs: Attributes, raw: RawListing, prefs: dict) -> str:
        hits = set(attrs.get("disqualifiers", [])) & set(prefs.get("disqualifying", []))
        if hits:
            return ", ".join(sorted(hits))

        hard_max = (prefs.get("budget") or {}).get("hard_max")
        if hard_max and raw.price and raw.price > hard_max:
            return f"price {raw.price:.0f} PLN above the {hard_max} PLN limit"

        # `required` is the deliberate exception to "unknown is not bad": if you
        # ask for it explicitly, an offer that never mentions it is rejected.
        missing = set(prefs.get("required", [])) - set(attrs.get("flags", []))
        if missing:
            return f"missing required: {', '.join(sorted(missing))}"

        for rule in self.spec.get("reject_rules", []):
            value = attrs.get(rule["attr"])
            if value in (None, ""):
                continue
            if rule.get("estimated_attr") and attrs.get(rule["estimated_attr"]):
                continue
            below = self._pref(prefs, rule["below_from"]) if rule.get("below_from") else rule.get("below")
            above = self._pref(prefs, rule["above_from"]) if rule.get("above_from") else rule.get("above")
            values = self._pref(prefs, rule["in_from"]) if rule.get("in_from") else rule.get("in")
            if below is not None and isinstance(value, (int, float)) and value <= below:
                return rule["message"].format(value=value)
            if above is not None and isinstance(value, (int, float)) and value >= above:
                return rule["message"].format(value=value)
            if values and str(value) in [str(v) for v in values]:
                return rule["message"].format(value=value)
        return ""

    # --------------------------------------------------------- price & extras
    @staticmethod
    def _budget_fit(raw: RawListing, prefs: dict) -> tuple[float, str]:
        b = prefs.get("budget") or {}
        comfortable = b.get("comfortable_max", 3500)
        soft, hard = b.get("soft_max", 4000), b.get("hard_max", 5500)
        floor = b.get("expensive_floor", 0.68)

        if raw.price is None:
            return 0.85, "price unknown"
        if raw.price <= comfortable:
            return 1.0, f"price {raw.price:.0f} PLN (within budget)"
        if raw.price <= soft:
            fit = 1.0 - 0.10 * (raw.price - comfortable) / max(soft - comfortable, 1)
            return fit, f"price {raw.price:.0f} PLN (slightly over budget)"
        fit = 0.90 - (0.90 - floor) * (raw.price - soft) / max(hard - soft, 1)
        return max(floor, fit), f"price {raw.price:.0f} PLN (must be clearly better)"

    def _extras(self, attrs: Attributes, raw: RawListing, prefs: dict,
                cfg: dict) -> tuple[float, list[str]]:
        from . import value as value_model
        total, reasons = 0.0, []

        points, note = value_model.bargain(raw.price, attrs, self.spec.get("value_model"))
        if note:
            total += points
            reasons.append(note)

        for model in prefs.get("preferred_models", []):
            if model.lower() in raw.title.lower():
                total += cfg.get("preferred_model", 0)
                reasons.append(f"+{cfg.get('preferred_model', 0)} reference model ({model})")
                break

        # Soft penalties: signals worth a nudge, not a rejection.
        for name, points in (prefs.get("penalties") or {}).items():
            if name in attrs.get("disqualifiers", []) or name in attrs.get("flags", []):
                total -= points
                reasons.append(f"-{points} {name}")

        target = (prefs.get("budget") or {}).get("target")
        if target and raw.price and raw.price <= target * 0.3:
            total -= 5
            reasons.append(f"-5 suspiciously cheap ({raw.price:.0f} PLN) - verify")

        if cfg.get("fresh_listing") and raw.created_at:
            try:
                posted = datetime.fromisoformat(raw.created_at)
                hours = (datetime.now(timezone.utc)
                         - posted.astimezone(timezone.utc)).total_seconds() / 3600
                if hours <= 48:
                    total += cfg["fresh_listing"]
                    reasons.append(f"+{cfg['fresh_listing']} fresh listing ({hours:.0f}h)")
            except ValueError:
                pass
        return total, reasons

    def _verdict(self, value: int, attrs: Attributes, raw: RawListing,
                 budget_fit: float, confidence: float) -> str:
        bands = self.spec.get("verdict_bands") or [
            [85, "Very good offer"], [70, "Good offer"], [55, "Average offer"], [0, "Weak offer"]]
        head = next(label for threshold, label in bands if value >= threshold)

        bits = []
        for rule in self.spec.get("verdict_notes", []):
            if attrs.get(rule["when_attr"]):
                bits.append(rule["text"].format(**{k: attrs.get(k, "") for k in rule.get("uses", [])}))
                break
        if not bits and self.spec.get("verdict_fallback"):
            bits.append(self.spec["verdict_fallback"])
        if raw.price:
            bits.append(f"price {raw.price:.0f} PLN")
        if budget_fit < 0.95:
            bits.append("above target budget")
        if confidence < 0.7:
            # Say it out loud rather than hiding a guess behind a confident number.
            bits.append(f"sparse listing - only {confidence * 100:.0f}% of criteria confirmed")
        return f"{head}. " + ", ".join(bits).capitalize() + "."
