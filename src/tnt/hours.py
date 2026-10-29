"""Regex hours parser.

Turns free-text store hours into {"mon": ["09:00", "22:00"], ...}.
A close time earlier than the open time means the store closes after
midnight, so it is written past 24:00 ("01:00" next day -> "25:00").
That keeps "open past 10 pm" a plain string/int comparison.
"""

import re
from dataclasses import dataclass, field

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_DAY_NAMES = {
    "mon": "mon", "monday": "mon",
    "tue": "tue", "tues": "tue", "tuesday": "tue",
    "wed": "wed", "wednesday": "wed",
    "thu": "thu", "thur": "thu", "thurs": "thu", "thursday": "thu",
    "fri": "fri", "friday": "fri",
    "sat": "sat", "saturday": "sat",
    "sun": "sun", "sunday": "sun",
}

# Sites mix hyphens, en dashes, em dashes and the word "to".
_DASH = r"\s*(?:-|–|—|to)\s*"
_DAY = r"\b(" + "|".join(sorted(_DAY_NAMES, key=len, reverse=True)) + r")\b\.?"
_TIME = r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?"

_RANGE_RE = re.compile(
    _DAY + r"(?:" + _DASH + _DAY + r")?" + r"\s*[,:]?\s*" + _TIME + _DASH + _TIME,
    re.IGNORECASE,
)
_GRAND_OPENING_RE = re.compile(r"grand opening[^/]*", re.IGNORECASE)
_DAILY_RE = re.compile(r"(?:daily|everyday|every day|7 days)\s*[,:]?\s*" + _TIME + _DASH + _TIME, re.IGNORECASE)


@dataclass
class ParsedHours:
    hours: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _to_24h(hour: str, minute: str | None, meridiem: str) -> int:
    h = int(hour) % 12
    if meridiem.lower() == "p":
        h += 12
    return h * 60 + int(minute or 0)


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _span(open_min: int, close_min: int) -> list[str]:
    if close_min <= open_min:
        close_min += 24 * 60
    return [_fmt(open_min), _fmt(close_min)]


def _day_range(start: str, end: str | None) -> list[str]:
    i = DAYS.index(_DAY_NAMES[start.lower()])
    if end is None:
        return [DAYS[i]]
    j = DAYS.index(_DAY_NAMES[end.lower()])
    # Wraps the week, e.g. "Sat - Mon".
    return [DAYS[(i + k) % 7] for k in range((j - i) % 7 + 1)]


def parse_hours(text: str) -> ParsedHours:
    result = ParsedHours()
    if not text:
        return result

    # T&T uses both "\r\n" and "<br />" between the day range and the times.
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # A grand-opening line carries a one-off time ("Oct 8 9am") that is not
    # the weekly schedule. Pull it out first so the range regex can't pair
    # "9am" with the regular hours.
    for m in _GRAND_OPENING_RE.finditer(text):
        result.notes.append(m.group(0).strip(" /"))
    body = _GRAND_OPENING_RE.sub(" ", text)

    for m in _RANGE_RE.finditer(body):
        d1, d2, h1, m1, ap1, h2, m2, ap2 = m.groups()
        span = _span(_to_24h(h1, m1, ap1), _to_24h(h2, m2, ap2))
        for day in _day_range(d1, d2):
            result.hours[day] = span

    if not result.hours:
        m = _DAILY_RE.search(body)
        if m:
            h1, m1, ap1, h2, m2, ap2 = m.groups()
            span = _span(_to_24h(h1, m1, ap1), _to_24h(h2, m2, ap2))
            result.hours = {day: span for day in DAYS}

    if not result.hours:
        result.notes.append(f"unparsed: {' '.join(text.split())}")
    return result
