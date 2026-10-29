# T&T in the Lower Mainland

A small store-location pipeline for T&T Supermarket's Lower Mainland stores. It captures the store locator's GraphQL response, normalizes addresses and hours, assigns stable IDs, checks each location against an independent geocode, and loads the result into PostGIS for spatial queries and a small API.

I built it as practice for store-location data work. The steps match what a location-data product needs: get the brand's own data, clean it, give each store an identity that survives re-scrapes, flag what looks wrong, and track when stores appear and disappear.

## Status

The automated scrape did not run. tntsupermarket.com sits behind Akamai, and the first headless Playwright request got a 403 "Access Denied". I stopped there instead of trying to get past the bot check. The pipeline doesn't care how the raw response arrives, so `tnt import` accepts a HAR or JSON saved from a normal browser session. The rest of the pipeline is tested against the real messy strings below and a synthetic fixture with an assumed response shape. Field mapping in `src/tnt/extract.py` still needs confirming against a real capture.

## Run it

```bash
docker compose up -d db
uv sync
uv run playwright install chromium
uv run tnt scrape                     # or: uv run tnt import ~/Downloads/tnt.har
uv run tnt clean                      # normalize, geocode (Nominatim, 1 req/s, cached), flag
uv run tnt load                       # every cleaned run in data/clean/ into Postgres
uv run tnt query                      # the three spatial/hours queries
uv run pytest
```

`docker compose up -d` also starts the API on port 8000 (`/stores`, `/stores?flagged=true`, `/stores/nearest?lat=..&lng=..`, `/stores/{id}`). `uv run tnt compare-llm` runs the LLM cleaner next to the regex one and needs `ANTHROPIC_API_KEY`.

## Pipeline

| Stage | Code | Output |
|---|---|---|
| Scrape | `scrape.py` | `data/raw/<date>.json`, the untouched GraphQL responses |
| Extract | `extract.py` | flat records from wherever the store list sits in the response |
| Clean | `address.py`, `hours.py` | street, unit, city, province, postal code; `{"mon": ["09:00", "22:00"]}` |
| Identify | `ids.py` | 16-hex SHA-256 of brand + normalized address |
| Validate | `geocode.py` | flags for missing postal codes and geocodes more than 200 m from T&T's pin |
| Load | `db.py`, `sql/` | `store_snapshots` log, `stores` and `store_hours` rebuilt from it |
| Diff | `diff.py` | added, removed and changed stores between two runs |

Raw data is saved before any parsing, so a parser bug never costs a re-scrape.

## What was messy

These strings came from tntsupermarket.com:

- `#Y007 - 1 Promenade Circle Thornhill, ON. L4J 4P8` has a mall unit with a letter, no comma between street and city, and a period after the province. The parser splits on the last street-type word ("Circle") to find the city.
- `26 Edward St, Toronto` has no province or postal code. The parser leaves them null and doesn't infer them from the city.
- `Unit 1115, 1800 Sheppard Avenue East` has no city at all. "East" is a direction, so it stays part of the street and doesn't become the city.
- `Monday – Sunday 9:00 am - 10:00 pm` uses an en dash between days and a hyphen between times. The day and time patterns accept both.
- `Grand Opening: Oct 8 9am / Store Hours: Mon - Sun, 8am-11pm` contains two times that look like opening hours. The parser removes the grand-opening clause first and keeps it as a note, so the weekly hours come out as 08:00 to 23:00, not 09:00 to 23:00.

Closing times after midnight are written past 24:00 (1 am becomes `25:00`), so "open past 10 pm" is a plain comparison and the database can enforce `close_min > open_min`.

## What gets flagged

| Flag | Meaning |
|---|---|
| `missing_postal_code` | no valid Canadian postal code in the address |
| `geocode_mismatch_<n>m` | Nominatim puts the address more than 200 m from the brand's coordinates |
| `geocode_failed` | Nominatim found nothing |
| `missing_site_coordinates` | the brand's record has no lat/lng |
| `hours_unparsed` | no weekly hours could be read; the raw text is kept |
| `lower_mainland_by_postal_code` | no city, included because the postal code starts with V3 to V7 |

The postal code pattern rejects D, F, I, O, Q and U, which Canada Post never uses, and W or Z as the first letter.

## Store IDs and what breaks them

The ID hashes brand, normalized street, unit, city and province. The postal code is left out because it's the field most often missing or corrected later, and fixing it shouldn't create a new store. A store gets a new ID when:

- the address text changes in a way `normalize_street` doesn't fold, such as "No. 3 Rd" vs "Number 3 Road";
- a unit number is added, removed or corrected;
- the listed city changes, for example a border store listed as Burnaby one week and Vancouver the next;
- the store moves to another unit in the same mall.

The reverse failure is two stores sharing one ID, such as a supermarket and a kiosk at one address with no unit. A production system would match new records to existing IDs by distance and name similarity before minting a new one, and keep the hash as a fallback.

## First seen and last seen

`store_snapshots` gets one row per store per scrape and is never updated in place. `stores.first_seen` and `last_seen` are the min and max `run_date` for each ID, recomputed on every load. Loading runs out of order or re-loading a day gives the same answer. `tnt diff data/clean/A.json data/clean/B.json` lists what changed between two runs.

## Bugs caught while building it

I built this with Claude Code and reviewed each diff. These were the bugs it wrote or nearly wrote:

- It wrote the Coquitlam Centre coordinates from memory and they were about 320 m off. They now come from Nominatim, with the date in a comment.
- The Lower Mainland fallback accepted any postal code starting with V, which also covers Victoria and Kelowna.
- A HAR import read `content.text` as JSON directly, but DevTools base64-encodes some bodies.
- A test named "keeps St in saint names" didn't test that case. `100 St Johns St` normalizes to `100 street johns street`. It's now an `xfail` test that records the gap.
- `ST_MakePoint` takes longitude first. The schema has a comment about it, and the DB test would catch a swap because the distances would be wrong.
- The self-join for nearby pairs uses `a.store_id < b.store_id`. With `<>` every pair comes back twice.
- Distances use `geography`. On `geometry(4326)` the same `ST_DWithin(..., 3000)` would mean 3000 degrees.

## At ChainXY's scale

ChainXY tracks about 6 million locations across more than 8,000 brands. Most of this pipeline would change at that size:

- Scraping: one adapter per brand behind a common output schema, per-domain rate limits, and data agreements or official feeds for sites that refuse automated clients.
- Parsing: regex first, because it's cheap and deterministic, and an LLM only for the records regex can't parse. Every LLM output gets validated against a schema, and its disagreements with regex go to human review. Those reviewed cases become test fixtures.
- Geocoding: self-hosted Nominatim or a paid geocoder, since the public one allows 1 request per second.
- Identity: match by distance and name before hashing, so a corrected address keeps its ID.
- Change tracking: an incremental merge keyed on `(store_id, run_date)` instead of rebuilding `stores` on each load, with an alert when a brand's store count moves more than expected between runs, since that usually means the scraper broke and not that stores closed.
