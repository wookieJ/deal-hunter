# Extending Deal Hunter

Each planned feature maps to exactly one seam. Nothing below requires touching
`pipeline.py` beyond, at most, one line.

## Add a marketplace (Allegro, Sprzedajemy, ...)

1. Create `src/dealhunter/sources/<name>.py` with a class exposing
   `name` and `search(spec) -> Iterator[RawListing]`.
2. Register it in `sources/base.py::get_source`.
3. Reference it as the key under `search:` in a profile.

The rest of the pipeline never learns a new source exists. Expect the hard part
to be bot protection, not parsing - check whether `curl_cffi` impersonation is
enough before writing the adapter.

## Add a product category (cameras, tools, ...)

1. `src/dealhunter/normalize/<category>.py` - free text to attribute dict.
2. `src/dealhunter/scoring/<category>.py` - attributes plus profile to `ScoreResult`.
3. Register both in the matching `base.py::get_*`.
4. Set `category: <name>` in the profile.

`Attributes` is an open dict precisely so a new category adds new keys without
schema or storage changes.

## Add LLM analysis of descriptions

Append a callable to `pipeline.ENRICHERS`:

```python
def llm_enricher(attrs: Attributes, raw: RawListing) -> Attributes:
    attrs["llm_condition_notes"] = ...      # new keys only
    attrs["flags"].append("seller_seems_honest")
    return attrs
```

Enrichers run after the regex normalizer and before scoring, so anything they add
is immediately available to the scorer. Cache by `raw.content_hash` - it only
changes when the offer text actually changes, so you pay per real change, not per
run.

## Add image analysis

Same seam as above. `raw.photos` holds up to six 600x450 URLs. Cache aggressively.

## Add price-history comparison / deal detection

The data is already there: `listing_version` holds every price ever seen, and
`listing_attrs` holds the specs. Compute a reference price per
(brand, groupset tier, frame size) bucket, then add it as another weighted
dimension in `scoring/bikes.py` and a weight in the profile.

## Add notifications

Read from the DB after `pipeline.run()` returns its stats dict, or add a reporter
under `report/`. The run already knows exactly which offers were new or changed.

## Add scheduled runs

`./run.sh run -p gravel` is idempotent and safe to repeat, so a launchd/cron entry
is all it takes. Nothing in the code needs to change.

## Add an MCP server

Expose read-only queries over the same SQLite file (`Repo.top`,
`Repo.price_history`). Keep the DB the single source of truth so the CLI and MCP
never disagree.
