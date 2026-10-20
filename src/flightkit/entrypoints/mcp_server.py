"""MCP server. Requires the `mcp` extra.

Gives AI assistants flightkit's trip search as tools. The assistant starts it as the
`flightkit-mcp` command and talks to it over stdio.

Set ZEROLOOK_API_KEY (and optionally ZEROLOOK_BASE_URL) to search real Zerolook prices.
Without a key it runs against the simulated FakeZerolook, and every answer says so.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from flightkit import (
    Engine,
    MemoryCache,
    PricedTrip,
    TooManySearchesError,
    TripQuery,
    TripResult,
    ZerolookClient,
)
from flightkit.adapters.zerolook import FakeZerolook
from flightkit.core.expand import DEFAULT_MAX_SEARCHES, count_searches

BEST_TRIPS = 10
FAILURE_EXAMPLES = 3


class TripOption(BaseModel):
    destination: str
    depart_date: date
    return_date: date | None
    price: str = Field(description="Total price for all passengers, as a decimal string.")
    currency: str
    carrier: str
    stops: int
    confidence: float | None = Field(
        description="How sure the provider is about this price, 0 to 1. Empty for live fares."
    )
    booking_url: str


class DayPrice(BaseModel):
    depart_date: date
    price: str
    destination: str


class CurrencySummary(BaseModel):
    currency: str
    cheapest_by_destination: list[TripOption]
    best_trips: list[TripOption] = Field(description=f"Up to {BEST_TRIPS} cheapest trips overall.")
    calendar: list[DayPrice] = Field(description="Cheapest price per departure day.")


class TripSummary(BaseModel):
    simulated: bool = Field(description="True if prices come from a simulation, not Zerolook.")
    searches: int = Field(description="Concrete searches the query covered.")
    provider_calls: int
    cache_hits: int
    results: list[CurrencySummary] = Field(description="One entry per currency.")
    failed_searches: int
    retryable_failures: int = Field(description="Failed searches that may succeed if retried.")
    failure_examples: list[str]


class SearchEstimate(BaseModel):
    searches: int
    limit: int
    within_limit: bool
    advice: str | None


class _State:
    engine: Engine
    simulated: bool


state = _State()


@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncIterator[None]:
    api_key = os.environ.get("ZEROLOOK_API_KEY")
    if api_key:
        base_url = os.environ.get("ZEROLOOK_BASE_URL", "https://api.zerolook.ai")
        transport = None
    else:
        base_url, transport = "https://zerolook.test", FakeZerolook(chaos=False).transport()

    async with ZerolookClient(base_url, api_key or "simulated", transport=transport) as client:
        state.engine = Engine(client, cache=MemoryCache(), max_concurrency=20)
        state.simulated = api_key is None
        yield


server = MCPServer(
    "flightkit",
    instructions=(
        "Flight price search across flexible dates and several destinations. "
        "Call estimate_search first for large queries; if a query is too big, narrow the "
        "date window or the list of destinations. Prices may be predictions; check "
        "`confidence` and the `simulated` flag before presenting them as exact."
    ),
    lifespan=lifespan,
    log_level="WARNING",
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


@server.tool(annotations=READ_ONLY)
async def search_trips(query: TripQuery) -> TripSummary:
    """Find the cheapest flights for a flexible trip.

    Covers every departure day in the window, every destination and every stay length,
    and returns the cheapest options per destination, the best trips overall and the
    cheapest price per departure day.
    """
    try:
        result = await state.engine.search_trips(query)
    except TooManySearchesError as e:
        raise ToolError(_too_big(e.count, e.limit)) from e
    return _summarize(result, simulated=state.simulated)


@server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
async def estimate_search(query: TripQuery) -> SearchEstimate:
    """Count how many searches a trip query needs, without running any of them."""
    count = count_searches(query)
    within = count <= DEFAULT_MAX_SEARCHES
    advice = None if within else _too_big(count, DEFAULT_MAX_SEARCHES)
    return SearchEstimate(
        searches=count, limit=DEFAULT_MAX_SEARCHES, within_limit=within, advice=advice
    )


def main() -> None:
    server.run("stdio")


def _summarize(result: TripResult, *, simulated: bool) -> TripSummary:
    failures = result.failures
    return TripSummary(
        simulated=simulated,
        searches=result.stats.searches,
        provider_calls=result.stats.calls,
        cache_hits=result.stats.cache_hits,
        results=[
            CurrencySummary(
                currency=currency,
                cheapest_by_destination=[
                    _option(t) for t in group.cheapest_by_destination.values()
                ],
                best_trips=[_option(t) for t in group.trips[:BEST_TRIPS]],
                calendar=[
                    DayPrice(
                        depart_date=day,
                        price=str(t.price.amount),
                        destination=t.search.destination,
                    )
                    for day, t in group.calendar.items()
                ],
            )
            for currency, group in result.currencies.items()
        ],
        failed_searches=len(failures),
        retryable_failures=sum(f.retryable for f in failures),
        failure_examples=[f.error for f in failures[:FAILURE_EXAMPLES]],
    )


def _option(trip: PricedTrip) -> TripOption:
    return TripOption(
        destination=trip.search.destination,
        depart_date=trip.search.depart_date,
        return_date=trip.search.return_date,
        price=str(trip.price.amount),
        currency=trip.price.currency,
        carrier=trip.carrier,
        stops=trip.stops,
        confidence=trip.confidence,
        booking_url=str(trip.deeplink),
    )


def _too_big(count: int, limit: int) -> str:
    return (
        f"This query needs {count} searches, but the limit is {limit}. "
        "Try fewer destinations, a shorter departure window or a narrower range of nights."
    )


if __name__ == "__main__":
    main()
