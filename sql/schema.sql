CREATE EXTENSION IF NOT EXISTS postgis;

-- Everything here is rebuilt by `tnt load` from the cleaned runs in
-- data/clean/, which are the history. Dropping first means a schema change
-- applies on the next load with no migration. (Tables from before the
-- location/store split are dropped too.)
DROP TABLE IF EXISTS store_events, location_hours, locations, location_snapshots,
    store_hours, stores, store_snapshots CASCADE;

-- One row per location per run.
CREATE TABLE location_snapshots (
    location_id text NOT NULL,
    run_date    date NOT NULL,
    record      jsonb NOT NULL,
    PRIMARY KEY (location_id, run_date)
);

-- One row per place. location_id never moves; store_id is the brand store
-- that was there most recently, which can have moved on (ended_reason).
CREATE TABLE locations (
    location_id   text PRIMARY KEY,
    store_id      text NOT NULL,
    brand         text NOT NULL,
    banner        text NOT NULL,
    name          text NOT NULL,
    street        text,
    unit          text,
    city          text,
    province      text,
    postal_code   text,
    phone         text,
    -- geography, not geometry: distances come back in meters on the spheroid.
    -- Points are (lng, lat); getting that backwards puts Vancouver in Antarctica.
    site_geog     geography(Point, 4326),
    -- Only building-level geocodes; a street-level match isn't a location.
    geocoded_geog geography(Point, 4326),
    flags         text[] NOT NULL DEFAULT '{}',
    record        jsonb NOT NULL,
    first_seen    date NOT NULL,
    last_seen     date NOT NULL,
    -- In the most recent run. Ended locations keep their row and history but
    -- drop out of the queries and the API's default listing.
    active        boolean NOT NULL,
    ended_reason  text CHECK (ended_reason IN ('closed', 'relocated'))
);

-- Best available point: the brand's own pin, else our geocode.
CREATE VIEW location_points AS
SELECT l.*, COALESCE(site_geog, geocoded_geog) AS geog FROM locations l;

-- Opening hours as minutes since midnight; close can exceed 1440 (past midnight).
CREATE TABLE location_hours (
    location_id text NOT NULL REFERENCES locations ON DELETE CASCADE,
    day         text NOT NULL CHECK (day IN ('mon','tue','wed','thu','fri','sat','sun')),
    open_min    int NOT NULL,
    close_min   int NOT NULL CHECK (close_min > open_min),
    PRIMARY KEY (location_id, day)
);

-- What happened to each brand store, run by run (src/tnt/events.py).
CREATE TABLE store_events (
    run_date         date NOT NULL,
    type             text NOT NULL CHECK (type IN ('opened', 'closed', 'relocated', 'reopened')),
    store_id         text NOT NULL,
    location_id      text NOT NULL,
    from_location_id text
);

CREATE INDEX locations_site_geog_idx ON locations USING gist (site_geog);
CREATE INDEX locations_geocoded_geog_idx ON locations USING gist (geocoded_geog);
CREATE INDEX store_events_store_idx ON store_events (store_id);
