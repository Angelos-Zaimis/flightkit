"""Search engine: fan-out and fallback."""

import asyncio

from flightkit.core.expand import DEFAULT_MAX_SEARCHES, expand
from flightkit.core.ports import Cache, FareSource
from flightkit.models import PricedTrip, Search, SearchFailure, SearchResult, TripQuery


class Engine:
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
        results = await asyncio.gather(
            *(self._search_one(s) for s in searches), return_exceptions=True
        )

        trips: list[PricedTrip] = []
        failures: list[SearchFailure] = []

        for search, result in zip(searches, results, strict=True):
            if isinstance(result, Exception):
                error = f"{type(result).__name__}: {result}"
                failures.append(SearchFailure(search=search, error=error))
            elif isinstance(result, BaseException):
                raise result
            else:
                trips.extend(result)
        return SearchResult(trips=tuple(trips), failures=tuple(failures))

    async def search_trips(self, query: TripQuery) -> SearchResult:
        """Search every concrete trip a TripQuery covers."""
        return await self.search_many(expand(query, max_searches=self._max_searches))

    async def _search_one(self, search: Search) -> list[PricedTrip]:
        if self._cache is not None:
            cached = await self._cache.get(search)
            if cached is not None:
                return cached

        task = self._in_flight.get(search)
        if task is None:
            task = asyncio.create_task(self._fetch(search))
            self._in_flight[search] = task
            task.add_done_callback(lambda done: self._forget(search, done))
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
            task.exception()
