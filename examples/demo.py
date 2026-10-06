"""A tour of flightkit against a simulated Zerolook API. No API key needed.

uv run examples/demo.py           # with simulated 429s and 503s
uv run examples/demo.py --calm    # without them
"""

import argparse
import asyncio
import time
from collections.abc import Awaitable
from datetime import date
from typing import TypeVar

from flightkit import Engine, MemoryCache, TooManySearchesError, TripQuery, TripResult
from flightkit.adapters.zerolook import FakeZerolook, ZerolookClient
from flightkit.core.expand import count_searches

T = TypeVar("T")

QUERY = TripQuery(
    origin="ZRH",
    destinations=("ATH", "HER", "JTR"),
    depart_from=date(2027, 6, 1),
    depart_to=date(2027, 6, 14),
    min_nights=6,
    max_nights=8,
)
AGENTS = 20


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--calm", action="store_true", help="no simulated provider errors")
    args = parser.parse_args()
    asyncio.run(tour(chaos=not args.calm))


async def tour(*, chaos: bool) -> None:
    fake = FakeZerolook(chaos=chaos)
    async with ZerolookClient(
        "https://zerolook.test", "demo", transport=fake.transport(), backoff=0.1
    ) as client:
        engine = Engine(client, cache=MemoryCache(), max_concurrency=20)

        heading("1. Flexible search")
        print(f"   {describe(QUERY)}")
        result, seconds = await timed(engine.search_trips(QUERY))
        s = result.stats
        print(f"   {s.searches} searches in {seconds:.1f}s · {s.calls} provider calls · ", end="")
        print(f"{fake.errors} temporary errors retried · {s.failures} failed")
        show_cheapest(result)
        show_calendar(result)

        heading("2. The same search again")
        before = fake.requests
        result, seconds = await timed(engine.search_trips(QUERY))
        s = result.stats
        print(f"   {s.cache_hits} cache hits · {fake.requests - before} provider requests ", end="")
        print(f"· {seconds * 1000:.0f} ms")

        heading(f"3. {AGENTS} agents ask at the same moment")
        fresh = Engine(client, cache=MemoryCache(), max_concurrency=20)
        before = fake.requests
        results = await asyncio.gather(*(fresh.search_trips(QUERY) for _ in range(AGENTS)))
        asked = sum(r.stats.searches for r in results)
        calls = sum(r.stats.calls for r in results)
        each = count_searches(QUERY)
        print(f"   {AGENTS} × {each} = {asked} searches requested · {calls} provider calls")
        print(f"   ({fake.requests - before} HTTP requests including retries)")

        heading("4. A query that's too big")
        huge = QUERY.model_copy(
            update={
                "destinations": ("ATH", "HER", "JTR", "CHQ", "RHO", "CFU", "JMK", "KGS"),
                "depart_to": date(2027, 7, 30),
            }
        )
        before = fake.requests
        try:
            await engine.search_trips(huge)
        except TooManySearchesError as e:
            print(f"   refused: {e} · {fake.requests - before} provider requests")
    print()


def describe(query: TripQuery) -> str:
    destinations = ", ".join(query.destinations)
    window = f"{query.depart_from:%b} {query.depart_from.day}–{query.depart_to.day}"
    nights = f"{query.min_nights}–{query.max_nights} nights"
    return f"{query.origin} → {destinations} · {window} · {nights}"


def show_cheapest(result: TripResult) -> None:
    print("\n   Cheapest per destination")
    for code, trip in result.currencies["EUR"].cheapest_by_destination.items():
        search = trip.search
        stops = "direct" if trip.stops == 0 else f"{trip.stops} stop" + "s" * (trip.stops > 1)
        print(
            f"     {code}  €{trip.price.amount:>7}   {search.depart_date:%a %b %d}"
            f" → {search.return_date:%b %d}   {stops:<7}  conf {trip.confidence:.2f}"
        )


def show_calendar(result: TripResult) -> None:
    calendar = result.currencies["EUR"].calendar
    cheapest = min(t.price.amount for t in calendar.values())
    print("\n   Cheapest per departure day")
    for day, trip in calendar.items():
        bar = "█" * round(float(trip.price.amount / cheapest) * 10)
        marker = "  ← cheapest" if trip.price.amount == cheapest else ""
        price = f"€{trip.price.amount:>7}"
        print(f"     {day:%a %b %d}  {price}  {trip.search.destination}  {bar}{marker}")


def heading(text: str) -> None:
    print(f"\n{text}")


async def timed(awaitable: Awaitable[T]) -> tuple[T, float]:
    start = time.perf_counter()
    value = await awaitable
    return value, time.perf_counter() - start


if __name__ == "__main__":
    main()
