"""Regex address normalizer for Canadian store addresses."""

import re
from dataclasses import asdict, dataclass

# Canada Post never uses D, F, I, O, Q or U, and W/Z never start a code.
POSTAL_RE = re.compile(
    r"\b([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z])\s?(\d[ABCEGHJ-NPRSTV-Z]\d)\b", re.IGNORECASE
)

PROVINCES = {
    "BC": "BC", "BRITISH COLUMBIA": "BC", "AB": "AB", "ALBERTA": "AB",
    "SK": "SK", "SASKATCHEWAN": "SK", "MB": "MB", "MANITOBA": "MB",
    "ON": "ON", "ONTARIO": "ON", "QC": "QC", "QUEBEC": "QC",
    "NB": "NB", "NS": "NS", "PE": "PE", "NL": "NL",
}
_PROVINCE_RE = re.compile(
    r"(?:,|\s)\s*(" + "|".join(sorted(PROVINCES, key=len, reverse=True)) + r")\.?\s*$", re.IGNORECASE
)

# Leading "#Y007 -", "#3000-", "Unit 1115,", "Unit #MAJ1," or "Suite 200".
# The unit is greedy and needs a separator after it: a lazy match plus a
# digit lookahead would split "#3000-10153" into unit "3".
_UNIT_PREFIX_RE = re.compile(
    r"^\s*(?:#\s*|unit\s*#?\s*|suite\s+|ste\.?\s+)(\w+)(?:\s*[-,]\s*|\s+)(?=\d)", re.IGNORECASE
)
# "1000-3700 No. 3 Rd": unit-civic, Canada Post's usual form.
_UNIT_CIVIC_RE = re.compile(r"^\s*(\w+)-(\d+\w?)\s+")
_UNIT_SUFFIX_RE = re.compile(r",?\s*(?:#|unit\s+|suite\s+)([\w-]+)\s*(?=,|$)", re.IGNORECASE)

SUFFIXES = {
    "st": "street", "street": "street", "ave": "avenue", "av": "avenue", "avenue": "avenue",
    "rd": "road", "road": "road", "blvd": "boulevard", "boulevard": "boulevard",
    "dr": "drive", "drive": "drive", "way": "way", "hwy": "highway", "highway": "highway",
    "cir": "circle", "circle": "circle", "cres": "crescent", "crescent": "crescent",
    "pl": "place", "place": "place", "ct": "court", "court": "court",
    "pkwy": "parkway", "parkway": "parkway", "lane": "lane", "ln": "lane",
}
DIRECTIONS = {"e": "east", "east": "east", "w": "west", "west": "west",
              "n": "north", "north": "north", "s": "south", "south": "south"}

_STREET_END_RE = re.compile(
    r"^(.*\b(?:" + "|".join(SUFFIXES) + r")\.?(?:\s+(?:" + "|".join(DIRECTIONS) + r")\.?)?)\s+(.+)$",
    re.IGNORECASE,
)


@dataclass
class Address:
    street: str | None = None
    unit: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    # Text that isn't part of the address proper: "(Keefer & Abbott)", "Upper Level".
    note: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def parse_address(raw: str) -> Address:
    addr = Address()
    notes = []
    # T&T separates street and city with two spaces ("147-4800 Kingsway  Burnaby").
    # Turn that into a comma before collapsing whitespace, or the signal is lost.
    s = re.sub(r"\s{2,}", ", ", raw.strip())
    s = " ".join(s.split())

    # Leading cross-street hint: "(100 Ave. & 152 St.)".
    if m := re.match(r"^\(([^)]*)\)[\s,]*", s):
        notes.append(m.group(1))
        s = s[m.end():]

    if m := POSTAL_RE.search(s):
        addr.postal_code = f"{m.group(1)} {m.group(2)}".upper()
        s = (s[: m.start()] + s[m.end():]).strip(" ,.")

    if m := _PROVINCE_RE.search(s):
        addr.province = PROVINCES[m.group(1).upper()]
        s = s[: m.start()].strip(" ,.")

    if m := _UNIT_PREFIX_RE.match(s):
        addr.unit = m.group(1).upper()
        s = s[m.end():]
    elif m := _UNIT_CIVIC_RE.match(s):
        addr.unit, s = m.group(1).upper(), m.group(2) + " " + s[m.end():]
    elif m := _UNIT_SUFFIX_RE.search(s):
        addr.unit = m.group(1).upper()
        s = (s[: m.start()] + s[m.end():]).strip(" ,")

    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) >= 2:
        addr.street, addr.city = parts[0], parts[-1]
        notes += parts[1:-1]  # "Upper Level" between street and city
    elif parts:
        # No comma between street and city: split after the street type.
        m = _STREET_END_RE.match(parts[0])
        if m and not _is_direction_only(m.group(2)):
            addr.street, addr.city = m.group(1), m.group(2)
        else:
            addr.street = parts[0]
    addr.note = "; ".join(notes) or None
    return addr


def _is_direction_only(text: str) -> bool:
    return text.lower().strip(".") in DIRECTIONS


def normalize_street(street: str) -> str:
    """Canonical form for comparison and hashing: '1800 Sheppard Ave. E' -> '1800 sheppard avenue east'."""
    words = re.sub(r"[.,#]", " ", street.lower()).split()
    out = []
    for i, w in enumerate(words):
        if w in SUFFIXES and i > 0:
            out.append(SUFFIXES[w])
        elif w in DIRECTIONS and i > 0 and (i == len(words) - 1 or i == 1):
            out.append(DIRECTIONS[w])
        else:
            out.append(w)
    return " ".join(out)
