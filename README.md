# T&T in the Lower Mainland

A small store-location pipeline for T&T Supermarket's 13 Lower Mainland stores. It captures the store locator's JSON response, normalizes addresses and hours, assigns stable IDs, checks each location against an independent geocode, and loads the result into PostGIS for spatial queries and a small API.

I built it as practice for store-location data work. The steps match what a location-data product needs: get the brand's own data, clean it, give each store an identity that survives re-scrapes, flag what looks wrong, and track when stores appear and disappear.

## Getting the data

tntsupermarket.com sits behind Akamai. The first headless Playwright request got a 403 "Access Denied", and I stopped there instead of trying to get past the bot check. `tnt scrape` still exists and exits with an error when it's blocked.

The data in this repo comes from my own browser session instead. I searched BC on the store locator, found the response in DevTools, and imported it with `tnt import`. The locator is a plain REST call that returns `{"code": 200, "data": [...]}`, with one object per store holding `id`, `name`, `address`, `lat`, `lng`, `store_hours` and `special_store_hours`. I had assumed a GraphQL endpoint and filtered on "graphql" in the URL, which matched nothing. The capture code now keeps any JSON response and skips the Google Maps tile labels on the same page, which are JSONP.

The captured response is in `tests/fixtures/tnt_bc_2026-10-29.json`. It came back sorted by distance from the search point, so it may be radius-limited. Comparing a second search from another postal code would confirm whether 13 is every Lower Mainland store.

## Run it

```bash
docker compose up -d db
uv sync
uv run tnt import tests/fixtures/tnt_bc_2026-10-29.json   # or a HAR you saved
uv run tnt clean                      # normalize, geocode (Nominatim, 1 req/s, cached), flag
uv run tnt load                       # every cleaned run in data/clean/ into Postgres
uv run tnt query                      # the three spatial/hours queries
uv run pytest
```

`docker compose up -d` also starts the API on port 8000 (`/stores`, `/stores?flagged=true`, `/stores/nearest?lat=..&lng=..`, `/stores/{id}`). `uv run tnt compare-llm` runs the LLM cleaner next to the regex one and needs `ANTHROPIC_API_KEY`.

## Pipeline

| Stage | Code | Output |
|---|---|---|
| Capture | `scrape.py` | `data/raw/<date>.json`, the untouched JSON responses |
| Extract | `extract.py` | flat records from wherever the store list sits in the response |
| Clean | `address.py`, `hours.py` | street, unit, city, province, postal code; `{"mon": ["09:00", "22:00"]}` |
| Identify | `ids.py` | 16-hex SHA-256 of brand + normalized address |
| Validate | `geocode.py` | flags for missing postal codes and geocodes more than 200 m from T&T's pin |
| Load | `db.py`, `sql/` | `store_snapshots` log, `stores` and `store_hours` rebuilt from it |
| Diff | `diff.py` | added, removed and changed stores between two runs |

Raw data is saved before any parsing, so a parser bug never costs a re-scrape.

## What was messy

On the first run against the real capture, 9 of 13 hours strings and 6 of 13 addresses parsed wrong.

Addresses:

- `147-4800 Kingsway  Burnaby, BC. V5H 4J2`. T&T separates street and city with two spaces, not a comma. "Kingsway" has no street type, so splitting on the last "Street" or "Avenue" can't find the city. The parser now turns a double space into a comma before it collapses whitespace. It used to collapse whitespace first, which threw away that separator.
- `(100 Ave. & 152 St.)  101T-15277 100th Ave  Surrey, BC. V3R 8X2` starts with a cross-street hint in parentheses and has a unit with a letter. The hint goes into a `note` field.
- `#3000-10153 King George Boulevard` has no space between unit and civic number.
- `Unit #MAJ1, 8311 Lansdowne Road  Richmond, British Columbia. V6X 3A4` uses both "Unit" and "#", and spells out the province.
- `2200 Park Royal South, Upper Level  West Vancouver` has a floor between the street and the city. It goes into `note`.
- `1085 Woolridge St, Coquitlam, BC V3K7A9 ` has a postal code with no space, and a trailing space.
- `Unit 100, 19705 Fraser HWY, Township of Langley, BC` has no postal code, and the city is "Township of Langley".

Hours:

- `Monday – Sunday<br />9:00 am - 9:00 pm`. Nine stores put an HTML `<br />` between the day range and the times, and four use `\r\n`. The parser now turns `<br />` into a newline first.
- `Sunday - Thursday \r\n9:00 am - 10:00 pm\r\nFriday – Saturday\r\n8:30 am - 10:30 pm` (Metrotown) splits the week across lines, and Sunday to Thursday wraps past the end of the week.
- `8:00 am - 12:00 am` (Lansdowne) closes at midnight, stored as `24:00`.
- En dashes, hyphens and "to" all appear between days and between times.

Closing times after midnight are written past 24:00 (1 am becomes `25:00`), so "open past 10 pm" is a plain comparison and the database can enforce `close_min > open_min`.

Earlier strings from T&T's Ontario stores are kept as tests too, including `Grand Opening: Oct 8 9am / Store Hours: Mon - Sun, 8am-11pm`. The parser removes the grand-opening clause first, so the weekly hours come out as 08:00 to 23:00, not 09:00 to 23:00.

## What got flagged

Four of 13 stores:

| Store | Flag | Why |
|---|---|---|
| Coquitlam | `geocode_mismatch_710m` | Coquitlam Centre shares civic number 2929 across the whole mall. Nominatim's house-level match is a restaurant at the other end. Needs a person to check. |
| Langley | `missing_postal_code` | T&T lists no postal code. |
| Park Royal | `geocode_street_level` | OSM has no house number for 2200 Park Royal South, only the road. |
| Yaohan Centre | `geocode_street_level` | Same for 3700 No. 3 Road. The road match is a fishing pier 8 km south. |

The first geocoding run flagged 7 stores, and 3 of those flags were the geocoder's fault, not T&T's:

- "2800 E. First Ave" matched a residential street called First Avenue in Port Moody, 13 km away. Nominatim drops the parts of a query it can't match, including the house number, city and postal code.
- "S.W. Marine Drive" and "100th Ave" found nothing.

Two fixes came out of that, each checked against Nominatim on these addresses:

1. `geocode_queries` spells out directions and street types and turns "First" into "1st". If a query misses, it retries without ordinal suffixes, because Surrey's numbered streets are "100 Avenue" in OSM.
2. A match below `place_rank` 30 is a whole street, not a building. It gets `geocode_street_level` and is never compared by distance.

All other flags:

| Flag | Meaning |
|---|---|
| `geocode_failed` | Nominatim found nothing for any spelling |
| `missing_site_coordinates` | the brand's record has no lat/lng |
| `hours_unparsed` | no weekly hours could be read; the raw text is kept |
| `lower_mainland_by_postal_code` | no city, included because the postal code starts with V3 to V7 |

The postal code pattern rejects D, F, I, O, Q and U, which Canada Post never uses, and W or Z as the first letter.

## Queries

`sql/queries.sql` has three queries. Docker wasn't available on the machine I built this on, so I haven't run them against PostGIS yet. The answers below were computed in Python from the cleaned data, and the integration tests in `tests/test_db.py` check the SQL once a database is running.

- Nearest store to Coquitlam Centre: Coquitlam Store, about 740 m from the mall's Nominatim point.
- Stores within 3 km of each other: Yaohan Centre and Lansdowne (1.3 km), and Marine Gateway and Yaohan Centre (2.9 km, across the Fraser River). The second pair is close to the cutoff, where PostGIS's spheroid distance and a spherical formula can disagree by a few meters.
- Stores open past 10 pm: Metrotown on Friday and Saturday (22:30), Marine Gateway (23:00) and Lansdowne (midnight). Kingsway closes at exactly 22:00 and isn't included.

## Store IDs and what breaks them

The ID hashes brand, normalized street, unit, city and province. The postal code is left out because it's the field most often missing or corrected later, and fixing it shouldn't create a new store. T&T's own `id` field is kept as `source_id`, but it's the brand's internal key and could change with a site rebuild. A store gets a new ID when:

- the address text changes in a way `normalize_street` doesn't fold, such as "E. First Ave" vs "East 1st Avenue";
- a unit number is added, removed or corrected;
- the listed city changes, for example "Township of Langley" becoming "Langley";
- the store moves to another unit in the same mall.

The reverse failure is two stores sharing one ID, such as a supermarket and a kiosk at one address with no unit. A production system would match new records to existing IDs by distance and name similarity before minting a new one, and keep the hash as a fallback.

## First seen and last seen

`store_snapshots` gets one row per store per scrape and is never updated in place. `stores.first_seen` and `last_seen` are the min and max `run_date` for each ID, recomputed on every load. Loading runs out of order or re-loading a day gives the same answer. `tnt diff data/clean/A.json data/clean/B.json` lists what changed between two runs.

## Bugs caught while building it

I built this with Claude Code and reviewed each diff. These were the bugs it wrote or nearly wrote:

- The address parser collapsed whitespace before parsing, which erased T&T's double-space separator between street and city.
- The unit pattern was lazy with a digit lookahead, which would have read `#3000-10153` as unit "3".
- It filtered captures on "graphql" in the URL, an assumption the real site didn't match.
- It treated any Nominatim result as a location, including street-level fallbacks 8 to 13 km away.
- It wrote the Coquitlam Centre coordinates from memory and they were about 320 m off. They now come from Nominatim, with the date in a comment.
- The Lower Mainland fallback accepted any postal code starting with V, which also covers Victoria and Kelowna.
- A HAR import read `content.text` as JSON directly, but DevTools base64-encodes some bodies.
- A test named "keeps St in saint names" didn't test that case. `100 St Johns St` normalizes to `100 street johns street`. It's now an `xfail` test that records the gap.
- `ST_MakePoint` takes longitude first. The schema has a comment about it, and the DB test would catch a swap because the distances would be wrong.
- The self-join for nearby pairs uses `a.store_id < b.store_id`. With `<>` every pair comes back twice.
- Distances use `geography`. On `geometry(4326)` the same `ST_DWithin(..., 3000)` would mean 3000 degrees.

## At ChainXY's scale

ChainXY tracks about 6 million locations across more than 8,000 brands. Most of this pipeline would change at that size:

- Capture: one adapter per brand behind a common output schema, per-domain rate limits, and data agreements or official feeds for sites that refuse automated clients.
- Parsing: regex first, because it's cheap and deterministic, and an LLM only for the records regex can't parse. Every LLM output gets validated against a schema, and its disagreements with regex go to human review. Those reviewed cases become test fixtures, the way the T&T capture did here.
- Geocoding: self-hosted Nominatim or a paid geocoder, since the public one allows 1 request per second. Street-level and shared-address matches (malls) need their own handling, because they produced most of the false flags here.
- Identity: match by distance and name before hashing, so a corrected address keeps its ID.
- Change tracking: an incremental merge keyed on `(store_id, run_date)` instead of rebuilding `stores` on each load, with an alert when a brand's store count moves more than expected between runs, since that usually means the scraper broke and not that stores closed.
