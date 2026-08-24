# Deal Hunter

**Stop scrolling through hundreds of marketplace listings. Let a scoring engine
read them for you.**

A local, manually-run tool that searches OLX, extracts real specs from messy
Polish free-text listings, scores every offer against *your* criteria, remembers
what it has already seen, and tells you what is new or has dropped in price since
last time.

Version 1 covers **OLX** and **bikes**. The architecture is built so that new
marketplaces, product categories and analysis steps slot in without a rewrite —
see [Extending](docs/extending.md).

```
=== Podsumowanie (gravel @ olx) ===
  znalezionych ofert : 206
  juz znanych        : 203
  nowych             : 0
  zmienionych        : 3

--- Zmiany w znanych ofertach ---
  Trek Checkpoint alr5 gravel
    cena: 5900 -> 5500 zl (spadek 400 zl, -6.8%)

--- Najlepsze oferty w bazie ---

 1. Rower Gravel Specialized Diverge E5 Sport Hydraulika 105 rama 56cm
    score 100/100   3199 zl   56 cm   Shimano 105
    Łódź, Łódzkie | prywatnie | hydraulic_disc | aluminium
    Bardzo dobra oferta. Rozmiar sie zgadza, osprzet shimano 105, cena 3199 zl.
    +30/30 rozmiar 56 cm (preferowany) | +20/25 osprzet Shimano 105 |
    +25/25 cena 3199 zl (w budzecie docelowym) | +10/10 marka specialized (preferowana) |
    +7/10 stan: używane | +6 atuty: hydraulic_disc, through_axle | +2 sprzedawca prywatny
```

Every run also writes a self-contained HTML report with photo thumbnails, the
seller's location, driving distance from home and a direct link — because for
bikes a picture settles it in three seconds.

## Why not just use the marketplace's own filters?

Because they are not good enough to find a deal:

| What matters when buying a bike | What OLX lets you filter by |
|---|---|
| Frame size (54 cm, 56 cm, L) | Inch buckets only: `17-18"`, `19-20"` |
| Groupset (GRX 400 vs Claris) — the biggest price driver | **No filter at all** |
| Brakes, axles, tubeless, model year | Partially, and only when the seller filled it in |

In a live sample, OLX's own frame-size field was filled in for **12 of 52**
listings. The real information is in the title and description — so this tool
reads those instead.

## Quickstart

Requires Python 3.11+.

```bash
git clone https://github.com/wookieJ/deal-hunter.git
cd deal-hunter
./setup.sh                  # creates .venv, installs 3 dependencies
./run.sh run                # search, score, store, report
```

That is the whole setup. No server, no scheduler, no API keys, no account.

## Usage

```bash
./run.sh run                      # search with the default 'gravel' profile
./run.sh run -p gravel            # pick a profile explicitly
./run.sh run -l 40                # stop after 40 offers (quick test)
./run.sh run --no-report          # skip the HTML report
./run.sh top -n 20                # best offers already in the DB, no fetching
./run.sh history olx:1089311360   # price history of a single offer
./run.sh rescore                  # recompute scores after editing a profile (offline)
./run.sh reset                    # wipe collected offers and start fresh
./run.sh profiles                 # list available profiles
./test.sh                         # run the test suite (offline)
```

Prefer a real install? `pip install -e .` gives you a `dealhunter` command; set
`DEALHUNTER_HOME` if you want config and data somewhere other than the repo.

## Two locations, deliberately separate

This tool deals with two different places, and conflating them produces nonsense:

| | Where it lives | What it does |
|---|---|---|
| **Search area** | `search.olx.area` in a profile | Where offers are hunted. A search parameter — you can hunt in a city you do not live in. Also narrows OLX's 1000-result cap: Poznan +100 km returns ~760 offers instead of 1000 truncated from the whole country. |
| **Home** | `config/settings.local.yml` | Where *you* live. Used only for the travel distance shown in reports. |

`proximity_to` decides which of the two the proximity score measures against, so
hunting around another city rewards offers *there*, while the report still tells
you how far each one is from your own door.

**Personal values never reach the repository.** Two gitignored files override the
tracked ones, and you only put in them the keys you want to change:

| File | Holds |
|---|---|
| `config/settings.local.yml` | Your home coordinates |
| `config/profiles/<name>.local.yml` | Your body measurements, budget and city |

The committed `config/settings.yml` and `config/profiles/gravel.yml` are examples
with placeholder numbers, so cloning and running works immediately — and your
height, inseam, budget and address stay on your machine. Each file's comments show
the block to copy.

## The scoring model

```
final = spec_score  x  budget_fit  +  bargain_bonus
```

**Why multiplicative, not a flat weighted sum.** In a flat sum, an expensive bike
with a better groupset simply outscores a sensibly priced one — which is the exact
opposite of what a deal hunter should do. Making budget fit a *multiplier* means a
bike at 5000 PLN keeps only ~75% of its spec score, so it has to be genuinely
exceptional to beat a well-priced one, while still showing up if it really is.

**Sizing uses real geometry, not the size label.** Nominal sizes are not
comparable across brands, or even across generations of the same model:

| Merida Silex | reach | stack |
|---|---|---|
| gen 1, size M | 400 mm | 625 mm |
| gen 1, size L | 415 mm | 644 mm |
| gen 2, size M | 412 mm | 607 mm |
| gen 2, size L | 426 mm | 626 mm |

A gen-2 M has more reach than a gen-1 M and nearly as much as a gen-1 L. So when
the model is present in `config/geometry.yml` the score uses reach and stack
against a window derived from your height; otherwise it falls back to the size
label at a **capped** confidence and says so in the reasons.

**Bargain detection** estimates a rough market value from the spec (groupset tier,
frame material, brakes, age, condition) and rewards offers priced well below it —
so a cheap bike with good parts rises, and an overpriced one is marked as such.

## Tuning what counts as a good deal

Everything about *what you want* lives in a YAML profile. No Python required:

```yaml
preferences:
  budget:
    target: 4000            # the sweet spot
    comfortable_max: 4500   # no penalty at or below this
    soft_max: 5000          # worth it only if clearly better
    hard_max: 6500          # above this: rejected
  rider:
    height_cm: 178                # yours goes in gravel.local.yml, not here
    inseam_cm: 82
  location:
    proximity_to: search_area     # or "home" - what proximity is measured against
    preferred_radius_km: 100      # scored, never a hard filter
  frame_size:
    ideal_reach_mm: [402, 426]    # used when geometry is known
    label_confidence_cap: 0.85    # a size label never scores full marks
    preferred_letter: ["L", "M/L"]
  preferred_groupsets: [grx]      # preferred, never required
  disqualifying: [parts_only, frame_damage, kids_bike, ebike, flatbar]

weights:                          # spec dimensions; price is NOT one of them
  size: 32
  groupset: 22
  features: 16
  condition: 12
  location: 10
  brand: 8
```

Hunting a different kind of bike? Copy the profile, change `category_id` (ids for
every OLX bike category are listed in `src/dealhunter/sources/olx.py`) and adjust
the preferences.

## How it works

```
Source ──► Normalizer ──► Enricher* ──► Scorer ──► Storage ──► Reporter
(OLX)      (regex)        (none yet)    (profile)  (SQLite)    (console + HTML)
```

Each arrow is a Protocol, so any layer can be replaced without touching the others.

**Source** talks to OLX's own JSON API rather than scraping HTML, so there is no
DOM to break. One catch worth knowing: OLX rejects `curl`, `requests` and `httpx`
with HTTP 403 based on TLS fingerprint, so the adapter uses
[`curl_cffi`](https://github.com/lexiforest/curl_cffi) impersonating Chrome.

**Normalizer** pulls structure out of free text: brand, model, frame size,
groupset and its quality tier, brakes, material, wheel size, model year and
feature flags. It also guards against negation — sellers advertise the *absence*
of damage far more often than its presence, and reading "rama bez pęknięć" as
"cracked frame" silently rejects some of the best-described offers.

**Scorer** turns attributes plus your profile into a 0-100 score. Every dimension
contributes a signed, human-readable reason, so you can always see *why* something
scored 91 — a score you cannot argue with is a score you cannot trust.

**Travel** adds real driving distance and time from your home to each offer shown
in a report, via the free public OSRM routing service — no API key. Results are
cached on a coordinate grid, so a run costs a handful of requests. Amusingly, OSRM
*rejects* the browser-impersonating client that OLX *requires*, so that call
deliberately uses plain `urllib`.

**Storage** stores each offer once and appends a new *version* row only when
`sha256(price | title | description)` changes. That single mechanism gives you
deduplication, new-offer detection, price-change detection and full price history
at the same time.

## Project structure

```
config/profiles/     what a good deal means (YAML, tune here)
src/dealhunter/
  sources/           marketplace adapters      -> add Allegro here
  normalize/         free text -> attributes   -> add a product category here
  scoring/           attributes -> 0-100 score
  storage/           SQLite schema, dedup, change detection
  report/            console + HTML output
  pipeline.py        the only module that knows the full sequence
tests/               24 offline tests
docs/extending.md    how to add a source, category, LLM enricher, notifications
```

## Roadmap

Deliberately not built yet, but the seams are in place — each maps to exactly one
layer (details in [docs/extending.md](docs/extending.md)):

- [ ] Detect sold/removed offers via per-listing re-check
- [ ] Replace the heuristic market-value model with real reference prices computed
      from observed listing history
- [ ] LLM analysis of descriptions, and image analysis
- [ ] Allegro and other marketplaces
- [ ] Notifications and scheduled runs
- [ ] MCP server so Claude or ChatGPT can query your findings
- [ ] English UI (output is currently Polish, matching the marketplace)

## Honest limitations

- Groupset is recognised in roughly **half** of listings; the rest get a neutral
  score rather than a wrong one.
- The geometry table ships with **Merida Silex only**. Every other model falls back
  to label-based sizing at reduced confidence until you add it — see the template
  in `config/geometry.yml`. Manufacturer charts are the source; do not guess.
- Market value is a **heuristic**, not comparable-sales data. It answers "is this
  cheap for what it is?", not "what is this bike worth?".
- OLX caps any single search at **1000 results**, so broad profiles cannot be
  fully enumerated — narrow them with price and category filters.
- Sold and removed offers are never marked inactive, so the database accumulates
  stale entries.
- This uses an **undocumented internal API** that could change or start blocking
  at any time.

## Etiquette

Requests are rate-limited to one per second, and raw payloads are archived under
`data/raw/` so re-analysis never means re-scraping. This is a personal-use tool
that browses public listings at roughly human speed. Please keep it that way, and
check OLX's terms before doing anything more aggressive.

## License

MIT — see [LICENSE](LICENSE).
