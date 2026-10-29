"""Stable store IDs.

The ID is a hash of brand + normalized street + unit + city + province.
Postal code is left out on purpose: it is the field most often missing or
corrected later, and a fix to it should not mint a new store.

What breaks it (a new ID for the same physical store):
- the brand renames its stores or the address string changes in a way
  normalize_street doesn't fold (e.g. "No. 3 Rd" vs "Number 3 Road");
- a unit number is added, removed or corrected;
- the city changes ("Vancouver" -> "Burnaby" for a border store, or a mall
  listed under its municipality one week and its neighbourhood the next);
- a store relocates within the same mall (new unit) - arguably a new store.

What it gets wrong the other way (two stores, one ID): two brand locations
at the same address with no unit, e.g. a supermarket and an express kiosk.
"""

import hashlib

from tnt.address import Address, normalize_street


def _norm(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def store_id(brand: str, addr: Address) -> str:
    key = "|".join([
        _norm(brand),
        normalize_street(addr.street or ""),
        _norm(addr.unit),
        _norm(addr.city),
        _norm(addr.province),
    ])
    return hashlib.sha256(key.encode()).hexdigest()[:16]
