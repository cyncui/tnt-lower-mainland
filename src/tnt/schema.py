"""The one store record shape used by cleaned files, the database and the API.

Cleaned fields sit at the top level; the strings exactly as T&T published
them sit under `source`, so a parser fix can always be re-run from them.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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


class StoreRecord(BaseModel):
    store_id: str
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
    source: Source

    @field_validator("hours")
    @classmethod
    def week_order(cls, v: dict) -> dict:
        return {d: v[d] for d in DAYS if d in v}


class Run(BaseModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    run_date: date
    captured_from: str
    stores: list[StoreRecord]
