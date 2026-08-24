# Extending Deal Hunter

Every search is one YAML file with the same shape, whatever you are buying:

```yaml
name: <search name>
source: olx
domain: <optional pack>

search:   { category_id:, queries:, price: {from:, to:}, max_pages:, sort_by:, area: {...} }
budget:   { target:, comfortable_max:, soft_max:, hard_max: }
scoring:  { weights: {...}, rules: [...] }
```

No product-specific fields, so nothing has to be mapped per domain. Everything you
want to say about what you are buying goes into `scoring.rules`.

## Add a search

Copy any file in `config/profiles/`, change the category and the rules. That is
the whole procedure. `config/profiles/monitor.yml` declares no domain at all and
works: price, location and condition are universal, and its rules do the rest.

## Rules

```yaml
rules:
  - name: high refresh rate
    any: ['\b(144|165|240)\s*hz\b']
    points: 20
  - name: dead pixels
    any: ['martw\w*\s*piksel\w*']
    points: -18
  - name: broken
    any: ['nie\s*dzia[lł]a']
    reject: true
  - name: must have a receipt
    any: ['paragon', 'faktur\w*']
    require: true          # absent -> rejected
```

- Entries in `any` are regexes, so `i7` works as-is and `zalan\w*` covers Polish
  inflection.
- `scope: title` narrows a rule to the title; the default also covers the
  description and the marketplace's own fields.
- Positive points build one weighted criterion (`weights.rules`, default 40).
  Negative points subtract directly, so a mentioned defect always costs.
- Negation is handled by the engine: *"brak martwych pikseli"* does not fire the
  dead-pixel rule.

## Add a marketplace

Implement `search(spec)` and `parse(payload)` in `src/dealhunter/sources/<name>.py`
and register it in `sources/base.py`. Expect bot protection to be the hard part,
not parsing.

## Optional: a domain pack

Reach for one only when rules genuinely are not enough — numeric ranges, quality
tiers, or a reference table mapping a model to its real specification. A pack is
one YAML file, `domains/<name>/domain.yml`, that a search opts into with
`domain: <name>`.

## Add a new product type

Copy `domains/bikes/` or `domains/laptops/` and rewrite `domain.yml`. Both are real, working packs that share no vocabulary and no code. Its three parts:

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
The engine has no prices of its own: omit this block and no estimate is made and
no bargain bonus awarded, which is better than guessing.

**4. `display:`** — which attributes the reports show. The engine renders what this
names and knows nothing else about your product:

```yaml
display:
  summary: [{attrs: [cpu], fallback: 'CPU ?'},
            {attrs: [ram_gb], suffix: {ram_gb: ' GB RAM'}, fallback: 'RAM ?'}]
  chips: [storage_raw, screen_raw, gpu, model_year]
```

**5. `profile_schema.defaults:`** and **`default_weights:`** — the preference keys
your dimensions read and their defaults, merged under whatever a profile sets, so
profiles stay short and no profile needs to know another domain's vocabulary.

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
