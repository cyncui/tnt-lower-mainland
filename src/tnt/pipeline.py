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

from tnt.address import POSTAL_RE, Address, canonical_city, canonical_street, parse_address
from tnt.extract import RawStore, extract
from tnt.geocode import FLAG_DISTANCE_M, GeoResult, Geocoder, haversine_m, validation_flags
from tnt.hours import parse_hours
from tnt.ids import first_store_id, location_id
from tnt.resolve import History, resolve_ids
from tnt.schema import DayHours, Excluded, Geocode, Inferred, Point, Run, Source, StoreRecord

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


def in_lower_mainland(r: StoreRecord) -> bool:
    city = r.address.city
    if city and canonical_city(city).lower() in LOWER_MAINLAND:
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
    if any(i.startswith("invalid postal code") for i in addr.issues):
        flags.append("postal_code_invalid")
    loc = location_id(BRAND, banner, addr)
    return StoreRecord(
        location_id=loc, store_id=first_store_id(loc), brand=BRAND, banner=banner, name=name, address=addr,
        phone=e164(raw.phone),
        location=Point(lat=raw.lat, lng=raw.lng) if raw.lat is not None and raw.lng is not None else None,
        geocode=None,
        hours={d: DayHours(open=o, close=c) for d, (o, c) in hours.hours.items()},
        hours_notes=hours.notes + ([f"special: {raw.special_hours}"] if raw.special_hours else []),
        flags=flags,
        source=Source(id=raw.source_id, name=raw.name, address=raw.address, phone=raw.phone,
                      hours=raw.hours, special_hours=raw.special_hours),
    )


def infer_postal_code(addr: Address, site: tuple[float, float] | None, buildings: list[GeoResult],
                      names: list[str]) -> Inferred | None:
    """Fill a missing postal code from OSM building matches at the same civic
    number, within FLAG_DISTANCE_M of the brand's pin.

    1. An OSM point named for the store itself wins. At 19705 Fraser Highway
       (Willowbrook mall) ten tenants carry three postal codes; a majority
       vote picks the mall's V3A 4C7, while OSM's T&T node has V3A 7E9.
    2. Otherwise fill only if every match agrees.
    3. Otherwise leave it empty and record the candidates for review.

    OSM postal codes can be wrong; Canada Post's AddressComplete is the
    authoritative source if this ever needs to be exact.
    """
    if addr.postal_code or not site or not addr.street:
        return None
    civic = addr.street.split(" ", 1)[0]
    matches = []  # (postal code, place name, metres from the brand's pin)
    for b in buildings:
        m = POSTAL_RE.fullmatch((b.postcode or "").strip())
        d = round(haversine_m(*site, b.lat, b.lng))
        if m and b.civic == civic and d <= FLAG_DISTANCE_M:
            matches.append((f"{m.group(1)} {m.group(2)}".upper(), b.matched.split(",")[0], d))
    if not matches:
        return None

    candidates = sorted({code for code, _, _ in matches})
    own = [(code, place, d) for code, place, d in matches if any(n.lower() in place.lower() for n in names)]
    if len({code for code, _, _ in own}) == 1:
        code, place, d = own[0]
        value, evidence = code, f"OSM point '{place}' at civic {civic}, {d} m from the brand's pin"
    elif len(candidates) == 1:
        value, evidence = candidates[0], f"all {len(matches)} OSM buildings at civic {civic} agree"
    else:
        value = None
        evidence = f"{len(matches)} OSM buildings at civic {civic} disagree: " + "; ".join(
            f"{place} {code}" for code, place, _ in matches)
    return Inferred(field="address.postal_code", value=value, candidates=candidates,
                    source="OpenStreetMap via Nominatim (ODbL)", evidence=evidence)


def validate(r: StoreRecord, geocoder: Geocoder | None) -> StoreRecord:
    site = (r.location.lat, r.location.lng) if r.location else None
    geo = geocoder.geocode(r.address) if geocoder else None
    geocode = None
    if geo:
        distance = round(haversine_m(*site, geo.lat, geo.lng)) if site and geo.precise else None
        geocode = Geocode(lat=geo.lat, lng=geo.lng, precision="building" if geo.precise else "street",
                          distance_m=distance, matched=geo.matched)
    addr, inferred = r.address, []
    if geocoder and not addr.postal_code:
        # OSM names the Langley store "大統華 T&T Supermarket", so match on "T&T", plus the banner (Osaka).
        names = sorted({"T&T", r.banner} - {BRAND})
        if found := infer_postal_code(addr, site, geocoder.buildings_at(addr), names):
            inferred = [found]
            if found.value:
                addr = replace(addr, postal_code=found.value)

    if geocoder:
        flags = validation_flags(addr, site, geo)
    else:
        flags = [] if addr.postal_code else ["missing_postal_code"]
    if inferred:
        # Inferred values still get a human glance; ambiguous ones need one.
        flags.append("postal_code_inferred" if inferred[0].value else "postal_code_ambiguous")
    return r.model_copy(update={"address": addr, "geocode": geocode, "flags": flags + r.flags,
                                "inferred": inferred})


def run(raw_path: Path, geocoder: Geocoder | None = None, history: History | None = None,
        decisions: dict[str, str] | None = None) -> Run:
    """history: earlier runs, so stores keep their IDs; decisions: relocations
    a person confirmed (resolve.py)."""
    raw = json.loads(raw_path.read_text())
    records = [clean(r) for r in extract(raw_path)]
    kept = [validate(r, geocoder) for r in records if in_lower_mainland(r)]
    excluded = [
        Excluded(source_id=r.source.id, name=r.name, city=r.address.city,
                 reason="outside the Lower Mainland" if r.address.city else "no city and no Lower Mainland postal code")
        for r in records if not in_lower_mainland(r)
    ]
    kept = resolve_ids(kept, history or History([], set()), decisions)
    kept.sort(key=lambda r: (r.address.city or "", r.name))
    return Run(run_date=date.fromisoformat(raw_path.stem), captured_from=raw["source"], stores=kept,
               excluded=excluded)
