# Deal Hunter - Project Instructions

Local marketplace deal hunter. Read this before changing anything here; it is a
router, not a knowledge dump.

## Orientation

| Need | Read |
|---|---|
| Project state, decisions, known issues | `knowledge.md` |
| Setup and usage | `README.md` |
| Adding a source, category, enricher | `docs/extending.md` |
| What changed and when | `CHANGELOG.md` |
| What counts as a good deal | `config/profiles/*.yml` |

## Non-negotiables

- **`curl_cffi` is mandatory for OLX.** OLX and Allegro return HTTP 403 to `curl`,
  `requests` and `httpx` based on TLS fingerprint. Never "simplify" the source
  adapter to `requests` - it will 403. Verified 2026-08-24.
- **Preferences live in YAML, never in Python.** If a change means "I want
  different bikes", it belongs in a profile. Only mechanism changes belong in code.
- **Never remove the rate limit** (`settings.yml: http.rate_limit_s`). This tool is
  a guest on someone else's servers.
- **Do not auto-deactivate offers missing from a run.** A run only sees the first N
  pages, so absence means "pushed out by newer offers" far more often than "sold".
- **Scoring must stay explainable.** Every dimension returns a sub-score *and* a
  human sentence. A score with no reasons attached is a bug.
- **Budget fit is a multiplier, never a weighted dimension.** Turning it back into
  one lets expensive, well-specced bikes outrank sensibly priced ones, which defeats
  the purpose of the tool. See the `scoring/bikes.py` docstring.
- **Never trust a size label over geometry.** If `config/geometry.yml` has the model,
  reach/stack wins; label-based sizing must stay confidence-capped.
- **Never invent geometry numbers.** Entries come from manufacturer charts and carry
  a `verified` flag. Guessing reach/stack produces confident, wrong fit advice.
- **Search area and home are different things.** The search area is a profile search
  parameter (where to hunt); home is a setting (where the user lives) and drives only
  the report's travel distances. Never merge them back into one field.
- **Never commit a home address.** Personal values belong in the gitignored
  `config/settings.local.yml`; `config/settings.yml` keeps a placeholder.
- **Every stored score carries a profile fingerprint.** Anything that changes how
  scores are produced must be inside `config.profile_fingerprint`'s input, or stale
  scores will survive a profile change and pollute the ranking.
- **The travel module must not use the curl_cffi session.** OSRM rejects
  browser-impersonating clients; OLX requires one. Opposite requirements, on purpose.

## This repo is public-facing

It is published on GitHub as a portfolio piece, so keep it cloneable by a stranger:
- README quickstart must work from a clean clone.
- All code, comments, docs and commit messages in English. Runtime output aimed at
  the user stays Polish, matching the marketplace being searched.
- Update `CHANGELOG.md` for user-visible changes and `knowledge.md` for decisions.
- Tests must stay offline - never add a test that hits OLX.

## Conventions

- Python 3.11+, stdlib first. Three dependencies only; justify any fourth.
- Layers talk through the Protocols in each `base.py`. Keep `pipeline.py` the only
  module that knows the full sequence.
- New attribute keys are free (`Attributes` is an open dict); new DB columns are not.
- Verify with `./test.sh`, and for scraping changes with `./run.sh run -l 25`.
