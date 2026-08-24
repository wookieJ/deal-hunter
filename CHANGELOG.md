# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Detect sold/removed offers via per-listing detail re-check
- Replace the heuristic market-value model with reference prices computed from
  observed listing history
- Populate `config/geometry.yml` beyond Merida Silex, from manufacturer charts
- Optional LLM enricher for description analysis
- Allegro source adapter
- Desktop notifications and scheduled runs

## [0.4.0] - 2026-08-24

### Changed
- **The engine no longer knows anything about bikes.** Brands, groupsets, brake
  types, frame-size patterns, market values and every scoring dimension moved out of
  Python into a domain pack, `domains/bikes/`. Extraction and scoring are now
  declarative types executed against that pack, so a new product type is a directory
  of YAML and a new search is a single YAML file. `domains/<name>/hooks.py` remains
  as an escape hatch for what YAML cannot express.
- **Unknown is no longer scored as bad.** Dimensions that cannot be determined drop
  out of the weight normalisation rather than taking a low default, so a terse
  listing is not punished for being terse. This matters doubly because extraction is
  regex over inflected Polish, where a missed pattern is common and should cost
  nothing beyond uncertainty.
- **The report is one page with a tab per search**, at the stable path
  `reports/index.html`, replacing one file per profile. The selected tab is
  remembered between refreshes.
- All user-facing output is English. The Polish regexes in the bikes domain are
  untouched: they parse Polish listings, and translating them would break extraction.

### Added
- `config/profiles/mtb.yml`, a second search written purely in YAML, as proof that
  no code is needed for a new one.
- `deal report` to rebuild the combined report offline.
- A confidence figure on every score, reported rather than folded into the number.
- `penalties:` in a profile for signals that deserve a nudge rather than a rejection.

### Fixed
- Pure renormalisation let 22% of the weight decide 100% of the score, so a
  near-empty listing reached 94/100 — the mirror image of punishing sparse listings.
  Scores now regress toward `unknown_prior` in proportion to what is unknown.
- `SCORING_VERSION` is part of the profile fingerprint. Changing the scorer's output
  used to leave stored scores stale, because the fingerprint covered the rules but
  not the code that renders them.

## [0.3.0] - 2026-08-24

### Added
- **Search area as a first-class search parameter** (`search.<source>.area`), applied
  to OLX as a city + radius filter. Besides narrowing the hunt, it pushes back the
  1000-result cap: a city +100 km returns ~760 offers instead of 1000 truncated from
  the whole country.
- **Gitignored local overrides for both settings and profiles**
  (`config/settings.local.yml`, `config/profiles/<name>.local.yml`), deep-merged over
  the tracked files. Home coordinates, body measurements and budget are personal and
  must never reach a public repository, so the committed files are examples with
  placeholder numbers and a clone still runs out of the box.
- `load_profile(..., use_local=False)`, used by the test suite: expectations that
  depend on a gitignored personal file pass locally and fail in CI.
- `proximity_to` setting choosing whether the proximity score measures distance from
  the search area or from home.
- `report.keep_dated_copies` setting (default `false`) for keeping a timestamped
  archive alongside the stable report.
- **`install-cli.sh`** putting a `deal` command on your PATH, so the tool runs from
  any directory. The launcher points back at the checkout, so config, data and
  reports resolve there regardless of the working directory.
- `reset` command to wipe collected offers. It keeps `travel_cache` by default, since
  that table maps coordinates to road distances, never goes stale, holds nothing about
  offers, and costs one routing request per entry to rebuild. `--all` drops it too.

### Changed
- **The HTML report is written to one stable path** (`<profile>_latest.html`) instead
  of a new timestamped file per run. A filename that changes every run cannot be
  bookmarked and just accumulates copies of a view that is only ever interesting in
  its latest state.
- **Search area and home address are now separate concepts.** Previously one field did
  both jobs, which breaks as soon as you hunt somewhere you do not live: the search
  area defines where to look, while home only ever drives the travel distances in
  reports. The resolved proximity anchor lives inside `preferences`, so changing
  either one correctly invalidates stored scores.

### Fixed
- Flat-bar hybrids advertised as gravel (for example "Cannondale Quick 1 fitness/gravel")
  are detected via a title-scoped rule and disqualified. Verified against live data:
  4 of 235 offers matched, all of them genuinely flat-bar bikes or framesets. The same
  word in a *description* only says how the seller used the bike, so it is ignored there.

## [0.2.0] - 2026-08-24

Scoring reworked around **value for money** rather than raw spec, plus geometry-based
sizing and travel distance.

### Changed
- **Scoring is now multiplicative:** `final = spec_score x budget_fit + bargain_bonus`.
  Previously price was one weighted dimension among many, which let an expensive,
  well-equipped bike outrank a sensibly priced one purely on spec. Budget fit is now
  a multiplier, so a bike at the soft maximum keeps only ~75% of its spec score and
  has to be genuinely exceptional to win — while still appearing if it is.
- **Sizing prefers manufacturer geometry over the size label.** Nominal sizes are not
  comparable across brands or generations (a gen-2 Merida Silex M has more reach than
  a gen-1 M), so label-based sizing is now capped in confidence and clearly marked.
- Only obviously wrong sizes are rejected; anything arguable is scored down instead,
  because size labels are brand-dependent.
- Seller type no longer affects the score — shops and outlets compete on equal terms.
- Spec dimensions reweighted: size 32, groupset 22, features 16, condition 12,
  location 10, brand 8. Price is deliberately not among them.

### Added
- **Geometry table** (`config/geometry.yml`) mapping model generation and size to
  reach/stack, with per-entry `verified` flags and confidence degradation when the
  model year is unknown.
- **Market-value heuristic** (`scoring/value.py`) estimating a fair asking price from
  groupset tier, frame material, brakes, age and condition, feeding a bargain bonus
  and an overpriced penalty.
- **Distance scoring** using the coordinates OLX returns with every offer — no
  geocoding needed. Local offers rank higher; distant ones are never rejected.
- **Driving distance and time** from home to each reported offer via the public OSRM
  service, cached on a coordinate grid and capped per run. Falls back to a
  straight-line estimate if routing is unavailable.
- Offer location, driving distance and a visible link in both console and HTML reports.
- `rescore` command and an automatic rescoring pass on every run, recomputing
  stored scores against the current profile without any marketplace requests.
- `features` scoring dimension covering hydraulic brakes, carbon fork, thru-axles and
  tubeless, where unknown is treated as partially credited rather than absent.
- 25 further tests, including the owner's buying rules as executable assertions.

### Fixed
- **A carbon fork was read as a carbon frame**, inflating the market-value estimate by
  ~60% on a very common configuration. Frame material now requires explicit frame
  phrasing, or a match not adjacent to a component word.
- Flat-bar conversions are detected and disqualified — they are a different bike.
- Migration adds coordinate columns to databases created before this version.
- **Stored scores are now invalidated when the profile changes.** Offers that fall
  out of the search window (for example once the price ceiling drops) kept scores
  computed under the previous rules and still ranked, so a bike above the hard
  budget limit could appear in the top list with a score no current rule could
  reproduce. Each score now records a fingerprint of the scoring rules, and every
  run rebuilds outdated ones from archived payloads - entirely offline.

## [0.1.0] - 2026-08-24

First working version. OLX + gravel bikes, run manually from the terminal.

### Added
- **OLX source adapter** using OLX's internal JSON API, with rate limiting,
  retry/backoff and cross-page deduplication of promoted ads.
- **Bike normalizer**: extracts brand, model, frame size (cm, letter and OLX inch
  bucket), groupset with a quality tier, brakes, frame material, wheel size, model
  year and feature flags from Polish free text.
- **Weighted scoring engine**: 0-100 score from size, groupset, price, brand and
  condition, plus bonuses, with signed human-readable reasons for every point.
- **Preference profiles as YAML** (`config/profiles/gravel.yml`) - budget, sizes,
  brands, required/nice-to-have/disqualifying features and dimension weights.
- **SQLite storage** with a `listing` / `listing_version` split that provides
  deduplication, new-offer detection, price-change detection and price history
  from a single content-hash mechanism.
- **Console report**: run summary (found / known / new / changed) plus ranked offers.
- **HTML report** with thumbnails, light and dark themes, written to
  `reports/<profile>_latest.html`.
- **CLI**: `run`, `top`, `history`, `profiles`.
- **24 unit tests** covering extraction, scoring and change detection; all offline.
- Raw payload archiving under `data/raw/` so re-analysis never means re-scraping.

### Fixed
- **Negation guard on disqualifiers.** Sellers advertise the *absence* of defects
  ("rama bez pęknięć", "brak uszkodzeń"), which naive matching read as damage and
  silently rejected some of the best-described offers.
- **Frame sizes derived from OLX inch buckets** are now marked as estimated, capped
  at a 0.75 sub-score and never scored a hard zero, since they are a guess.
- **Suspiciously cheap listings** (below 30% of target budget) are flagged for
  verification instead of being rewarded with a perfect price score.

### Known limitations
- Groupset is recognised in roughly half of listings; the rest fall back to a
  neutral sub-score.
- OLX caps any single search at 1000 results.
- Sold or removed offers are never marked inactive.
- Console and report text is in Polish, matching the marketplace it searches.

[Unreleased]: https://github.com/wookieJ/deal-hunter/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/wookieJ/deal-hunter/releases/tag/v0.1.0
