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


class FlightkitModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class Search(FlightkitModel):
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


class Price(FlightkitModel):
    amount: Decimal = Field(ge=0)
    currency: CurrencyCode


class PricedTrip(FlightkitModel):
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


class SearchResult(FlightkitModel):
    """Trips found across many searches, plus any searches that failed."""

    trips: tuple[PricedTrip, ...] = ()
    failures: tuple[SearchFailure, ...] = ()
