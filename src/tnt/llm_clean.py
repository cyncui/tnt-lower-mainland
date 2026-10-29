"""LLM version of the cleaner, for comparison with the regex one.

Uses structured outputs so the response is validated against a schema
instead of parsed out of free text. Needs ANTHROPIC_API_KEY (or an
`ant auth login` profile); without credentials the comparison is skipped.
"""

import os

import anthropic
from pydantic import BaseModel

MODEL = os.environ.get("TNT_LLM_MODEL", "claude-opus-5-5")

PROMPT = """Extract the store address and weekly opening hours from this listing.

Rules:
- Use only what is written. If a field is absent, return null. Do not infer a
  postal code or province from the city.
- hours: one entry per day the store is open, 24-hour HH:MM. A close time after
  midnight is written past 24:00 (1 am -> "25:00").
- A one-off event time (e.g. a grand opening) is not part of the weekly hours;
  put it in notes.

Address: {address}
Hours: {hours}"""


class DayHours(BaseModel):
    day: str  # mon..sun
    open: str
    close: str


class LLMStore(BaseModel):
    street: str | None
    unit: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    hours: list[DayHours]
    notes: list[str]


def clean_with_llm(address: str, hours: str, client: anthropic.Anthropic | None = None) -> LLMStore:
    client = client or anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=2000,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": PROMPT.format(address=address, hours=hours)}],
        output_format=LLMStore,
    )
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise RuntimeError(f"LLM extraction stopped with {response.stop_reason}")
    return response.parsed_output


def hours_dict(store: LLMStore) -> dict[str, list[str]]:
    return {h.day: [h.open, h.close] for h in store.hours}
