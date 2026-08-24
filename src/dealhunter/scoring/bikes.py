"""Value-oriented scoring for bike listings.

The scoring model is deliberately multiplicative rather than a flat weighted sum:

    final = spec_score x budget_fit + bargain_bonus

A flat sum lets an expensive, well-equipped bike outrank a sensibly priced one
purely on spec - which is the opposite of what a deal hunter should do. Making
budget fit a multiplier means a 5000 PLN bike keeps only ~75% of its spec score,
so it has to be genuinely exceptional to beat a good 3000 PLN bike, while still
appearing in the list if it really is that good.

Every dimension returns a 0.0-1.0 sub-score plus a human sentence, so the number
always arrives with the reasoning that produced it.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from ..models import Attributes, RawListing, ScoreResult
from . import value as value_model

CONDITION_SCORES = {
    "nowe": 1.0, "jak nowe": 0.95, "odnowione": 0.85,
    "używane": 0.75, "uzywane": 0.75, "uszkodzone": 0.15,
}

# OLX reports condition in Polish. The stored attribute keeps the source value;
# only the displayed label is translated.
CONDITION_LABELS = {
    "nowe": "new", "jak nowe": "as new", "odnowione": "refurbished",
    "używane": "used", "uzywane": "used", "uszkodzone": "damaged",
}

# Weight of each feature inside the "features" dimension. Unknown is not the same
# as absent: sparse descriptions get partial credit rather than a zero.
FEATURE_WEIGHTS = {"hydraulic_disc": 0.45, "carbon_fork": 0.25,
                   "through_axle": 0.20, "tubeless": 0.10}
UNKNOWN_FEATURE_CREDIT = 0.4

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class BikeScorer:
    category = "bikes"

    def score(self, attrs: Attributes, raw: RawListing, profile: dict[str, Any]) -> ScoreResult:
        prefs = profile.get("preferences", {})
        weights = profile.get("weights", {})
        bonuses = profile.get("bonuses", {})

        blocked = self._disqualify(attrs, raw, prefs)
        if blocked:
            return ScoreResult(0, f"Rejected: {blocked}", [f"DISQUALIFIED: {blocked}"],
                               disqualified=True, disqualified_by=blocked)

        parts = [
            ("size", *self._size(attrs, prefs)),
            ("groupset", *self._groupset(attrs, prefs)),
            ("features", *self._features(attrs, prefs)),
            ("condition", *self._condition(attrs)),
            ("location", *self._location(raw, prefs)),
            ("brand", *self._brand(attrs, prefs)),
        ]

        total_weight = sum(weights.get(dim, 0) for dim, _, _ in parts) or 1
        factor = 100.0 / total_weight

        reasons: list[str] = []
        spec_score = 0.0
        for dim, sub, note in parts:
            weight = weights.get(dim, 0)
            if not weight:
                continue
            points = sub * weight * factor
            spec_score += points
            reasons.append(f"{points:+.0f}/{weight * factor:.0f} {note}")

        budget_fit, budget_note = self._budget_fit(raw, prefs)
        reasons.append(f"x{budget_fit:.2f} {budget_note}")

        extra, extra_reasons = self._extras(attrs, raw, prefs, bonuses)
        reasons.extend(extra_reasons)

        final = max(0, min(100, round(spec_score * budget_fit + extra)))
        return ScoreResult(final, self._verdict(final, attrs, raw, budget_fit), reasons)

    # ------------------------------------------------------------ hard gates
    @staticmethod
    def _disqualify(attrs: Attributes, raw: RawListing, prefs: dict) -> str:
        hits = set(attrs.get("disqualifiers", [])) & set(prefs.get("disqualifying", []))
        if hits:
            return ", ".join(sorted(hits))

        hard_max = (prefs.get("budget") or {}).get("hard_max")
        if hard_max and raw.price and raw.price > hard_max:
            return f"price {raw.price:.0f} PLN above the {hard_max} PLN limit"

        missing = set(prefs.get("required", [])) - set(attrs.get("flags", []))
        if missing:
            return f"missing required: {', '.join(sorted(missing))}"

        # Obviously wrong sizes only. Anything arguable is scored down, not rejected,
        # because sizing is brand-dependent and the label is often unreliable.
        cfg = prefs.get("frame_size", {})
        reach = attrs.get("geo_reach")
        if reach and (reach < cfg.get("reject_reach_below", 0)
                      or reach > cfg.get("reject_reach_above", 9999)):
            return f"reach {reach} mm is clearly wrong"
        cm = attrs.get("frame_size_cm")
        if cm and not attrs.get("frame_size_estimated"):
            if cm <= cfg.get("reject_cm_below", 0) or cm >= cfg.get("reject_cm_above", 999):
                return f"size {cm} cm is clearly wrong"
        letter = attrs.get("frame_size_letter")
        if letter and letter in cfg.get("reject_letters", []):
            return f"size {letter} is clearly wrong"
        return ""

    # ------------------------------------------------------------ dimensions
    @staticmethod
    def _size(attrs: Attributes, prefs: dict) -> tuple[float, str]:
        """Geometry first, size label only as a fallback - and never at full confidence."""
        cfg = prefs.get("frame_size", {})
        reach, stack = attrs.get("geo_reach"), attrs.get("geo_stack")

        if reach:
            lo, hi = cfg.get("ideal_reach_mm", [402, 426])
            alo, ahi = cfg.get("acceptable_reach_mm", [390, 438])
            if lo <= reach <= hi:
                sub = 1.0
                fit = "ideal"
            elif alo <= reach <= ahi:
                sub = 0.65
                fit = "acceptable"
            else:
                sub = 0.2
                fit = "poor"

            min_stack = cfg.get("comfort_stack_mm", 600)
            if stack and stack >= min_stack:
                sub = min(1.0, sub + 0.05)
                fit += ", comfortable stack"
            elif stack and stack < min_stack - 25:
                sub *= 0.9
                fit += ", low stack"

            confidence = attrs.get("geo_confidence")
            caveat = ""
            if confidence == "ambiguous":
                sub *= 0.9          # geometry differs between generations
                caveat = f" [{attrs.get('geo_note')}]"
            elif confidence == "unverified":
                sub *= 0.85
                caveat = f" [{attrs.get('geo_note')}]"
            note = (f"geometry {attrs.get('geo_model')}: reach {reach}/stack {stack} mm "
                    f"({fit}){caveat}")
            return sub, note

        # Fallback: nominal size. Capped, because labels are not comparable
        # across brands - that is the whole reason the geometry table exists.
        cap = cfg.get("label_confidence_cap", 0.85)
        cm, letter = attrs.get("frame_size_cm"), attrs.get("frame_size_letter")
        estimated = attrs.get("frame_size_estimated")
        if estimated:
            cap *= 0.8

        if cm is not None:
            if cm in cfg.get("preferred_cm", []):
                return cap, f"size {cm} cm (fits per generic chart{' ~estimated' if estimated else ''})"
            if cm in cfg.get("acceptable_cm", []):
                return 0.65 * cap, f"size {cm} cm (acceptable per generic chart)"
            return 0.25 * cap, f"size {cm} cm (probably does not fit)"
        if letter:
            if letter in cfg.get("preferred_letter", []):
                return cap, f"size {letter} (fits per generic chart, no geometry data)"
            if letter in cfg.get("acceptable_letter", []):
                return 0.65 * cap, f"size {letter} (acceptable, no geometry data)"
            return 0.25 * cap, f"size {letter} (probably does not fit)"
        return 0.35, "size unknown (ask the seller)"

    @staticmethod
    def _groupset(attrs: Attributes, prefs: dict) -> tuple[float, str]:
        tier, name = attrs.get("groupset_tier"), attrs.get("groupset")
        if tier is None:
            return 0.45, "groupset not recognised"
        sub = tier / 100.0
        for wanted in prefs.get("preferred_groupsets", []):
            if wanted.lower() in (name or "").lower():
                sub = min(1.0, sub + 0.10)
                return sub, f"groupset {name} (preferred)"
        return sub, f"groupset {name}"

    @staticmethod
    def _features(attrs: Attributes, prefs: dict) -> tuple[float, str]:
        flags = set(attrs.get("flags", []))
        brakes = attrs.get("brakes") or ""
        sub, have, miss = 0.0, [], []
        for feature, weight in FEATURE_WEIGHTS.items():
            if feature in flags:
                sub += weight
                have.append(feature)
            elif feature == "hydraulic_disc" and brakes in ("rim", "mechanical_disc"):
                miss.append(f"no hydraulics ({brakes})")
            elif feature == "hydraulic_disc" and not brakes:
                sub += weight * UNKNOWN_FEATURE_CREDIT
            else:
                sub += weight * UNKNOWN_FEATURE_CREDIT * 0.5
        note = "features: " + (", ".join(have) if have else "none confirmed")
        if miss:
            note += " | " + ", ".join(miss)
        return min(1.0, sub), note

    @staticmethod
    def _condition(attrs: Attributes) -> tuple[float, str]:
        cond = (attrs.get("condition") or "").lower()
        if not cond:
            return 0.65, "condition unspecified"
        return CONDITION_SCORES.get(cond, 0.65), f"condition: {CONDITION_LABELS.get(cond, cond)}"

    @staticmethod
    def _location(raw: RawListing, prefs: dict) -> tuple[float, str]:
        anchor = (prefs.get("location") or {}).get("anchor") or {}
        if not anchor or raw.lat is None or raw.lon is None:
            return 0.6, f"location: {raw.location or 'unknown'}"
        km = haversine_km(anchor["lat"], anchor["lon"], raw.lat, raw.lon)
        radius = anchor.get("radius_km", 100)
        name = anchor.get("name", "obszaru")
        if km <= radius:
            return 1.0, f"{km:.0f} km from {name} (inside search area)"
        if km <= radius * 2:
            return 0.75, f"{km:.0f} km from {name}"
        if km <= radius * 3.5:
            return 0.55, f"{km:.0f} km from {name} (far)"
        return 0.4, f"{km:.0f} km from {name} (shipping required)"

    @staticmethod
    def _brand(attrs: Attributes, prefs: dict) -> tuple[float, str]:
        cfg = prefs.get("brands", {})
        brand = (attrs.get("brand") or "").lower()
        if not brand:
            return 0.5, "brand not recognised"
        if brand in [b.lower() for b in cfg.get("avoid", [])]:
            return 0.0, f"brand {brand} (avoided)"
        if brand in [b.lower() for b in cfg.get("preferred", [])]:
            return 1.0, f"brand {brand} (preferred)"
        return 0.7, f"brand {brand}"

    # --------------------------------------------------------- price & extras
    @staticmethod
    def _budget_fit(raw: RawListing, prefs: dict) -> tuple[float, str]:
        """Budget fit is a multiplier, not a dimension - see the module docstring."""
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

    @staticmethod
    def _extras(attrs: Attributes, raw: RawListing, prefs: dict,
                cfg: dict) -> tuple[float, list[str]]:
        total, reasons = 0.0, []

        points, note = value_model.bargain(raw.price, attrs)
        if note:
            total += points
            reasons.append(note)

        for model in prefs.get("preferred_models", []):
            if model.lower() in raw.title.lower():
                total += cfg.get("preferred_model", 0)
                reasons.append(f"+{cfg.get('preferred_model', 0)} reference model ({model})")
                break

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

    @staticmethod
    def _verdict(value: int, attrs: Attributes, raw: RawListing, budget_fit: float) -> str:
        if value >= 85:
            head = "Very good offer"
        elif value >= 70:
            head = "Good offer"
        elif value >= 55:
            head = "Average offer"
        else:
            head = "Weak offer"

        bits = []
        if attrs.get("geo_reach"):
            bits.append(f"geometry checked (reach {attrs['geo_reach']} mm)")
        elif attrs.get("frame_size_estimated"):
            bits.append("size estimated - confirm with the seller")
        elif attrs.get("frame_size_cm") or attrs.get("frame_size_letter"):
            bits.append("size from the label - check the geometry")
        else:
            bits.append("size to be confirmed")
        if attrs.get("groupset"):
            bits.append(f"groupset {attrs['groupset']}")
        if raw.price:
            bits.append(f"price {raw.price:.0f} PLN")
        if budget_fit < 0.95:
            bits.append("above target budget")
        return f"{head}. " + ", ".join(bits).capitalize() + "."
