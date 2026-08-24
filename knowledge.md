# Knowledge

Last updated: 2026-08-24
Status: Active

## Purpose

Local, manually-run deal hunter: search marketplaces for offers matching defined
criteria, score them against a preference profile, remember what was already seen,
and report what is new or changed. v1 covers OLX + gravel bikes only, but the
structure is built so new sources, categories and analysis steps slot in without a
rewrite.

## Current State

| Field | Value |
|---|---|
| Type | Project |
| Owner | wookieJ |
| Status | Active |
| Tags | `deal-hunter`, `olx`, `scraping`, `bikes`, `scoring`, `sqlite`, `python` |
| Current focus | v0.6: one uniform search-file shape; domain packs optional; rules carry the product logic |
| Next action | Populate `domains/bikes/lookups/geometry.yml` beyond Merida Silex from manufacturer charts |
| Main output | `./run.sh run` -> console summary + `reports/gravel_latest.html` |

## Directory Map

| Path | Purpose |
|---|---|
| `README.md` | Setup and usage. |
| `config/settings.yml` | Runtime settings: rate limit, paths, report size, placeholder home. |
| `config/settings.local.yml` | Personal overrides incl. real home address. Gitignored. |
| `config/profiles/*.local.yml` | Personal profile overrides: measurements, budget, city. Gitignored. |
| `config/profiles/*.yml` | What counts as a good deal. Pure data - tune here, not in code. |
| `src/dealhunter/sources/` | Marketplace adapters (`olx.py`). |
| `src/dealhunter/normalize/` | Free text -> structured attributes (`bikes.py`). |
| `src/dealhunter/scoring/` | Attributes + profile -> 0-100 score with reasons. |
| `src/dealhunter/storage/` | SQLite schema and change detection. |
| `src/dealhunter/report/` | Console and HTML output. |
| `domains/<name>/domain.yml` | Domain pack: extraction rules, scoring dimensions, value model. |
| `domains/<name>/lookups/*.yml` | Reference tables. Never guess these numbers. |
| `domains/<name>/hooks.py` | Optional escape hatch for rules YAML cannot express. |
| `src/dealhunter/travel.py` | Driving distance from home via OSRM, cached. |
| `docs/extending.md` | How to add a source, category or enricher. |
| `data/` | SQLite DB and raw payload archive (gitignored). |
| `reports/` | Generated HTML reports (gitignored). |

## Important Decisions

| Date | Decision | Reason | Consequence |
|---|---|---|---|
| 2026-08-24 | Python + SQLite + curl_cffi | Verified: OLX returns 403 to curl/requests on TLS fingerprint; curl_cffi impersonating Chrome returns 200 | `requests`/`httpx` cannot replace curl_cffi here |
| 2026-08-24 | Use OLX's own JSON API, not HTML scraping | Returns clean structured offers incl. full description; no DOM parsing to break | Depends on an internal API that may change without notice |
| 2026-08-24 | Own extraction layer instead of OLX filters | OLX has frame size only as inch buckets (17-18") and no groupset filter at all, yet groupset drives price | Regex quality is the main determinant of result quality |
| 2026-08-24 | `listing` + `listing_version` split, keyed on content hash | One mechanism yields dedup, new detection, change detection and price history | Price history exists from day one, no migration needed later |
| 2026-08-24 | Scoring profile is YAML data, not code | Retuning preferences must not require Python changes | New category = new profile + normalizer, not a rewrite |
| 2026-08-24 | Rule-based scoring only in v1; `ENRICHERS` list left empty | Deterministic, free, debuggable; LLM can append later | LLM/image analysis is an append, not a refactor |
| 2026-08-24 | Do NOT auto-deactivate offers missing from a run | A run only sees the first N pages; absence usually means pushed out by newer offers, not sold | "Offer gone" detection needs per-listing re-check (post-MVP) |
| 2026-08-24 | Negation guard on disqualifiers | Sellers advertise absence of defects ("bez pęknięć ramy"); naive matching hid good offers | Best-described offers are no longer wrongly rejected |
| 2026-08-24 | Budget fit is a score multiplier, not a weighted dimension | A flat sum let a 5000 PLN bike win on groupset alone; the owner's sweet spot sits well below the top of the range | Expensive bikes keep ~75% of spec score - must be exceptional to win, but still surface |
| 2026-08-24 | Sizing scored on manufacturer geometry (reach/stack) where known | Nominal sizes are not comparable across brands or generations - gen-2 Silex M has more reach than gen-1 M | Needs a geometry table; label-based sizing is confidence-capped and marked |
| 2026-08-24 | Never invent geometry numbers | Guessed reach/stack yields confident, wrong fit advice | Table ships with Merida Silex only (owner-supplied); rest falls back to labels |
| 2026-08-24 | Search area and home address kept separate | One field cannot serve both: the search area is where to hunt (a search parameter), home is where the owner lives (report distances only) | `search.<source>.area` narrows the hunt and the 1000-cap; `proximity_to` picks the scoring anchor |
| 2026-08-24 | Personal values in gitignored `*.local.yml` overrides | Repo is public; home coordinates, height, inseam and budget are all personal | Tracked `settings.yml` and `profiles/gravel.yml` are examples; local files deep-merge over them; tests pin `use_local=False` so CI is deterministic |
| 2026-08-24 | Report written to one stable path, overwritten each run | A per-run filename cannot be bookmarked and accumulates copies of a view only interesting in its latest state | `reports/<profile>_latest.html`; dated archives opt-in via `report.keep_dated_copies` |
| 2026-08-24 | One uniform search-file shape, domain optional | Dedicated per-product preference keys were a hidden mapping every domain had to repeat | `name/source/search/budget/scoring` everywhere; product logic lives in text rules |
| 2026-08-24 | Rules compose as a weighted criterion, negatives subtract | Adding points on top double-counted against a pack's dimensions and pushed offers to 100 | `weights.rules` (default 40); negative points bypass the clamp |
| 2026-08-24 | Negation guard belongs to the engine, not a pack | A search without a pack lost it and penalised "brak martwych pikseli" as a defect | Universal `DEFAULT_NEGATION`; caught on live data |
| 2026-08-24 | Keyword rules (`rules:`) as the short path to a score | Declarative dimensions needed an extractor plus a dimension just to say 'nvidia is good' | One YAML line; works in a domain pack or a single profile |
| 2026-08-24 | Product knowledge purged from reporters and value model | Reporters read `frame_size_cm`/`groupset` directly; `value.py` defaulted to `groupset_tier` with bike prices baked in | `display:` block per domain; a test walks engine source and fails on leakage |
| 2026-08-24 | No domain `value_model` means no estimate at all | Engine defaults would be a guess dressed as data | Bargain bonus simply does not fire |
| 2026-08-24 | Engine split from YAML domain packs | Tool was a bike script with an engine attached; new product types required code | `domains/<name>/` carries extraction + scoring; new search = one YAML file |
| 2026-08-24 | Unknown dimensions leave the weight normalisation | Sparse listings were scored as if features were absent - grading the description, not the product; regex over inflected Polish misses things routinely | A miss now costs certainty, not points |
| 2026-08-24 | Low confidence regresses toward a neutral prior | Renormalisation alone let 22% of weight set 100% of score; an empty listing hit 94/100 | `unknown_prior` in the domain; confidence reported in every score |
| 2026-08-24 | One report with a tab per search | A file per profile does not scale past one search | `reports/index.html`, selected tab remembered |
| 2026-08-24 | Distance scored, never filtered | Owner prefers a home region but wants exceptional offers elsewhere to surface | Uses lat/lon OLX returns per offer - no geocoding needed |
| 2026-08-24 | Seller type removed from scoring | Owner wants shops and outlets to compete equally | `private_seller` bonus dropped |
| 2026-08-24 | Scores carry a profile fingerprint; stale ones are rebuilt from archived payloads | Offers dropping out of the search window kept scores from old rules and still ranked - a 5700 PLN bike showed above a 5500 PLN hard limit | Profile edits are self-healing; `run` rescores automatically, `rescore` on demand, all offline |
| 2026-08-24 | Driving distance via public OSRM, plain urllib | OSRM rejects browser-impersonating clients that OLX requires | Two HTTP clients in one codebase, deliberately |

## Architecture Or Structure

```
Source ──► Normalizer ──► Enricher* ──► Scorer ──► Storage ──► Reporter
(OLX)      (regex)        (empty)       (profile)  (SQLite)    (console + HTML)
```

Each arrow is a Protocol, so a layer can be swapped without touching the others.
`pipeline.run()` is the only place that knows the full sequence.

Storage tables: `run`, `listing`, `listing_version`, `listing_attrs`, `score`.
A new `listing_version` row is written only when `sha256(price|title|description)`
differs from the previous one - that is the whole change-detection mechanism.

OLX bike category ids: gravel 4242, MTB 1651, road 1652, cross 1648,
trekking 1653, city 1650, electric 1649, folding 4243, kids 1681, all bikes 461.

## Commands And Workflows

| Command / Workflow | Purpose | Notes |
|---|---|---|
| `./setup.sh` | Create `.venv`, install deps | Once per machine |
| `./install-cli.sh` | Put `deal` on PATH | Symlinks into a PATH dir; `deal run` works anywhere |
| `./run.sh run -p gravel` | Full search, score, store, report | ~12 s for ~210 offers |
| `./run.sh run -l 40` | Short run for testing | Avoids hammering OLX |
| `./run.sh top -n 20` | Best offers from DB without fetching | Free, offline |
| `./run.sh history olx:<id>` | Price history of one offer | |
| `./run.sh rescore` | Recompute scores after a profile edit | Offline, uses archived payloads |
| `./run.sh reset` | Wipe collected offers | Keeps `travel_cache` unless `--all` |
| `./test.sh` | 79 unit tests | Extraction, scoring, rules, geometry, value, dedup, engine purity |

## Dependencies And External Services

| Dependency / Service | Purpose | Notes |
|---|---|---|
| OLX internal JSON API | Offer data | `https://www.olx.pl/api/v1/offers/`; unofficial, may change |
| `curl_cffi` | Chrome TLS impersonation | Mandatory - plain HTTP clients get 403 |
| `PyYAML` | Config and profiles | |
| `Jinja2` | HTML report | |

## Known Issues And Constraints

| Date | Issue / Constraint | Impact | Status |
|---|---|---|---|
| 2026-08-24 | Groupset recognised in ~50% of offers | Others fall back to a neutral 0.4 sub-score | Open - expand `GROUPSETS`, or use an LLM enricher |
| 2026-08-24 | OLX caps any single search at 1000 results | Very broad profiles cannot be fully enumerated | Accepted - narrow with price/category filters |
| 2026-08-24 | Sold/removed offers are never marked inactive | DB grows with stale offers | Open - needs per-listing detail re-check |
| 2026-08-24 | Relies on an undocumented internal API | Could break or start blocking at any time | Accepted - rate limited to 1 req/s, raw payloads archived |
| 2026-08-24 | Frame size from OLX inch buckets is a guess | Marked `frame_size_estimated`, capped sub-score | Accepted by design |
| 2026-08-24 | Geometry table covers Merida Silex only | Every other model falls back to label-based sizing | Open - fill from manufacturer charts |
| 2026-08-24 | Market value is a heuristic, not comparable sales | Bargain bonus can be wrong on unusual builds | Open - replace with reference prices from listing history |

## Open Questions

| Date | Question | Owner | Status |
|---|---|---|---|
| 2026-08-24 | Which further models to add to `config/geometry.yml` first | wookieJ | Open - candidates: Cube Nuroad, Kross Esker, Romet Aspre, Specialized Diverge |

## Changelog

| Date | Change | Notes |
|---|---|---|
| 2026-08-24 | MVP built and verified against live OLX | 212 offers found, dedup and price-change detection confirmed |
| 2026-08-24 | v0.2: value-based scoring, geometry sizing, travel distance | Profile tuned to the owner via a gitignored local override. 49 tests |

## Context Recovery

To resume work:

1. Read workspace `CLAUDE.md`.
2. Read workspace `knowledge.md`.
3. Read this file.
4. For extension work read `docs/extending.md`; for tuning read `config/profiles/gravel.yml`.
5. Continue from `Next action`.
