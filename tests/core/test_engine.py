import asyncio
from datetime import date, datetime, timezone

import pytest

from flightkit.core.cache import MemoryCache
from flightkit.core.engine import Engine
from flightkit.core.expand import count_searches, expand
from flightkit.errors import TooManySearchesError
from flightkit.models import Price, PricedTrip, Search, SearchResult, TripQuery


def _search(destination: str, day: int = 1) -> Search:
    return Search(origin="ATH", destination=destination, depart_date=date(2026, 10, day))


def _distinct(n: int) -> list[Search]:
    """n different searches, so coalescing doesn't merge them."""
    return [_search("ZRH", day) for day in range(1, n + 1)]


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

    await Engine(source, max_concurrency=5).search_many(_distinct(28) * 2)

    assert len(source.calls) == 28
    assert source.max_in_flight == 5


async def test_parallel_calls_share_the_limit():
    source = FakeSource()
    engine = Engine(source, max_concurrency=5)

    await asyncio.gather(
        engine.search_many(_distinct(20)),
        engine.search_many([_search("LHR", day) for day in range(1, 21)]),
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


async def test_identical_searches_at_once_make_one_call():
    source = FakeSource()
    engine = Engine(source)

    results = await asyncio.gather(*(engine.search_many([_search("ZRH")]) for _ in range(50)))

    assert len(source.calls) == 1
    assert all(len(r.trips) == 1 for r in results)


async def test_duplicates_in_one_batch_make_one_call_each():
    source = FakeSource()

    result = await Engine(source).search_many([_search("ZRH")] * 3 + [_search("LHR")] * 3)

    assert len(source.calls) == 2
    assert [t.search.destination for t in result.trips] == ["ZRH"] * 3 + ["LHR"] * 3


async def test_different_searches_are_not_merged():
    source = FakeSource()

    await Engine(source).search_many([_search("ZRH", 1), _search("ZRH", 2)])

    assert len(source.calls) == 2


async def test_shared_failure_reaches_every_waiter():
    source = FailsFor("BAD")
    engine = Engine(source)

    results = await asyncio.gather(*(engine.search_many([_search("BAD")]) for _ in range(5)))

    assert len(source.calls) == 1
    assert all(len(r.failures) == 1 for r in results)


async def test_new_search_after_finish_calls_again():
    source = FailsFor("BAD")
    engine = Engine(source)

    await engine.search_many([_search("BAD")])
    await engine.search_many([_search("BAD")])

    assert len(source.calls) == 2
    assert engine._in_flight == {}


async def test_cancelling_one_caller_does_not_cancel_the_others():
    source = FakeSource(delay=0.1)
    engine = Engine(source)

    first = asyncio.create_task(engine.search_many([_search("ZRH")]))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(engine.search_many([_search("ZRH")]))
    await asyncio.sleep(0.01)
    first.cancel()

    result = await second

    assert len(result.trips) == 1
    assert len(source.calls) == 1


async def test_each_caller_gets_its_own_list():
    engine = Engine(FakeSource())

    a, b = await asyncio.gather(
        engine._search_one(_search("ZRH")), engine._search_one(_search("ZRH"))
    )

    assert a == b
    assert a is not b


async def test_coalescing_and_cache_together():
    source = FakeSource()
    engine = Engine(source, cache=MemoryCache())

    await asyncio.gather(*(engine.search_many([_search("ZRH")]) for _ in range(20)))
    await engine.search_many([_search("ZRH")])

    assert len(source.calls) == 1


def _trip_query(**overrides) -> TripQuery:
    data = {
        "origin": "ZRH",
        "destinations": ["ATH", "HER"],
        "depart_from": "2027-06-01",
        "depart_to": "2027-06-03",
        **overrides,
    }
    return TripQuery(**data)


async def test_search_trips_searches_every_expanded_search():
    source = FakeSource()
    query = _trip_query(min_nights=6, max_nights=7)

    result = await Engine(source).search_trips(query)

    assert source.calls == expand(query)
    assert len(result.trips) == count_searches(query) == 12


async def test_search_trips_too_big_raises_before_any_call():
    source = FakeSource()

    with pytest.raises(TooManySearchesError):
        await Engine(source, max_searches=5).search_trips(_trip_query())

    assert source.calls == []


async def test_search_trips_uses_the_cache():
    source = FakeSource()
    engine = Engine(source, cache=MemoryCache())

    await engine.search_trips(_trip_query())
    await engine.search_trips(_trip_query())

    assert len(source.calls) == 6


async def test_search_trips_keeps_partial_results():
    source = FailsFor("HER")

    result = await Engine(source).search_trips(_trip_query())

    assert {t.search.destination for t in result.trips} == {"ATH"}
    assert len(result.failures) == 3


@pytest.mark.parametrize("value", [0, -1])
def test_max_searches_must_be_positive(value):
    with pytest.raises(ValueError, match="max_searches"):
        Engine(FakeSource(), max_searches=value)
