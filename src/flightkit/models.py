"""Domain models: what callers send, and what flightkit returns."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)
from typing_extensions import Self

IataCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$", to_upper=True)]
Cabin = Literal["economy", "premium_economy", "business", "first"]
Source = Literal["prediction", "live"]
CurrencyCode = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{3}$", to_upper=True)
]
AirlineCode = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9]{2}$", to_upper=True)
]
MAX_DATE_RANGE_DAYS = 60


class FlightkitModel(BaseModel):
    """Base for flightkit models: immutable, strict about unknown fields, trims strings."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class Search(FlightkitModel):
    """One concrete search: a route, a departure day and an optional return day."""

    origin: IataCode
    destination: IataCode
    depart_date: date
    return_date: date | None = None
    passengers: int = Field(default=1, ge=1, le=9)
    cabin: Cabin = "economy"

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        if self.return_date and self.return_date < self.depart_date:
            raise ValueError("return_date must be on or after depart_date")
        return self


class TripQuery(FlightkitModel):
    """A flexible trip search that expands into many concrete searches."""

    origin: IataCode = Field(description="Departure airport as an IATA code, e.g. ZRH.")
    destinations: tuple[IataCode, ...] = Field(
        min_length=1,
        max_length=20,
        description="Candidate destination airports as IATA codes, e.g. ATH, HER.",
    )
    depart_from: date = Field(description="Earliest departure date.")
    depart_to: date = Field(description="Latest departure date, inclusive")
    min_nights: int | None = Field(
        default=None,
        ge=1,
        le=30,
        description="Shortest stay in nights. Leave both night fields empty for one-way",
    )
    max_nights: int | None = Field(
        default=None,
        ge=1,
        le=30,
        description="Longest stay in nights. Leave both night fields empty for one-way",
    )
    passengers: int = Field(default=1, ge=1, le=9, description="Number of travellers.")
    cabin: Cabin = Field(default="economy", description="Cabin class.")

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.depart_to < self.depart_from:
            raise ValueError("depart_to must be on or after depart_from")
        if (self.depart_to - self.depart_from).days + 1 > MAX_DATE_RANGE_DAYS:
            raise ValueError(f"date range must be at most {MAX_DATE_RANGE_DAYS} days")
        if self.origin in self.destinations:
            raise ValueError("origin must not be one of the destinations")
        if len(set(self.destinations)) != len(self.destinations):
            raise ValueError("destinations must not contain duplicates")
        if (self.min_nights is None) != (self.max_nights is None):
            raise ValueError("set both min_nights and max_nights, or neither")
        if self.min_nights and self.max_nights and self.min_nights > self.max_nights:
            raise ValueError("min_nights must not be greater than max_nights")
        return self


class Price(FlightkitModel):
    """An exact amount in one currency."""

    amount: Decimal = Field(ge=0)
    currency: CurrencyCode


class PricedTrip(FlightkitModel):
    """A bookable trip with its price, as returned by a fare source."""

    price: Price
    confidence: float | None = Field(default=None, ge=0, le=1)
    carrier: AirlineCode
    stops: int = Field(ge=0)
    deeplink: HttpUrl
    fetched_at: AwareDatetime
    source: Source
    search: Search

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.source == "prediction" and self.confidence is None:
            raise ValueError("confidence is required when source is 'prediction'")
        return self


class SearchFailure(FlightkitModel):
    """A search that could not be completed."""

    search: Search
    error: str
    retryable: bool = Field(
        default=False, description="Whether trying the same search again later may succeed."
    )


class SearchStats(FlightkitModel):
    """How a batch of searches was served."""

    searches: int = Field(default=0, description="Concrete searches requested.")
    cache_hits: int = Field(default=0, description="Searches answered from the cache.")
    coalesced: int = Field(default=0, description="Searches that shared an in-flight call.")
    calls: int = Field(default=0, description="Searches sent to the fare source.")
    failures: int = Field(default=0, description="Searches that failed.")


class SearchResult(FlightkitModel):
    """Trips found across many searches, plus any searches that failed."""

    trips: tuple[PricedTrip, ...] = ()
    failures: tuple[SearchFailure, ...] = ()
    stats: SearchStats = SearchStats()


class CurrencyResult(FlightkitModel):
    """Ranked trips that share one currency."""

    trips: tuple[PricedTrip, ...] = Field(description="All trips, cheapest first.")
    cheapest_by_destination: dict[str, PricedTrip] = Field(
        description="Cheapest trip per destination airport, cheapest first."
    )
    calendar: dict[date, PricedTrip] = Field(
        description="Cheapest trip per departure date, in date order."
    )


class TripResult(FlightkitModel):
    """The answer to a TripQuery: ranked trips per currency, failures, and stats."""

    currencies: dict[str, CurrencyResult] = Field(
        description="Results grouped by currency code. Prices are only compared within a currency."
    )
    failures: tuple[SearchFailure, ...] = ()
    stats: SearchStats = SearchStats()
