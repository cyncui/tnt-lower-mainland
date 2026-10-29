"""Hash IDs for stores we have never seen before.

A new store's ID hashes brand, banner, street, unit, city, province and
the address note. Each part is normalized first so formatting doesn't
matter: "E. First Ave" = "East 1st Avenue", "100th" = "100", "0147" = "147",
"101-T" = "101T", "Township of Langley" = "Langley". The postal code is left
out, so filling one in or correcting a valid one doesn't change the ID.

The hash is only used to mint IDs. A store that was in an earlier run keeps
the ID it had, matched by the brand's own store number or by its map pin
(see resolve.py). So a changed address, a renamed street, or a change to this
normalization re-keys nothing that resolve.py can match.

What still gives a store a new ID: a change that resolve.py can't match,
i.e. a new brand store number AND a pin that moved more than 50 m (or two
earlier stores within 50 m, so the match is ambiguous).

Banner and note are in the hash so an Osaka and a T&T at one address, or
stores on different floors of one mall ("Upper Level" / "Lower Level"),
don't collide. Run rejects any duplicate ID that gets through anyway.
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


def store_id(brand: str, banner: str, addr: Address) -> str:
    key = "|".join([
        _norm(brand),
        _norm(banner),
        _street_key(addr.street),
        _unit_key(addr.unit),
        _norm(canonical_city(addr.city)) if addr.city else "",
        _norm(addr.province),
        _norm(addr.note),
    ])
    return hashlib.sha256(key.encode()).hexdigest()[:16]
