"""The one store record shape used by cleaned files, the database and the API.

Cleaned fields sit at the top level; the strings exactly as T&T published
them sit under `source`, so a parser fix can always be re-run from them.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from tnt.address import Address
from tnt.hours import DAYS

SCHEMA_VERSION = 1
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HHMM = Field(pattern=r"^\d{2}:\d{2}$")


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Geocode(Point):
    # "building" is a house-number or point-of-interest match; "street" means
    # Nominatim only found the road, so the point says nothing about the store.
    precision: Literal["building", "street"]
    distance_m: int | None = None  # from the brand's pin, building matches only
    matched: str


class DayHours(BaseModel):
    open: str = HHMM
    close: str = HHMM  # past 24:00 when the store closes after midnight


class Source(BaseModel):
    id: str | None
    name: str | None
    address: str
    phone: str | None
    hours: str
    special_hours: str | None


class Inferred(BaseModel):
    """A value the brand didn't publish that we tried to fill in.

    value is None when the sources disagreed; candidates lists what they said.
    """

    field: str  # dotted path, e.g. "address.postal_code"
    value: str | None
    candidates: list[str]
    source: str
    evidence: str


class StoreRecord(BaseModel):
    store_id: str
    # How this ID was decided: carried over from an earlier run by the brand's
    # store number or its map pin, or minted from the address hash (resolve.py).
    matched_by: Literal["store_number", "pin", "new"] = "new"
    brand: str
    banner: str  # "T&T Supermarket" or "Osaka"
    name: str  # location only: "Park Royal", not "Osaka – Park Royal Store"
    address: Address
    phone: str | None = Field(None, pattern=r"^\+1\d{10}$")  # E.164
    location: Point | None  # the brand's own pin
    geocode: Geocode | None
    hours: dict[Day, DayHours]
    hours_notes: list[str]
    flags: list[str]
    inferred: list[Inferred] = []
    source: Source

    @field_validator("hours")
    @classmethod
    def week_order(cls, v: dict) -> dict:
        return {d: v[d] for d in DAYS if d in v}


class Excluded(BaseModel):
    """A store in the capture that didn't make the run. Listed so a parse
    failure can't look like a closure."""

    source_id: str | None
    name: str | None
    city: str | None
    reason: str


class Run(BaseModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    run_date: date
    captured_from: str
    stores: list[StoreRecord]
    excluded: list[Excluded] = []

    @model_validator(mode="after")
    def unique_ids(self) -> "Run":
        # Two stores with one ID would silently overwrite each other in the
        # database and the diff, so refuse the run instead.
        seen: dict[str, str] = {}
        dupes = []
        for s in self.stores:
            if s.store_id in seen:
                dupes.append(f"{s.store_id} ({seen[s.store_id]} / {s.name})")
            seen[s.store_id] = s.name
        if dupes:
            raise ValueError(f"duplicate store IDs: {', '.join(dupes)}")
        return self
