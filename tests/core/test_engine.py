import asyncio
from datetime import date, datetime, timezone

import pytest

from flightkit.core.cache import MemoryCache
from flightkit.core.engine import Engine
from flightkit.models import Price, PricedTrip, Search, SearchResult


def _search(destination: str) -> Search:
    return Search(origin="ATH", destination=destination, depart_date=date(2026, 10, 1))


def _trip(search: Search, carrier: str = "LX") -> PricedTrip:
    return PricedTrip(
        price=Price(amount="100", currency="EUR"),
        confidence=0.9,
        carrier=carrier,
        stops=0,
        deeplink="https://example.com/book",
        fetched_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        source="prediction",
        search=search,
    )


class FakeSource:
    """Returns one trip per search and records how many ran at once."""

    def __init__(self, delay: float = 0.01) -> None:
        self.delay = delay
        self.calls: list[Search] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def search(self, search: Search) -> list[PricedTrip]:
        self.calls.append(search)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return [_trip(search)]
        finally:
            self.in_flight -= 1


class FailsFor(FakeSource):
    """Raises for the given destinations, succeeds for the rest."""

    def __init__(self, *bad: str, error: Exception | None = None) -> None:
        super().__init__()
        self.bad = set(bad)
        self.error = error or TimeoutError("zerolook too slow")

    async def search(self, search: Search) -> list[PricedTrip]:
        if search.destination in self.bad:
            self.calls.append(search)
            raise self.error
        return await super().search(search)


async def test_returns_trips_from_every_search_in_order():
    searches = [_search(d) for d in ["ZRH", "LHR", "CDG"]]

    result = await Engine(FakeSource()).search_many(searches)

    assert [t.search.destination for t in result.trips] == ["ZRH", "LHR", "CDG"]
    assert result.failures == ()


async def test_flattens_multiple_trips_per_search():
    class TwoTrips(FakeSource):
        async def search(self, search: Search) -> list[PricedTrip]:
            return [_trip(search, "LX"), _trip(search, "A3")]

    result = await Engine(TwoTrips()).search_many([_search("ZRH"), _search("LHR")])

    assert [t.carrier for t in result.trips] == ["LX", "A3", "LX", "A3"]


async def test_no_searches_makes_no_calls():
    source = FakeSource()
    assert await Engine(source).search_many([]) == SearchResult()
    assert source.calls == []


async def test_sends_each_search_to_the_source():
    source = FakeSource()
    searches = [_search(d) for d in ["ZRH", "LHR"]]

    await Engine(source).search_many(searches)

    assert source.calls == searches


async def test_searches_run_concurrently():
    source = FakeSource()

    await Engine(source).search_many([_search(d) for d in ["ZRH", "LHR", "CDG", "FRA", "MAD"]])

    assert source.max_in_flight == 5


async def test_never_exceeds_max_concurrency():
    source = FakeSource()

    await Engine(source, max_concurrency=5).search_many([_search("ZRH")] * 50)

    assert len(source.calls) == 50
    assert source.max_in_flight == 5


async def test_parallel_calls_share_the_limit():
    source = FakeSource()
    engine = Engine(source, max_concurrency=5)

    await asyncio.gather(
        engine.search_many([_search("ZRH")] * 20),
        engine.search_many([_search("LHR")] * 20),
    )

    assert source.max_in_flight == 5


async def test_one_failure_keeps_the_other_results():
    searches = [_search(d) for d in ["ZRH", "BAD", "LHR"]]

    result = await Engine(FailsFor("BAD")).search_many(searches)

    assert [t.search.destination for t in result.trips] == ["ZRH", "LHR"]
    assert len(result.failures) == 1
    assert result.failures[0].search == _search("BAD")
    assert result.failures[0].error == "TimeoutError: zerolook too slow"


async def test_all_failing_returns_only_failures():
    searches = [_search(d) for d in ["ZRH", "LHR"]]

    result = await Engine(FailsFor("ZRH", "LHR")).search_many(searches)

    assert result.trips == ()
    assert [f.search.destination for f in result.failures] == ["ZRH", "LHR"]


async def test_failure_keeps_the_error_type():
    source = FailsFor("ZRH", error=ValueError("bad payload"))

    result = await Engine(source).search_many([_search("ZRH")])

    assert result.failures[0].error == "ValueError: bad payload"


async def test_failed_search_releases_its_slot():
    engine = Engine(FailsFor("BAD"), max_concurrency=1)

    first = await engine.search_many([_search("BAD")])
    second = await asyncio.wait_for(engine.search_many([_search("ZRH")]), timeout=1)

    assert len(first.failures) == 1
    assert len(second.trips) == 1


async def test_cancelling_stops_the_search_instead_of_reporting_a_failure():
    class Hangs(FakeSource):
        async def search(self, search: Search) -> list[PricedTrip]:
            await asyncio.sleep(10)
            return []

    task = asyncio.create_task(Engine(Hangs()).search_many([_search("ZRH")]))
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_result_serializes_to_json():
    result = await Engine(FailsFor("BAD")).search_many([_search("ZRH"), _search("BAD")])

    assert SearchResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("value", [0, -1])
def test_max_concurrency_must_be_positive(value):
    with pytest.raises(ValueError, match="at least 1"):
        Engine(FakeSource(), max_concurrency=value)


async def test_cache_hit_skips_the_source():
    source = FakeSource()
    engine = Engine(source, cache=MemoryCache())

    first = await engine.search_many([_search("ZRH")])
    second = await engine.search_many([_search("ZRH")])

    assert len(source.calls) == 1
    assert second == first


async def test_cache_miss_calls_the_source_and_stores_the_result():
    source = FakeSource()
    cache = MemoryCache()

    await Engine(source, cache=cache).search_many([_search("ZRH")])

    assert len(source.calls) == 1
    assert await cache.get(_search("ZRH")) is not None


async def test_failures_are_not_cached():
    source = FailsFor("BAD")
    engine = Engine(source, cache=MemoryCache())

    await engine.search_many([_search("BAD")])
    await engine.search_many([_search("BAD")])

    assert len(source.calls) == 2


async def test_cache_hits_do_not_take_a_slot():
    class Blocks(FakeSource):
        async def search(self, search: Search) -> list[PricedTrip]:
            self.calls.append(search)
            await asyncio.Event().wait()  # never finishes
            return []

    cache = MemoryCache()
    await cache.set(_search("ZRH"), [])
    engine = Engine(Blocks(), max_concurrency=1, cache=cache)

    blocker = asyncio.create_task(engine.search_many([_search("LHR")]))
    await asyncio.sleep(0.01)  # LHR now holds the only slot

    result = await asyncio.wait_for(engine.search_many([_search("ZRH")]), timeout=1)

    assert result.failures == ()
    blocker.cancel()


async def test_mixed_hits_and_misses():
    source = FakeSource()
    cache = MemoryCache()
    await Engine(source, cache=cache).search_many([_search("ZRH")])

    result = await Engine(source, cache=cache).search_many([_search("ZRH"), _search("LHR")])

    assert [t.search.destination for t in result.trips] == ["ZRH", "LHR"]
    assert [s.destination for s in source.calls] == ["ZRH", "LHR"]
