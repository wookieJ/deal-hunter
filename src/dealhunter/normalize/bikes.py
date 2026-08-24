"""Extract structured bike attributes from free-text Polish listings.

Why regex over OLX's own filters: OLX only offers frame size in coarse inch
buckets (17-18", 19-20"), which is useless for gravel/road bikes sold in cm or
S/M/L, and it has no groupset filter at all - yet groupset is the single most
price-relevant spec. So the real signal lives in the title and description.
"""
from __future__ import annotations

import re

from ..models import Attributes, RawListing
from .geometry import resolve as resolve_geometry

# ---------------------------------------------------------------- vocabularies

BRANDS = [
    "merida", "cube", "giant", "trek", "canyon", "specialized", "cannondale", "scott",
    "kross", "orbea", "bianchi", "focus", "ghost", "kellys", "ktm", "lapierre", "marin",
    "fuji", "bombtrack", "genesis", "ridley", "cervelo", "bmc", "pinarello", "colnago",
    "rondo", "accent", "romet", "unibike", "author", "corratec", "stevens", "rose",
    "bergamont", "conway", "kona", "santa cruz", "yeti", "norco", "vitus", "boardman",
    "van rysel", "triban", "riverside", "rockrider", "btwin", "b'twin", "decathlon",
    "gt", "haibike", "cross", "gazelle", "batavus", "koga", "kalkhoff", "winora",
    "3t", "open", "salsa", "surly", "all-city", "niner", "wilier", "basso", "look",
]

# Groupset -> quality tier (0-100). Ordered: most specific pattern first.
GROUPSETS: list[tuple[str, str, int]] = [
    (r"\bred\s*(?:axs|etap)\b", "SRAM Red AXS", 100),
    (r"\bdura[\s\-]?ace\b", "Shimano Dura-Ace", 100),
    (r"\bforce\s*(?:axs|etap)\b", "SRAM Force AXS", 92),
    (r"\bultegra\b", "Shimano Ultegra", 92),
    (r"\bgrx\s*(?:81[05]|820|rx8)\w*\b", "Shimano GRX 800/820", 90),
    (r"\bekar\b", "Campagnolo Ekar", 90),
    (r"\bforce\b", "SRAM Force", 85),
    (r"\bchorus\b", "Campagnolo Chorus", 85),
    (r"\bgrx\s*(?:6[01]0|rx6)\w*\b", "Shimano GRX 600", 80),
    (r"\brival\s*(?:axs|etap)\b", "SRAM Rival AXS", 78),
    (r"\bxt\b|\bdeore\s*xt\b", "Shimano Deore XT", 78),
    (r"\b105\b", "Shimano 105", 78),
    (r"\brival\b", "SRAM Rival", 72),
    (r"\bgrx\s*(?:400|rx4)\w*\b", "Shimano GRX 400", 72),
    (r"\bslx\b", "Shimano SLX", 70),
    (r"\bapex\s*(?:axs|etap)\b", "SRAM Apex AXS", 62),
    (r"\btiagra\b", "Shimano Tiagra", 60),
    (r"\bgrx\b", "Shimano GRX", 75),
    (r"\bdeore\b", "Shimano Deore", 58),
    (r"\bapex\b", "SRAM Apex", 55),
    (r"\bcues\b", "Shimano CUES", 50),
    (r"\bnx\b", "SRAM NX", 50),
    (r"\bsx\b", "SRAM SX", 38),
    (r"\bsora\b", "Shimano Sora", 42),
    (r"\balivio\b", "Shimano Alivio", 35),
    (r"\bclaris\b", "Shimano Claris", 28),
    (r"\bacera\b", "Shimano Acera", 28),
    (r"\baltus\b", "Shimano Altus", 25),
    (r"\bmicroshift\b|\badvent\b|\bsword\b", "microSHIFT", 45),
    (r"\btourney\b", "Shimano Tourney", 15),
]

BRAKES = [
    (r"hydrauliczn\w*\s*(?:hamulc\w*\s*)?tarczow\w*|tarczow\w*\s*hydrauliczn\w*|"
     r"hydraulic\w*\s*disc|\bhydraulik\w*\b|\bmt\d{3}\b|\bbr-?r?[dm]\w*\b", "hydraulic_disc"),
    (r"mechaniczn\w*\s*(?:hamulc\w*\s*)?tarczow\w*|tarczow\w*\s*mechaniczn\w*|"
     r"mechanical\s*disc|\bspyre\b|\bavid\s*bb\b|\btektro\s*mira\b", "mechanical_disc"),
    (r"\btarczow\w*\b|\bdisc\b|\bhamulce\s*tarcz", "disc"),
    (r"v[\s\-]?brake|szczękow\w*|szczekow\w*|\bcaliper\b|\bobręczow\w*", "rim"),
]

MATERIALS = [
    (r"\bkarbon\w*|\bcarbon\w*|\bwęgl\w*|\bwegl\w*", "carbon"),
    (r"\btytan\w*|\btitanium\b", "titanium"),
    (r"\bcr[\s\-]?mo\b|\bchromoly\b|\bcromoly\b|\breynolds\b|\bcolumbus\b", "cromoly"),
    (r"\bstal\w*|\bsteel\b|\bhi[\s\-]?ten\b", "steel"),
    (r"\balumini\w*|\baluminum\b|\balu\b|\b6061\b|\b7005\b", "aluminium"),
]

BIKE_TYPES = [
    (r"\bgravel\w*|\bszutrow\w*|\ball[\s\-]?road\b", "gravel"),
    (r"\bszosow\w*|\bkolarz\w*|\broad\s*bike\b|\bszosa\b", "road"),
    (r"\bmtb\b|\bgórsk\w*|\bgorsk\w*|\bhardtail\b|\benduro\b|\btrail\b", "mtb"),
    (r"\btrekking\w*|\btreking\w*", "trekking"),
    (r"\bcross\w*", "cross"),
    (r"\bmiejsk\w*|\bcity\s*bike\b|\bholender\w*", "city"),
]

# Flags: (regex, flag name). Presence of the pattern sets the flag.
FLAGS = [
    (r"\bwidelec\s*karbon\w*|\bcarbon\s*fork\b|\bkarbonowy\s*widelec\b", "carbon_fork"),
    (r"\bo[śs]\s*przelotow\w*|\bthru[\s\-]?axle\b|\bthrough\s*axle\b|\bsztywn\w*\s*os\w*|"
     r"\b12\s*x\s*1(?:00|42)\b|\b15\s*x\s*100\b", "through_axle"),
    (r"\btubeless\b|\btlr\b|\btubelessow\w*", "tubeless"),
    (r"\b1\s*x\s*(?:10|11|12|13)\b|\bjedna\s*tarcza\b|\b1x\b", "1x_drivetrain"),
    (r"\bdi2\b|\baxs\b|\betap\b|\belektroniczn\w*\s*(?:przerzut|osprz)", "electronic_shifting"),
    (r"\bgwarancj\w*\b", "warranty"),
    (r"\bnowy\s*rower\b|\bfabrycznie\s*nowy\b|\bpowystawow\w*", "new_or_display"),
]

# Disqualifiers: things that mean "this is not the product I am shopping for".
DISQUALIFIERS = [
    (r"\bna\s*cz[eę][sś]ci\b|\bcz[eę][sś]ci\s*z\s*rower\w*|\bdo\s*renowacji\b|"
     r"\bbez\s*ko[lł]\b|\bsama\s*rama\b|\btylko\s*rama\b|\brama\s*bez\b", "parts_only"),
    (r"\bp[eę]kni[eę]\w*|\bz[lł]amana\s*rama\b|\buszkodzon\w*\s*ram\w*|\bwgniecen\w*\s*ram\w*|"
     r"\brozbit\w*\b", "frame_damage"),
    (r"\bdzieci[eę]c\w*|\bdla\s*dziecka\b|\bjunior\w*\b|\bko[lł]a\s*(?:12|14|16|18|20)\s*[\"']",
     "kids_bike"),
    (r"\belektryczn\w*|\be[\s\-]?bike\b|\bebike\b|\bwspomagani\w*\b|\bbosch\s*(?:perf|active)|"
     r"\bshimano\s*steps\b|\bsilnik\s*\d{3}w\b", "ebike"),
    (r"\bzamieni[eę]\b|\bzamiana\s*na\b|\bkupi[eę]\b|\bposzukuj[eę]\b|\bszukam\b", "wrong_category"),
    (r"\bflat\s*bar\b|\bflatbar\b|\bprosta\s*kierownic\w*|\bp[lł]aska\s*kierownic\w*",
     "flatbar"),
]

# Sellers advertise the ABSENCE of defects far more often than their presence
# ("bez pekniec ramy", "brak uszkodzen"). Matching those naively disqualifies the
# best-described offers - the worst possible failure mode for a deal hunter.
# Words that, near a material mention, mean it describes a component - not the frame.
COMPONENT_CONTEXT = re.compile(
    r"widel\w*|fork|kierownic\w*|wspornik\w*|mostek|sztyc\w*|siode[lł]\w*|"
    r"ko[lł]a\b|obr[eę]cz\w*|felg\w*|korb\w*|bidon\w*|baga[zż]nik\w*")

NEGATIONS = re.compile(r"(?:\bbez\b|\bbrak\w*\b|\bnie\s+ma\b|\bnie\b|\b[zż]adn\w*\b)[^.!?;]{0,40}$")

# OLX only exposes frame size as coarse inch buckets; map them to a usable cm range.
INCH_BUCKET_CM = {
    "16-and-less": (44, 48), '16" i mniej': (44, 48),
    "17-18": (48, 52), '17-18"': (48, 52),
    "19-20": (52, 56), '19-20"': (52, 56),
    "21-22": (56, 60), '21-22"': (56, 60),
    "23-and-more": (60, 64), '23" i wiecej': (60, 64), '23" i więcej': (60, 64),
}

# Matched against the TITLE only. "fitness" in a description often just describes
# how the seller used the bike; in the title it reliably means a flat-bar hybrid,
# which is a different bike from the drop-bar gravel being shopped for.
TITLE_DISQUALIFIERS = [
    (r"\bfitness\b", "fitness_bike"),
    (r"\bframeset\b|\bsam[aą]\s*ram[aę]\b", "parts_only"),
]

_STOP_MODEL = {"rower", "rowerowy", "gravel", "szosowy", "gorski", "górski", "nowy", "uzywany",
               "używany", "sprzedam", "rozmiar", "rama", "ramy", "szt", "okazja", "polecam"}


def _affirmative(text: str, pattern: str) -> bool:
    """True only if the pattern occurs somewhere that is NOT negated."""
    for m in re.finditer(pattern, text):
        if not NEGATIONS.search(text[max(0, m.start() - 45):m.start()]):
            return True
    return False


def _first_match(text: str, table) -> tuple:
    for pattern, *rest in table:
        if re.search(pattern, text):
            return tuple(rest)
    return ()


class BikeNormalizer:
    category = "bikes"

    def normalize(self, raw: RawListing) -> Attributes:
        text = raw.text
        title = raw.title.lower()
        params = {k: v.lower() for k, v in raw.params.items()}

        attrs: Attributes = {
            "bike_type": self._bike_type(text, params),
            "brand": self._brand(title, text, params),
            "frame_material": self._material(text, params),
            "brakes": self._brakes(text, params),
            "wheel_size": self._wheel_size(text, params),
            "model_year": self._year(text),
            "condition": params.get("state", ""),
            "is_business": raw.is_business,
        }
        attrs["model"] = self._model(raw.title, attrs["brand"])
        attrs["frame_size_estimated"] = False
        attrs.update(self._frame_size(text, params))
        attrs.update(self._groupset(text))
        attrs["flags"] = sorted({name for pattern, name in FLAGS if re.search(pattern, text)})
        if attrs["brakes"] == "hydraulic_disc" and "hydraulic_disc" not in attrs["flags"]:
            attrs["flags"].append("hydraulic_disc")
        # Real geometry beats the size label whenever we can identify the model.
        attrs.update(resolve_geometry(
            attrs["brand"], raw.title, attrs["frame_size_letter"], attrs["model_year"]))

        title_lower = raw.title.lower()
        attrs["disqualifiers"] = sorted(
            {name for pattern, name in DISQUALIFIERS if _affirmative(text, pattern)}
            | {name for pattern, name in TITLE_DISQUALIFIERS
               if _affirmative(title_lower, pattern)}
        )
        return attrs

    # ------------------------------------------------------------ extractors
    @staticmethod
    def _bike_type(text: str, params: dict) -> str:
        found = _first_match(text, BIKE_TYPES)
        return found[0] if found else ""

    @staticmethod
    def _brand(title: str, text: str, params: dict) -> str:
        if params.get("brand") and params["brand"] not in ("inna", "others", "other"):
            return params["brand"]
        for source in (title, text):          # prefer a brand named in the title
            for brand in BRANDS:
                if re.search(rf"\b{re.escape(brand)}\b", source):
                    return brand
        return ""

    @staticmethod
    def _model(title: str, brand: str) -> str:
        if not brand:
            return ""
        m = re.search(rf"\b{re.escape(brand)}\b(.*)", title, re.IGNORECASE)
        if not m:
            return ""
        tokens = re.findall(r"[A-Za-z0-9\-\.]+", m.group(1))
        model: list[str] = []
        for tok in tokens[:4]:
            if tok.lower() in _STOP_MODEL or len(tok) < 2:
                break
            model.append(tok)
        return " ".join(model[:3])

    @staticmethod
    def _material(text: str, params: dict) -> str:
        """Frame material only.

        A carbon *fork* on an aluminium frame is extremely common, and reading it
        as a carbon frame inflated the market-value estimate by 60%. So explicit
        frame phrasing wins, and generic matches next to a component word lose.
        """
        p = params.get("framematerial", "")
        mapping = {"karbon": "carbon", "aluminium": "aluminium", "stal": "steel",
                   "cr-mo": "cromoly", "hi-ten": "steel"}
        if p in mapping:
            return mapping[p]

        for pattern, material in MATERIALS:
            explicit = (rf"ram[aęy]\w*\s+(?:\w+\s+){{0,2}}?(?:{pattern})"
                        rf"|(?:{pattern})\w*\s+ram[aęy]")
            if re.search(explicit, text):
                return material
        if re.search(r"\bfull\s*carbon\b", text):
            return "carbon"

        for pattern, material in MATERIALS:
            for m in re.finditer(pattern, text):
                window = text[max(0, m.start() - 30):m.end() + 30]
                if not COMPONENT_CONTEXT.search(window):
                    return material
        return ""

    @staticmethod
    def _brakes(text: str, params: dict) -> str:
        p = params.get("braketype", "")
        mapping = {"tarczowe hydrauliczne": "hydraulic_disc", "tarczowe mechaniczne": "mechanical_disc",
                   "szczękowe": "rim", "v-brake": "rim", "szczękowe hydrauliczne": "rim"}
        if p in mapping:
            return mapping[p]
        found = _first_match(text, BRAKES)
        return found[0] if found else ""

    @staticmethod
    def _wheel_size(text: str, params: dict) -> str:
        if params.get("wheelsize"):
            return params["wheelsize"].replace('"', "")
        m = re.search(r"\b(700\s*c|650\s*b|29|27[,.]5|28|26|24)\s*[\"']?", text)
        return m.group(1).replace(" ", "") if m else ""

    @staticmethod
    def _year(text: str) -> int | None:
        years = [int(y) for y in re.findall(r"\b(20[0-2]\d)\b", text) if 2005 <= int(y) <= 2027]
        return max(years) if years else None

    @staticmethod
    def _frame_size(text: str, params: dict) -> Attributes:
        out: Attributes = {"frame_size_cm": None, "frame_size_letter": "", "frame_size_raw": ""}

        # cm: "rozmiar ramy 56", "rama 54 cm", "56cm". 44-64 excludes wheel sizes.
        for pattern in (
            r"(?:rozmiar\w*\s*ram\w*|ram\w*\s*rozmiar\w*|frame\s*size|rozmiar|rozm\.?|ram[ay])"
            r"[\s:\-]*([4-6]\d)\s*(?:cm)?\b",
            r"\b([4-6]\d)\s*cm\b",
        ):
            m = re.search(pattern, text)
            if m and 44 <= int(m.group(1)) <= 64:
                out["frame_size_cm"] = int(m.group(1))
                out["frame_size_raw"] = m.group(0).strip()
                break

        # letter sizes: "rozmiar L", "rozm. M/L", "size XL"
        m = re.search(
            r"(?:rozmiar\w*|rozm\.?|size|ram[ay])[\s:\-]*"
            r"\b(xxl|xl|l/xl|m/l|s/m|xs|s|m|l)\b(?!\w)", text)
        if m:
            out["frame_size_letter"] = m.group(1).upper().replace("/", "/")
            out["frame_size_raw"] = out["frame_size_raw"] or m.group(0).strip()

        # MTB-style inch size written in the text ("rama 19 cali")
        if out["frame_size_cm"] is None and not out["frame_size_letter"]:
            m = re.search(r"(?:rozmiar\w*|rozm\.?|ram[ay])[\s:\-]*(1[3-9]|2[0-4])\s*(?:\"|cal\w*|inch)", text)
            if m:
                out["frame_size_cm"] = round(int(m.group(1)) * 2.54)
                out["frame_size_estimated"] = True
                out["frame_size_raw"] = m.group(0).strip()

        # OLX's coarse inch bucket, as a last resort: take the middle of the range
        if out["frame_size_cm"] is None and not out["frame_size_letter"] and params.get("framesize"):
            out["frame_size_raw"] = params["framesize"]
            span = INCH_BUCKET_CM.get(params["framesize"])
            if span:
                out["frame_size_cm"] = (span[0] + span[1]) // 2
                out["frame_size_estimated"] = True
        return out

    @staticmethod
    def _groupset(text: str) -> Attributes:
        for pattern, name, tier in GROUPSETS:
            if re.search(pattern, text):
                return {"groupset": name, "groupset_tier": tier}
        return {"groupset": "", "groupset_tier": None}
