-- name: nearest_to_coquitlam_centre
-- Coquitlam Centre, 2929 Barnet Hwy (Nominatim, 2026-10-29). ST_MakePoint takes (lng, lat).
SELECT store_id, name, street, city,
       round(ST_Distance(geog, ST_MakePoint(-122.7986, 49.2798)::geography)) AS meters
FROM store_locations
WHERE geog IS NOT NULL
ORDER BY geog <-> ST_MakePoint(-122.7986, 49.2798)::geography
LIMIT 1;

-- name: stores_within_3km
-- a.store_id < b.store_id lists each pair once and skips self-pairs;
-- a.store_id <> b.store_id would return every pair twice.
SELECT a.name AS store_a, b.name AS store_b, a.city AS city_a, b.city AS city_b,
       round(ST_Distance(a.geog, b.geog)) AS meters
FROM store_locations a
JOIN store_locations b
  ON a.store_id < b.store_id
 AND ST_DWithin(a.geog, b.geog, 3000)
ORDER BY meters;

-- name: open_past_10pm
-- "Past 10 pm" means closing after 22:00, not at it. One row per store and
-- closing time, with the days it applies to in week order.
SELECT s.name, s.city,
       string_agg(h.day, ',' ORDER BY array_position(ARRAY['mon','tue','wed','thu','fri','sat','sun'], h.day)) AS days,
       to_char(make_interval(mins => h.close_min), 'HH24:MI') AS closes
FROM stores s
JOIN store_hours h USING (store_id)
WHERE h.close_min > 22 * 60
GROUP BY s.name, s.city, h.close_min
ORDER BY h.close_min DESC, s.name;
