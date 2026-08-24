# Extending Deal Hunter

The engine knows nothing about any product. What a product *is* - how to read its
specs out of a listing, what makes one offer better than another - lives in a
**domain pack**. Adding a new kind of product is a directory of YAML; adding a new
search is a single YAML file.

```
domains/<name>/
    domain.yml          extraction rules, scoring dimensions, value model
    lookups/*.yml       reference tables: model generation -> real specs
    hooks.py            optional, only for what YAML cannot express
```

## Add a new search (no code, no new domain)

Copy `config/profiles/gravel.yml`, point it at another category and adjust the
preferences. `config/profiles/mtb.yml` is exactly that: a second search over the
same `bikes` domain, written without a line of Python.

```yaml
name: mtb
domain: bikes
search:
  olx:
    category_id: 1651
    area: { name: Warszawa, city_id: 17871, lat: 52.2297, lon: 21.0122, radius_km: 100 }
preferences: { ... }
weights:     { size: 28, groupset: 24, features: 18, condition: 12, location: 10, brand: 8 }
```

Then `deal run -p mtb`. It gets its own tab in the report.

## Add a new product type

Copy `domains/bikes/` and rewrite `domain.yml`. Its three parts:

**1. `extract:`** — how to turn free text into attributes. Each rule names a type:

| Type | Use for |
|---|---|
| `patterns` | first matching regex wins (bike type, brakes, material) |
| `dictionary` | a list of names matched as words, title preferred (brand) |
| `tiered` | label plus a 0-100 quality tier (groupset, CPU generation) |
| `numeric` | a captured number with range checks, unit conversion and marketplace-bucket fallbacks |
| `enum_regex` | one token from a closed set (S/M/L) |
| `regex_value` | a single regex whose first group is the value |
| `year` | four-digit years in range, newest wins |
| `param` | straight from a marketplace-supplied field |
| `model_after_brand` | the words following a recognised brand in the title |
| `lookup` | a reference table: brand + model + variant -> known specs |

**2. `dimensions:`** — how attributes become a score:

| Type | Use for |
|---|---|
| `range_chain` | ordered sources, best first, each with a confidence cap (geometry, then the size label) |
| `tier` | an attribute holding a 0-100 quality tier |
| `preference_list` | preferred / acceptable / avoided values |
| `flag_coverage` | weighted presence of features |
| `enum_map` | a fixed value-to-score map (condition) |
| `distance` | proximity to the search area or home |

A dimension setting can be redirected into the profile with `<key>_from: some.path`,
so the domain defines the *mechanism* and the profile supplies *your* numbers.

**3. `value_model:`** — a rough market price from the spec, used to spot bargains.

## Two rules worth respecting

**Unknown is not bad.** Dimensions that cannot be determined drop out of the
weight normalisation rather than scoring low, and the result then regresses
toward `unknown_prior` in proportion to what is unknown. A terse listing is
uncertain, not inferior — and it must not be able to top the ranking either. The
reported confidence carries that, not the score.

**Extraction is regex over inflected text and will miss things.** That is
tolerable precisely because a miss produces *unknown*, which costs nothing but
certainty. Do not build rules that punish silence. Hard rejection is reserved for
`disqualifying:` and `required:` in a profile, which you opt into explicitly; for
anything softer use `penalties:`.

## hooks.py — the escape hatch

Only when a rule genuinely cannot be declared:

```python
from dealhunter import domains

@domains.register_extractor("bikes", "my_type")
def my_extractor(rule, attrs, text, title, params, raw):
    return {"my_attribute": ...}

@domains.register_dimension("bikes", "my_dimension")
def my_dimension(cfg, attrs, raw, prefs):
    from dealhunter.scoring.engine import Result
    return Result(0.8, "explained in one human sentence")
```

The YAML then refers to `type: my_type`. Keep this rare: everything here is
invisible to anyone reading the domain's YAML.

## Add a marketplace

Implement `search(spec)` and `parse(payload)` in `src/dealhunter/sources/<name>.py`
and register it in `sources/base.py`. Expect bot protection to be the hard part,
not parsing — check whether `curl_cffi` impersonation is enough before writing it.

## Other extension points

- **LLM or image analysis**: append to `pipeline.ENRICHERS`. Enrichers run after
  extraction and before scoring, so anything they add is immediately scorable.
  Cache by `raw.content_hash` — it only changes when the listing text does.
- **Real reference prices**: `listing_version` already holds every price ever
  seen; compute buckets from it and replace the `value_model` heuristic.
- **Notifications**: read the stats dict `pipeline.run()` returns, or add a
  reporter under `report/`.
- **Scheduled runs**: `deal run` is idempotent; a cron or launchd entry is enough.
- **MCP server**: expose `Repo.top` and `Repo.price_history` read-only over the
  same SQLite file.
