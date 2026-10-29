"""Raw capture -> cleaned, ID'd, validated store records (regex cleaner)."""

from dataclasses import asdict, dataclass, field
from pathlib import Path

from tnt.address import Address, parse_address
from tnt.extract import RawStore, extract
from tnt.geocode import Geocoder, validation_flags
from tnt.hours import parse_hours
from tnt.ids import store_id

BRAND = "T&T Supermarket"

LOWER_MAINLAND = {
    "vancouver", "burnaby", "richmond", "surrey", "coquitlam", "port coquitlam", "port moody",
    "new westminster", "north vancouver", "west vancouver", "delta", "langley", "white rock",
    "maple ridge", "pitt meadows", "abbotsford",
}


@dataclass
class Store:
    store_id: str
    brand: str
    name: str | None
    source_id: str | None
    street: str | None
    unit: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    raw_address: str
    raw_hours: str
    hours: dict[str, list[str]]
    hours_notes: list[str]
    lat: float | None
    lng: float | None
    geocoded_lat: float | None = None
    geocoded_lng: float | None = None
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def clean(raw: RawStore) -> Store:
    addr = parse_address(raw.address)
    hours = parse_hours(raw.hours)
    return Store(
        store_id=store_id(BRAND, addr), brand=BRAND, name=raw.name, source_id=raw.source_id,
        **addr.as_dict(), raw_address=raw.address, raw_hours=raw.hours,
        hours=hours.hours, hours_notes=hours.notes, lat=raw.lat, lng=raw.lng,
    )


def in_lower_mainland(s: Store) -> bool:
    if s.city and s.city.lower() in LOWER_MAINLAND:
        return True
    # No city: fall back to the postal code. Every BC code starts with V, so
    # "V" alone would pull in Victoria and Kelowna; V3-V7 is the Lower Mainland
    # core. Callers flag these for review.
    return s.city is None and (s.postal_code or "")[:2] in {"V3", "V4", "V5", "V6", "V7"}


def run(raw_path: Path, geocoder: Geocoder | None = None) -> list[Store]:
    stores = [clean(r) for r in extract(raw_path)]
    stores = [s for s in stores if in_lower_mainland(s)]
    for s in stores:
        addr = Address(s.street, s.unit, s.city, s.province, s.postal_code)
        site = (s.lat, s.lng) if s.lat is not None and s.lng is not None else None
        geo = geocoder.geocode(addr) if geocoder else None
        if geo:
            s.geocoded_lat, s.geocoded_lng = geo
        s.flags = validation_flags(addr, site, geo) if geocoder else (
            [] if s.postal_code else ["missing_postal_code"]
        )
        if s.city is None:
            s.flags.append("lower_mainland_by_postal_code")
        if any(n.startswith("unparsed") for n in s.hours_notes):
            s.flags.append("hours_unparsed")
    return stores
