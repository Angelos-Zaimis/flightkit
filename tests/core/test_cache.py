from datetime import date, datetime, timezone

import pytest

from flightkit.core.cache import MemoryCache
from flightkit.models import Price, PricedTrip, Search


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _search(destination: str) -> Search:
    return Search(origin="ATH", destination=destination, depart_date=date(2026, 10, 1))


def _trip(search: Search) -> PricedTrip:
    return PricedTrip(
        price=Price(amount="100", currency="EUR"),
        confidence=0.9,
        carrier="LX",
        stops=0,
        deeplink="https://example.com/book",
        fetched_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        source="prediction",
        search=search,
    )


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def cache(clock):
    return MemoryCache(ttl=300, max_entries=3, clock=clock)


async def test_miss_returns_none(cache):
    assert await cache.get(_search("ZRH")) is None


async def test_hit_returns_saved_trips(cache):
    search = _search("ZRH")
    await cache.set(search, [_trip(search)])

    assert await cache.get(search) == [_trip(search)]


async def test_equal_searches_share_an_entry(cache):
    await cache.set(_search("ZRH"), [])

    same = Search(origin=" ath", destination="zrh ", depart_date="2026-10-01")
    assert await cache.get(same) == []


async def test_empty_result_is_a_hit_not_a_miss(cache):
    await cache.set(_search("ZRH"), [])
    assert await cache.get(_search("ZRH")) == []


async def test_fresh_just_before_ttl(cache, clock):
    await cache.set(_search("ZRH"), [])
    clock.now = 299.9

    assert await cache.get(_search("ZRH")) == []


async def test_expires_at_ttl(cache, clock):
    await cache.set(_search("ZRH"), [])
    clock.now = 300

    assert await cache.get(_search("ZRH")) is None
    assert len(cache) == 0


async def test_set_again_refreshes_the_timer(cache, clock):
    await cache.set(_search("ZRH"), [])
    clock.now = 200
    await cache.set(_search("ZRH"), [])
    clock.now = 400

    assert await cache.get(_search("ZRH")) == []


async def test_drops_least_recently_used_when_full(cache):
    for d in ["ZRH", "LHR", "CDG"]:
        await cache.set(_search(d), [])
    await cache.get(_search("ZRH"))  # ZRH is now the most recently used

    await cache.set(_search("FRA"), [])

    assert len(cache) == 3
    assert await cache.get(_search("LHR")) is None
    assert await cache.get(_search("ZRH")) == []


async def test_returned_list_is_a_copy(cache):
    search = _search("ZRH")
    await cache.set(search, [_trip(search)])

    (await cache.get(search)).clear()

    assert await cache.get(search) == [_trip(search)]


async def test_changing_the_input_list_does_not_change_the_cache(cache):
    search = _search("ZRH")
    trips = [_trip(search)]
    await cache.set(search, trips)

    trips.clear()

    assert await cache.get(search) == [_trip(search)]


@pytest.mark.parametrize("ttl", [0, -1])
def test_ttl_must_be_positive(ttl):
    with pytest.raises(ValueError, match="ttl"):
        MemoryCache(ttl=ttl)


@pytest.mark.parametrize("size", [0, -1])
def test_max_entries_must_be_positive(size):
    with pytest.raises(ValueError, match="max_entries"):
        MemoryCache(max_entries=size)
