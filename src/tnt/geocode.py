"""Nominatim geocoding and distance checks.

Nominatim's usage policy: at most 1 request per second, a real User-Agent
with contact info, and cache results. All three are done here.
"""

import json
import math
import time
from pathlib import Path

import httpx

from tnt.address import Address

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


class Geocoder:
    def __init__(self, cache_path: Path = CACHE, client: httpx.Client | None = None):
        self.cache_path = cache_path
        self.cache: dict[str, list[float] | None] = (
            json.loads(cache_path.read_text()) if cache_path.exists() else {}
        )
        self.client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20)
        self._last = 0.0

    def geocode(self, addr: Address) -> tuple[float, float] | None:
        # Units confuse Nominatim, and it matches civic addresses, not mall units.
        query = ", ".join(p for p in [addr.street, addr.city, addr.province, addr.postal_code, "Canada"] if p)
        if query in self.cache:
            hit = self.cache[query]
            return tuple(hit) if hit else None

        wait = 1.1 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = self.client.get(NOMINATIM, params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "ca"})
        r.raise_for_status()
        results = r.json()
        hit = [float(results[0]["lat"]), float(results[0]["lon"])] if results else None
        self.cache[query] = hit
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=1, sort_keys=True))
        return tuple(hit) if hit else None


def validation_flags(addr: Address, site: tuple[float, float] | None, geocoded: tuple[float, float] | None) -> list[str]:
    flags = []
    if not addr.postal_code:
        flags.append("missing_postal_code")
    if site is None:
        flags.append("missing_site_coordinates")
    if geocoded is None:
        flags.append("geocode_failed")
    if site and geocoded:
        d = haversine_m(*site, *geocoded)
        if d > FLAG_DISTANCE_M:
            flags.append(f"geocode_mismatch_{round(d)}m")
    return flags
