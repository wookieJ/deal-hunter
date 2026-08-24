# Deal Hunter

**Stop scrolling through hundreds of marketplace listings. Describe what a good
deal looks like in YAML, and let a scoring engine read them for you.**

A local, manually-run tool that searches a marketplace, scores every offer
against criteria you define, remembers what it has already seen, and tells you
what is new or has dropped in price since last time.

The engine knows nothing about what you are buying. **A new kind of search is one
YAML file** — no code, no plugin, nothing to register.

```
=== Summary (monitor @ olx) ===
  offers found  : 212
  already known : 203
  new           : 6
  changed       : 3

--- Changes to known offers ---
  Gigabyte M27Q X 27" QHD IPS 240 Hz
    price: 899 -> 689 PLN (drop 210 PLN, -23.4%)

--- Best offers in the database ---

 1. Gigabyte M27Q X 27" QHD IPS 240 Hz
    score 89/100   689 PLN
    Łódź, Łódzkie | 211 km / 2h58m by car | private
    Very good offer. Price 689 pln.
    +55/55 rules +64/64 | +19/25 118 km from search area | +15/20 condition: used |
    x1.00 price 689 PLN (within budget) | +20 high refresh rate | +18 good resolution |
    +12 sensible size | +8 good panel | +6 usb-c or height adjustable
```

Every run also writes `reports/index.html` — one page with **a tab per search**,
photo thumbnails, driving distance from your door and a direct link. Always the
same path, so bookmark it once and refresh.

## What a search looks like

Every search file has the same shape, whatever you are buying. Generic fields
first, then the rules that say what *you* care about:

```yaml
name: monitor
source: olx

search:
  category_id: 1201
  queries: ['', '27 cali']
  price: { from: 300, to: 2500 }
  area: { name: Warszawa, city_id: 17871, lat: 52.2297, lon: 21.0122, radius_km: 100 }

budget:
  target: 900          # the sweet spot
  comfortable_max: 1200
  soft_max: 1600
  hard_max: 2500       # above this: rejected

scoring:
  weights: { rules: 55, location: 25, condition: 20 }
  rules:
    - { name: high refresh rate, any: ['\b(144|165|240)\s*hz\b'], points: 20 }
    - { name: good resolution,   any: ['\bqhd\b', '\b4k\b'],      points: 18 }
    - { name: dead pixels,       any: ['martw\w*\s*piksel\w*'],   points: -18 }
    - { name: broken,            any: ['nie\s*dzia[lł]a'],        reject: true }
```

That is a complete, working search. Patterns are regexes, matched against the
title, the description and the marketplace's own fields. `reject:` throws an
offer out, `require:` demands a match, `scope: title` narrows a rule.

Negation is handled: a listing saying *"brak martwych pikseli"* — no dead pixels
— does not trip the dead-pixel rule. Sellers advertise the absence of defects far
more often than their presence, and reading that backwards is the worst mistake a
deal hunter can make.

## Quickstart

Requires Python 3.11+.

```bash
git clone https://github.com/wookieJ/deal-hunter.git
cd deal-hunter
./setup.sh            # creates .venv, installs 3 dependencies
./install-cli.sh      # optional: puts `deal` on your PATH
deal run -p monitor
```

No server, no scheduler, no API keys, no account.

## Usage

```bash
deal run -p <search>          # search, score, store, report
deal run -p <search> -l 40    # stop after 40 offers (quick test)
deal top -p <search> -n 20    # best stored offers, no fetching
deal history olx:1089311360   # price history of one offer
deal rescore -p <search>      # recompute after editing a search file (offline)
deal report                   # rebuild the combined report (offline)
deal reset                    # wipe collected offers
deal profiles                 # list searches
./test.sh                     # run the test suite
```

## How it scores

```
final = spec_score  x  budget_fit  +  bonuses
```

**Budget fit is a multiplier, not one criterion among many.** In a flat weighted
sum, an expensive well-specified item outranks a sensibly priced one purely on
spec — the opposite of what a deal hunter should do. As a multiplier, something
near your ceiling keeps only ~70% of its score, so it has to be genuinely
exceptional to win, while still appearing if it really is.

**Unknown is not the same as bad.** A criterion that cannot be determined drops
out of the weight normalisation instead of scoring low, so a terse listing is not
punished for being terse. Matching is regex over inflected Polish and *will* miss
things; a miss must cost certainty, not points. The score then regresses toward a
neutral prior in proportion to what is unknown, so a near-empty listing cannot top
the ranking either. You are told which it is:

```
confidence 48% (48/100 of weight known) -> 94 blended toward 55 = 74
```

**Every score explains itself.** Each line above is a criterion, its contribution
and its reason. A score you cannot argue with is a score you cannot trust.

## How it works

```
Source ──► Extract ──► Enrich* ──► Score ──► Storage ──► Report
```

**Source** talks to the marketplace's own JSON API rather than scraping HTML, so
there is no DOM to break. One catch worth knowing: OLX rejects `curl`, `requests`
and `httpx` with HTTP 403 based on TLS fingerprint, so the adapter uses
[`curl_cffi`](https://github.com/lexiforest/curl_cffi) impersonating Chrome.

**Storage** stores each offer once and appends a new *version* row only when
`sha256(price | title | description)` changes. That single mechanism gives
deduplication, new-offer detection, price-change detection and full price history
at the same time.

**Travel** adds real driving distance and time from your home via the free public
OSRM service — no API key. Amusingly, OSRM *rejects* the browser-impersonating
client that OLX *requires*, so that call deliberately uses plain `urllib`.

## Going further than rules

Rules cover most of what you want to say. When a search needs real structure —
numeric ranges, quality tiers, or a reference table mapping a model to its actual
specification — add an optional **domain pack**: one YAML file under `domains/`
that a search opts into with a single `domain:` line. Nothing else changes.

Two packs ship as worked examples. Neither shares vocabulary or code with the
other, and a test walks the engine source and fails if product knowledge leaks
back into it. See [docs/extending.md](docs/extending.md).

## Two locations, deliberately separate

| | Where it lives | What it does |
|---|---|---|
| **Search area** | `search.area` in a search file | Where offers are hunted. You can hunt in a city you do not live in. Also narrows the marketplace's result cap. |
| **Home** | `config/settings.local.yml` | Where *you* live. Used only for travel distance in reports. |

**Personal values never reach the repository.** `config/settings.local.yml` and
`config/profiles/<name>.local.yml` are gitignored and override the tracked files,
which ship with placeholders — so cloning works immediately while your address,
budget and preferences stay on your machine.

## Honest limitations

- Matching is regex over inflected Polish and misses things. That is survivable
  only because a miss produces *unknown*, which costs no points — but it does mean
  the confidence figure is doing real work.
- The marketplace caps any single search at 1000 results; narrow with price,
  category and area.
- Sold and removed offers are never marked inactive, so the database accumulates
  stale entries.
- Market-value estimates are a heuristic, not comparable-sales data. Without a
  domain pack that declares one, no estimate is made at all.
- This uses an undocumented internal API that could change or start blocking.

## Etiquette

Requests are rate-limited to one per second, and raw payloads are archived under
`data/raw/` so re-analysis never means re-scraping. This is a personal-use tool
that browses public listings at roughly human speed. Please keep it that way.

## License

MIT — see [LICENSE](LICENSE).
