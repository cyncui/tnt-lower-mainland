"""Raw locator captures -> flat store records.

Confirmed against a browser capture (2026-10-29): the locator returns
{"code": 200, "data": [{id, name, address, lat, lng, store_hours,
special_store_hours, ...}]}. The address is one string, with no separate
city or postal fields. The walker still looks for any list of objects with
address-like and coordinate-like keys, so a schema change that only renames
or nests fields keeps working.
"""

import json
from dataclasses import dataclass
from pathlib import Path

NAME_KEYS = ["store_name", "name", "title", "store"]
ADDRESS_KEYS = ["address", "street", "address1", "street_address", "address_line_1"]
CITY_KEYS = ["city", "locality"]
PROVINCE_KEYS = ["province", "region", "region_code", "state"]
POSTAL_KEYS = ["postcode", "postal_code", "zip", "postal"]
LAT_KEYS = ["lat", "latitude"]
LNG_KEYS = ["lng", "lon", "long", "longitude"]
HOURS_KEYS = ["store_hours", "hours", "opening_hours", "business_hours", "schedule"]
SPECIAL_HOURS_KEYS = ["special_store_hours", "holiday_hours"]
SOURCE_ID_KEYS = ["id", "store_id", "store_code", "code", "identifier"]


@dataclass
class RawStore:
    source_id: str | None
    name: str | None
    address: str
    hours: str
    lat: float | None
    lng: float | None
    special_hours: str | None = None


def _first(d: dict, keys: list[str]):
    lowered = {k.lower(): v for k, v in d.items()}
    for k in keys:
        v = lowered.get(k)
        if v not in (None, "", []):
            return v
    return None


def _looks_like_store(d: dict) -> bool:
    return _first(d, ADDRESS_KEYS) is not None and (
        _first(d, LAT_KEYS) is not None or _first(d, CITY_KEYS) is not None
    )


def _walk(node):
    if isinstance(node, dict):
        if _looks_like_store(node):
            yield node
            return
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return " ".join(_text(x) for x in v)
    return json.dumps(v, ensure_ascii=False)


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def extract(raw_path: Path) -> list[RawStore]:
    data = json.loads(raw_path.read_text())
    stores: dict[str, RawStore] = {}
    for capture in data["captures"]:
        for d in _walk(capture["response"]):
            parts = [_text(_first(d, ADDRESS_KEYS)), _text(_first(d, CITY_KEYS)),
                     _text(_first(d, PROVINCE_KEYS)), _text(_first(d, POSTAL_KEYS))]
            address = ", ".join(p.strip() for p in parts if p.strip())
            store = RawStore(
                source_id=_text(_first(d, SOURCE_ID_KEYS)) or None,
                name=_text(_first(d, NAME_KEYS)).strip() or None,  # "Lougheed Store "
                address=address,
                hours=_text(_first(d, HOURS_KEYS)),
                lat=_float(_first(d, LAT_KEYS)),
                lng=_float(_first(d, LNG_KEYS)),
                special_hours=_text(_first(d, SPECIAL_HOURS_KEYS)).strip() or None,
            )
            # The same store can appear in several captures (page load + search).
            stores[store.source_id or address] = store
    return list(stores.values())
