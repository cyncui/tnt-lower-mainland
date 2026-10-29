"""Nominatim geocoding and distance checks.

Nominatim's usage policy: at most 1 request per second, a real User-Agent
with contact info, and cache results. All three are done here.
"""

import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from tnt.address import Address, canonical_street

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "tnt-lower-mainland/0.1 (portfolio project; github.com/cyncui/tnt-lower-mainland)"
CACHE = Path("data/geocode_cache.json")
FLAG_DISTANCE_M = 200


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def geocode_queries(addr: Address) -> list[str]:
    """Spellings to try, most specific first.

    Tested against Nominatim on the real T&T addresses: the canonical street
    ("2800 East 1st Avenue") matches where the raw one ("2800 E. First Ave")
    falls back to the wrong road, and Surrey's numbered streets only match
    without the ordinal ("15277 100 Avenue"). The unit and postal code are
    left out: Nominatim matches civic numbers, not mall units.
    """
    street = canonical_street(addr.street or "")
    tail = [p for p in [addr.city, addr.province, "Canada"] if p]
    first = ", ".join([street, *tail])
    no_ordinal = ", ".join([re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", r"\1", street), *tail])
    return [first] if no_ordinal == first else [first, no_ordinal]


@dataclass
class GeoResult:
    lat: float
    lng: float
    # place_rank 30 is a building or point of interest; 26-27 is a whole
    # street, which Nominatim returns when it can't find the house number.
    precise: bool
    matched: str = ""


class Geocoder:
    def __init__(self, cache_path: Path = CACHE, client: httpx.Client | None = None):
        self.cache_path = cache_path
        self.cache: dict[str, dict | None] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        self.client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20)
        self._last = 0.0

    def _lookup(self, query: str) -> dict | None:
        if query in self.cache:
            return self.cache[query]
        wait = 1.1 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = self.client.get(NOMINATIM, params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "ca"})
        r.raise_for_status()
        results = r.json()
        hit = None
        if results:
            top = results[0]
            hit = {"lat": float(top["lat"]), "lng": float(top["lon"]), "rank": top["place_rank"],
                   "name": top["display_name"]}
        self.cache[query] = hit
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=1, sort_keys=True, ensure_ascii=False))
        return hit

    def geocode(self, addr: Address) -> GeoResult | None:
        fallback = None
        for query in geocode_queries(addr):
            hit = self._lookup(query)
            if hit and hit["rank"] >= 30:
                return GeoResult(hit["lat"], hit["lng"], precise=True, matched=hit["name"])
            fallback = fallback or hit
        return GeoResult(fallback["lat"], fallback["lng"], False, fallback["name"]) if fallback else None


def validation_flags(addr: Address, site: tuple[float, float] | None, geocoded: GeoResult | None) -> list[str]:
    flags = []
    if not addr.postal_code:
        flags.append("missing_postal_code")
    if site is None:
        flags.append("missing_site_coordinates")
    if geocoded is None:
        flags.append("geocode_failed")
    elif not geocoded.precise:
        # A street-level match says nothing about where on the street the
        # store is, so comparing distances would only produce noise.
        flags.append("geocode_street_level")
    elif site:
        d = haversine_m(*site, geocoded.lat, geocoded.lng)
        if d > FLAG_DISTANCE_M:
            flags.append(f"geocode_mismatch_{round(d)}m")
    return flags
