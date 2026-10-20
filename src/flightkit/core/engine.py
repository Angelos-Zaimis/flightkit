"""Search engine: fan-out, caching and request coalescing."""

import asyncio
from dataclasses import dataclass

from flightkit.core.expand import DEFAULT_MAX_SEARCHES, expand
from flightkit.core.ports import Cache, FareSource
from flightkit.core.rank import rank
from flightkit.errors import ProviderError
from flightkit.models import (
    PricedTrip,
    Search,
    SearchFailure,
    SearchResult,
    SearchStats,
    TripQuery,
    TripResult,
)


@dataclass
class _Counter:
    """Mutable stats for one search_many call. Each call gets its own."""

    cache_hits: int = 0
    coalesced: int = 0
    calls: int = 0


class Engine:
    """Runs searches against a fare source with caching, coalescing, and a concurrency limit."""

    def __init__(
        self,
        source: FareSource,
        *,
        max_concurrency: int = 10,
        cache: Cache | None = None,
        max_searches: int = DEFAULT_MAX_SEARCHES,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if max_searches < 1:
            raise ValueError("max_searches must be at least 1")
        self._source = source
        self._max_searches = max_searches
        self._limit = asyncio.Semaphore(max_concurrency)
        self._cache = cache
        self._in_flight: dict[Search, asyncio.Task[list[PricedTrip]]] = {}

    async def search_many(self, searches: list[Search]) -> SearchResult:
        """Run all searches concurrently. Failed searches are reported, not raised."""
        counter = _Counter()
        results = await asyncio.gather(
            *(self._search_one(s, counter) for s in searches), return_exceptions=True
        )

        trips: list[PricedTrip] = []
        failures: list[SearchFailure] = []

        for search, result in zip(searches, results, strict=True):
            if isinstance(result, Exception):
                error = f"{type(result).__name__}: {result}"
                retryable = isinstance(result, ProviderError) and result.retryable
                failures.append(SearchFailure(search=search, error=error, retryable=retryable))
            elif isinstance(result, BaseException):
                raise result
            else:
                trips.extend(result)
        stats = SearchStats(
            searches=len(searches),
            cache_hits=counter.cache_hits,
            coalesced=counter.coalesced,
            calls=counter.calls,
            failures=len(failures),
        )
        return SearchResult(trips=tuple(trips), failures=tuple(failures), stats=stats)

    async def search_trips(self, query: TripQuery) -> TripResult:
        """Search every concrete trip a TripQuery covers, ranked per currency."""
        searches = expand(query, max_searches=self._max_searches)
        return rank(await self.search_many(searches))

    async def _search_one(self, search: Search, counter: _Counter) -> list[PricedTrip]:
        if self._cache is not None:
            cached = await self._cache.get(search)
            if cached is not None:
                counter.cache_hits += 1
                return cached

        task = self._in_flight.get(search)
        if task is None:
            counter.calls += 1
            task = asyncio.create_task(self._fetch(search))
            self._in_flight[search] = task
            task.add_done_callback(lambda done: self._forget(search, done))
        else:
            counter.coalesced += 1
        return list(await asyncio.shield(task))

    async def _fetch(self, search: Search) -> list[PricedTrip]:
        async with self._limit:
            trips = await self._source.search(search)

        if self._cache is not None:
            await self._cache.set(search, trips)
        return trips

    def _forget(self, search: Search, task: asyncio.Task[list[PricedTrip]]) -> None:
        if self._in_flight.get(search) is task:
            del self._in_flight[search]
        if not task.cancelled():
            task.exception()  # mark as seen, in case every caller was cancelled
