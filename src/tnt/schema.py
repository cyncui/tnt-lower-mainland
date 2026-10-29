"""The one store record shape used by cleaned files, the database and the API.

Cleaned fields sit at the top level; the strings exactly as T&T published
them sit under `source`, so a parser fix can always be re-run from them.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from tnt.address import Address
from tnt.hours import DAYS

# v2: store_id split into location_id (a place) and store_id (a brand store).
SCHEMA_VERSION = 2
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
    location_id: str = Field(pattern=r"^loc_[0-9a-f]{16}$")  # one place; never moves
    store_id: str = Field(pattern=r"^sto_[0-9a-f]{16}$")  # one brand store; follows relocations
    # How the IDs were decided (resolve.py): carried over by the brand's store
    # number, by map pin, by a person's review decision, or newly minted.
    matched_by: Literal["store_number", "pin", "review", "new"] = "new"
    # Set in the run where a store moved: the location it moved from.
    relocated_from: str | None = None
    # A new location that may be a store that just disappeared nearby. Not
    # linked until a person confirms it (review/relocations.json).
    relocation_candidate: str | None = None
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


class Event(BaseModel):
    run_date: date
    type: Literal["opened", "closed", "relocated", "reopened"]
    store_id: str
    location_id: str  # for "relocated", the new location
    from_location_id: str | None = None  # for "relocated"


class Run(BaseModel):
    schema_version: Literal[2] = SCHEMA_VERSION
    run_date: date
    captured_from: str
    stores: list[StoreRecord]
    excluded: list[Excluded] = []

    @model_validator(mode="before")
    @classmethod
    def migrate_v1(cls, data):
        # v1 had one store_id per place. It becomes the location_id, and the
        # store_id is named after it, the same rule a new store gets now. Old
        # files keep their history connected without being rewritten.
        if isinstance(data, dict) and data.get("schema_version") == 1:
            data = {**data, "schema_version": 2, "stores": [
                {**s, "location_id": "loc_" + s["store_id"], "store_id": "sto_" + s["store_id"]}
                for s in data["stores"]
            ]}
        return data

    @model_validator(mode="after")
    def unique_ids(self) -> "Run":
        # Two records with one location_id would silently overwrite each other
        # in the database and the diff, and one brand store can't be in two
        # places in the same run. Refuse the run instead.
        for field in ("location_id", "store_id"):
            seen: dict[str, str] = {}
            dupes = []
            for s in self.stores:
                key = getattr(s, field)
                if key in seen:
                    dupes.append(f"{key} ({seen[key]} / {s.name})")
                seen[key] = s.name
            if dupes:
                raise ValueError(f"duplicate {field}s: {', '.join(dupes)}")
        return self
