"""Regex address normalizer for Canadian store addresses."""

import re
from dataclasses import asdict, dataclass, field

# Canada Post never uses D, F, I, O, Q or U, and W/Z never start a code.
POSTAL_RE = re.compile(
    r"\b([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z])[\s-]?(\d[ABCEGHJ-NPRSTV-Z]\d)\b", re.IGNORECASE
)
# Shaped like a postal code at the end of the address but not valid: "V5N 2TO"
# (letter O), "V5N2T". Left in place it parses as the city and drops the store.
_POSTAL_LIKE_RE = re.compile(r"[,.\s]+([A-Z]\d[A-Z][\s-]?[0-9A-Z]{1,3})\.?\s*$", re.IGNORECASE)

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
    r"^\s*(?:#\s*|unit\s*#?\s*|suite\s+|ste\.?\s+)(\w+)(?:\s*[-–—,]\s*|\s+)(?=\d)", re.IGNORECASE
)
# "1000-3700 No. 3 Rd": unit-civic, Canada Post's usual form.
_UNIT_CIVIC_RE = re.compile(r"^\s*(\w+)[-–—](\d+\w?)\s+")
_UNIT_SUFFIX_RE = re.compile(r",?\s*(?:#|unit\s+|suite\s+)([\w-]+)\s*(?=,|$)", re.IGNORECASE)

SUFFIXES = {
    "st": "street", "street": "street", "ave": "avenue", "av": "avenue", "avenue": "avenue",
    "rd": "road", "road": "road", "blvd": "boulevard", "boulevard": "boulevard",
    "dr": "drive", "drive": "drive", "way": "way", "hwy": "highway", "highway": "highway",
    "cir": "circle", "circle": "circle", "cres": "crescent", "crescent": "crescent",
    "pl": "place", "place": "place", "ct": "court", "court": "court",
    "pkwy": "parkway", "parkway": "parkway", "lane": "lane", "ln": "lane",
    "ter": "terrace", "terrace": "terrace", "sq": "square", "square": "square",
    "trl": "trail", "trail": "trail",
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
    # Things the parser removed because they were malformed, e.g. an invalid postal code.
    issues: list[str] = field(default_factory=list, compare=False)

    def as_dict(self) -> dict:
        return asdict(self)


def parse_address(raw: str) -> Address:
    addr = Address()
    notes = []
    # T&T separates street and city with two spaces ("147-4800 Kingsway  Burnaby").
    # Turn that into a comma before collapsing whitespace, or the signal is lost.
    s = re.sub(r"\s{2,}", ", ", raw.strip())
    s = " ".join(s.split())
    s = re.sub(r"[,\s]+canada\.?$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\bB\.\s?C\b\.?", "BC", s)

    # Leading cross-street hint: "(100 Ave. & 152 St.)".
    if m := re.match(r"^\(([^)]*)\)[\s,]*", s):
        notes.append(m.group(1))
        s = s[m.end():]

    if m := POSTAL_RE.search(s):
        addr.postal_code = f"{m.group(1)} {m.group(2)}".upper()
        s = (s[: m.start()] + s[m.end():]).strip(" ,.")
    elif m := _POSTAL_LIKE_RE.search(s):
        addr.issues.append(f"invalid postal code {m.group(1)!r}")
        s = s[: m.start()].strip(" ,.")

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


COMPOUND_DIRECTIONS = {"ne": "NE", "nw": "NW", "se": "SE", "sw": "SW", "northeast": "NE",
                       "northwest": "NW", "southeast": "SE", "southwest": "SW"}
ORDINAL_WORDS = {"first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th",
                 "sixth": "6th", "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th"}


def canonical_street(street: str) -> str:
    """One spelling per street, used for display, IDs and geocoding.

    Full words in title case: '2800 E. First Ave' -> '2800 East 1st Avenue',
    '458 S.W. Marine Drive' -> '458 SW Marine Drive', '3700 No. 3 Rd' ->
    '3700 No. 3 Road'. Nominatim matched every T&T address in this form.
    """
    s = re.sub(r"\b([NS])\.\s?([EW])\.", r"\1\2", street, flags=re.IGNORECASE)  # S.W. -> SW
    s = re.sub(r"\b(?:no\.?|number)\s*(?=\d)", "No. ", s, flags=re.IGNORECASE)  # No 3 / Number 3 -> No. 3
    words = s.replace(",", " ").split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower().rstrip(".")
        if i == 0:
            out.append(w.upper())  # civic number, e.g. "15277"
        elif lw in COMPOUND_DIRECTIONS:
            out.append(COMPOUND_DIRECTIONS[lw])
        elif lw in DIRECTIONS and (i == 1 or i == len(words) - 1):
            out.append(DIRECTIONS[lw].title())
        elif lw == "st" and not all(_is_direction_word(r) for r in words[i + 1:]):
            out.append("Saint")  # "St Johns St": a name follows, so not the street type
        elif lw in ORDINAL_WORDS:
            out.append(ORDINAL_WORDS[lw])
        elif lw in SUFFIXES:
            out.append(SUFFIXES[lw].title())
        elif w == "No.":
            out.append(w)
        elif re.fullmatch(r"\d+(st|nd|rd|th)", lw):
            out.append(lw)  # "100th", not "100Th"
        else:
            out.append(w[0].upper() + w[1:].lower() if w.isupper() and len(w) > 1 else w[0].upper() + w[1:])
    # Again at the end: "No First" only becomes "No 1st" in the loop above.
    return re.sub(r"\bNo\.?\s*(?=\d)", "No. ", " ".join(out))


def _is_direction_word(word: str) -> bool:
    w = word.lower().rstrip(".")
    return w in DIRECTIONS or w in COMPOUND_DIRECTIONS


_CITY_PREFIX_RE = re.compile(r"^(?:township|city|district|corporation|town|village) of\s+", re.IGNORECASE)
_CITY_DIRECTIONS = {"n": "North", "s": "South", "e": "East", "w": "West"}


def canonical_city(city: str) -> str:
    """'Township of Langley' -> 'Langley', 'N. Vancouver' -> 'North Vancouver'."""
    words = _CITY_PREFIX_RE.sub("", " ".join(city.split())).split()
    if words and words[0].lower().rstrip(".") in _CITY_DIRECTIONS and len(words) > 1:
        words[0] = _CITY_DIRECTIONS[words[0].lower().rstrip(".")]
    return " ".join(w[0].upper() + w[1:] for w in words)
