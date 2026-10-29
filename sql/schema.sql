CREATE EXTENSION IF NOT EXISTS postgis;

-- One row per store per scrape. first_seen / last_seen are derived from
-- this, so re-running a scrape never overwrites history.
CREATE TABLE IF NOT EXISTS store_snapshots (
    store_id   text NOT NULL,
    run_date   date NOT NULL,
    record     jsonb NOT NULL,
    PRIMARY KEY (store_id, run_date)
);

CREATE TABLE IF NOT EXISTS stores (
    store_id      text PRIMARY KEY,
    brand         text NOT NULL,
    name          text,
    street        text,
    unit          text,
    city          text,
    province      text,
    postal_code   text,
    raw_address   text NOT NULL,
    raw_hours     text NOT NULL,
    hours         jsonb NOT NULL,
    -- geography, not geometry: distances come back in meters on the spheroid.
    -- Points are (lng, lat); getting that backwards puts Vancouver in Antarctica.
    site_geog     geography(Point, 4326),
    geocoded_geog geography(Point, 4326),
    flags         text[] NOT NULL DEFAULT '{}',
    first_seen    date NOT NULL,
    last_seen     date NOT NULL
);

-- Best available location: the brand's own pin, else our geocode.
CREATE OR REPLACE VIEW store_locations AS
SELECT s.*, COALESCE(site_geog, geocoded_geog) AS geog FROM stores s;

-- Opening hours as minutes since midnight; close can exceed 1440 (past midnight).
CREATE TABLE IF NOT EXISTS store_hours (
    store_id   text NOT NULL REFERENCES stores ON DELETE CASCADE,
    day        text NOT NULL CHECK (day IN ('mon','tue','wed','thu','fri','sat','sun')),
    open_min   int NOT NULL,
    close_min  int NOT NULL CHECK (close_min > open_min),
    PRIMARY KEY (store_id, day)
);

CREATE INDEX IF NOT EXISTS stores_site_geog_idx ON stores USING gist (site_geog);
CREATE INDEX IF NOT EXISTS stores_geocoded_geog_idx ON stores USING gist (geocoded_geog);
