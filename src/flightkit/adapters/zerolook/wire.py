"""Zerolook request and response formats."""

from datetime import date
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, HttpUrl

from flightkit.models import AirlineCode, Cabin, CurrencyCode

# TODO: rename fields once Zerolook publishes their API docs.


class ZerolookSearchRequest(BaseModel):
    """A search request in the format the Zerolook API expects."""

    orig: str
    dest: str
    departDate: date
    returnDate: date | None = None
    pax: int
    cabin: Cabin


class ZerolookTrip(BaseModel):
    """A trip as returned by the Zerolook API."""

    model_config = ConfigDict(extra="ignore")

    fareAmt: Decimal
    cur: CurrencyCode
    airline: AirlineCode
    conf: float
    stops: int
    url: HttpUrl
    ts: AwareDatetime
