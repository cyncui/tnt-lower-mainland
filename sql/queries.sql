-- name: nearest_to_coquitlam_centre
-- Coquitlam Centre, 2929 Barnet Hwy (Nominatim, 2026-10-29). ST_MakePoint takes (lng, lat).
SELECT location_id, name, street, city,
       round(ST_Distance(geog, ST_MakePoint(-122.7986, 49.2798)::geography)) AS meters
FROM location_points
WHERE geog IS NOT NULL AND active
ORDER BY geog <-> ST_MakePoint(-122.7986, 49.2798)::geography
LIMIT 1;

-- name: stores_within_3km
-- a.location_id < b.location_id lists each pair once and skips self-pairs;
-- <> would return every pair twice.
SELECT a.name AS store_a, b.name AS store_b, a.city AS city_a, b.city AS city_b,
       round(ST_Distance(a.geog, b.geog)) AS meters
FROM location_points a
JOIN location_points b
  ON a.location_id < b.location_id
 AND ST_DWithin(a.geog, b.geog, 3000)
WHERE a.active AND b.active
ORDER BY meters;

-- name: open_past_10pm
-- "Past 10 pm" means closing after 22:00, not at it. One row per store and
-- closing time, with the days it applies to in week order.
SELECT s.name, s.city,
       string_agg(h.day, ',' ORDER BY array_position(ARRAY['mon','tue','wed','thu','fri','sat','sun'], h.day)) AS days,
       to_char(make_interval(mins => h.close_min), 'HH24:MI') AS closes
FROM locations s
JOIN location_hours h USING (location_id)
WHERE h.close_min > 22 * 60 AND s.active
GROUP BY s.name, s.city, h.close_min
ORDER BY h.close_min DESC, s.name;
