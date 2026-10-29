"""Regex vs LLM cleaning on the same inputs."""

import json
from pathlib import Path

from tnt.address import parse_address
from tnt.hours import parse_hours

# Messy strings seen on tntsupermarket.com, kept so the comparison runs
# even before a full capture exists. The address/hours pairings are
# arbitrary; each string is real, the combinations are not.
KNOWN_MESSY = [
    ("#Y007 - 1 Promenade Circle Thornhill, ON. L4J 4P8", "Monday – Sunday 9:00 am - 10:00 pm"),
    ("26 Edward St, Toronto", "Grand Opening: Oct 8 9am / Store Hours: Mon - Sun, 8am-11pm"),
    ("Unit 1115, 1800 Sheppard Avenue East", "Monday – Sunday 9:00 am - 10:00 pm"),
]

FIELDS = ["street", "unit", "city", "province", "postal_code"]


def compare(clean_path: Path | None) -> None:
    from tnt.llm_clean import clean_with_llm, hours_dict

    pairs = list(KNOWN_MESSY)
    if clean_path:
        pairs += [(r["raw_address"], r["raw_hours"]) for r in json.loads(clean_path.read_text())]

    disagreements = 0
    for address, hours in pairs:
        rx_addr, rx_hours = parse_address(address).as_dict(), parse_hours(hours)
        llm = clean_with_llm(address, hours)
        llm_addr = {f: getattr(llm, f) for f in FIELDS}
        diffs = [f"{f}: regex={rx_addr[f]!r} llm={llm_addr[f]!r}" for f in FIELDS if rx_addr[f] != llm_addr[f]]
        if rx_hours.hours != hours_dict(llm):
            diffs.append(f"hours: regex={rx_hours.hours} llm={hours_dict(llm)}")
        if rx_hours.notes != llm.notes:
            diffs.append(f"notes: regex={rx_hours.notes} llm={llm.notes}")
        disagreements += bool(diffs)
        print(f"\n{address} | {hours}")
        print("  agree" if not diffs else "\n".join("  " + d for d in diffs))
    print(f"\n{disagreements}/{len(pairs)} inputs disagree")
