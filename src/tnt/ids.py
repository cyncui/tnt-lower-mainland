"""IDs for places and for brand stores.

location_id ("loc_..."): one physical place. It never moves. When the
brand leaves a site, that location ends, whether the store closed or
relocated. This is the ID to join map or foot-traffic data on.

store_id ("sto_..."): one brand store. It follows the store through
relocations and only ends when the store really closes. A new store's
store_id is named after the first place it was seen (same hex as that
location_id), which is a label, not a link: after a move the two differ.

Both are only minted here for stores never seen before. A store that was in
an earlier run keeps its IDs through resolve.py.

The location hash covers brand, banner, street, unit, city, province and
the address note, each normalized first so formatting doesn't matter:
"E. First Ave" = "East 1st Avenue", "100th" = "100", "0147" = "147",
"101-T" = "101T", "Township of Langley" = "Langley". The postal code isn't
hashed. Banner and note are, so an Osaka and a T&T at one address, or
stores on different floors of one mall, don't collide. Run rejects any
duplicate that gets through anyway.
"""

import hashlib
import re

from tnt.address import Address, canonical_city, canonical_street


def _norm(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def _street_key(street: str | None) -> str:
    # Ordinals off: OSM and T&T disagree on "100th Avenue" vs "100 Avenue".
    return re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", r"\1", canonical_street(street).lower()) if street else ""


def _unit_key(unit: str | None) -> str:
    return re.sub(r"[-\s]", "", unit or "").lstrip("0").lower()


def address_key(addr: Address) -> str:
    """The normalized address, used for hashing and to tell a relocation
    (address changed) from a corrected pin (same address)."""
    return "|".join([
        _street_key(addr.street),
        _unit_key(addr.unit),
        _norm(canonical_city(addr.city)) if addr.city else "",
        _norm(addr.province),
        _norm(addr.note),
    ])


def location_id(brand: str, banner: str, addr: Address) -> str:
    key = "|".join([_norm(brand), _norm(banner), address_key(addr)])
    return "loc_" + hashlib.sha256(key.encode()).hexdigest()[:16]


def first_store_id(location_id: str) -> str:
    """A brand-new store is named after the place it was first seen."""
    return "sto_" + location_id.removeprefix("loc_")
