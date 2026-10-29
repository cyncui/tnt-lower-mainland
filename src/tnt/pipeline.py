"""Raw capture -> validated StoreRecords (regex cleaner).

clean() turns one raw store into a record; validate() geocodes it and sets
flags. The Lower Mainland filter runs between them so Nominatim is only
asked about stores we keep.
"""

import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

from tnt.address import canonical_street, parse_address
from tnt.extract import RawStore, extract
from tnt.geocode import Geocoder, haversine_m, validation_flags
from tnt.hours import parse_hours
from tnt.ids import store_id
from tnt.schema import DayHours, Geocode, Point, Run, Source, StoreRecord

BRAND = "T&T Supermarket"
BANNERS = ["Osaka"]  # T&T's Japanese-format stores, listed as "Osaka – <location> Store"

LOWER_MAINLAND = {
    "vancouver", "burnaby", "richmond", "surrey", "coquitlam", "port coquitlam", "port moody",
    "new westminster", "north vancouver", "west vancouver", "delta", "langley", "white rock",
    "maple ridge", "pitt meadows", "abbotsford",
}


def split_name(raw: str | None) -> tuple[str, str]:
    """'Osaka – Park Royal Store' -> ('Osaka', 'Park Royal'); 'Lougheed Store ' -> (BRAND, 'Lougheed')."""
    name = " ".join((raw or "").split())
    banner = BRAND
    for b in BANNERS:
        if m := re.match(rf"^{b}\s*[–—-]\s*", name):
            banner, name = b, name[m.end():]
    return banner, re.sub(r"\s+store$", "", name, flags=re.IGNORECASE)


def e164(phone: str | None) -> str | None:
    """'604.945.3818' and '604-519-8678' -> '+16049453818'."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    return f"+1{digits}" if len(digits) == 10 else None


def _municipality(city: str) -> str:
    # "Township of Langley" -> "langley"
    return re.sub(r"^(?:township|city|district|corporation) of ", "", city.lower())


def in_lower_mainland(r: StoreRecord) -> bool:
    city = r.address.city
    if city and _municipality(city) in LOWER_MAINLAND:
        return True
    # No city: fall back to the postal code. Every BC code starts with V, so
    # "V" alone would pull in Victoria and Kelowna; V3-V7 is the Lower Mainland
    # core. These get a flag for review.
    return city is None and (r.address.postal_code or "")[:2] in {"V3", "V4", "V5", "V6", "V7"}


def clean(raw: RawStore) -> StoreRecord:
    addr = parse_address(raw.address)
    if addr.street:
        addr = replace(addr, street=canonical_street(addr.street))
    hours = parse_hours(raw.hours)
    banner, name = split_name(raw.name)
    flags = []
    if addr.city is None:
        flags.append("lower_mainland_by_postal_code")
    if not hours.hours:
        flags.append("hours_unparsed")
    if raw.phone and not e164(raw.phone):
        flags.append("phone_unparsed")
    return StoreRecord(
        store_id=store_id(BRAND, addr), brand=BRAND, banner=banner, name=name, address=addr,
        phone=e164(raw.phone),
        location=Point(lat=raw.lat, lng=raw.lng) if raw.lat is not None and raw.lng is not None else None,
        geocode=None,
        hours={d: DayHours(open=o, close=c) for d, (o, c) in hours.hours.items()},
        hours_notes=hours.notes + ([f"special: {raw.special_hours}"] if raw.special_hours else []),
        flags=flags,
        source=Source(id=raw.source_id, name=raw.name, address=raw.address, phone=raw.phone,
                      hours=raw.hours, special_hours=raw.special_hours),
    )


def validate(r: StoreRecord, geocoder: Geocoder | None) -> StoreRecord:
    site = (r.location.lat, r.location.lng) if r.location else None
    geo = geocoder.geocode(r.address) if geocoder else None
    geocode = None
    if geo:
        distance = round(haversine_m(*site, geo.lat, geo.lng)) if site and geo.precise else None
        geocode = Geocode(lat=geo.lat, lng=geo.lng, precision="building" if geo.precise else "street",
                          distance_m=distance, matched=geo.matched)
    if geocoder:
        flags = validation_flags(r.address, site, geo)
    else:
        flags = [] if r.address.postal_code else ["missing_postal_code"]
    return r.model_copy(update={"geocode": geocode, "flags": flags + r.flags})


def run(raw_path: Path, geocoder: Geocoder | None = None) -> Run:
    raw = json.loads(raw_path.read_text())
    records = [clean(r) for r in extract(raw_path)]
    kept = [validate(r, geocoder) for r in records if in_lower_mainland(r)]
    kept.sort(key=lambda r: (r.address.city or "", r.name))
    return Run(run_date=date.fromisoformat(raw_path.stem), captured_from=raw["source"], stores=kept)
