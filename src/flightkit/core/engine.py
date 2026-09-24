"""Search engine: fan-out and fallback."""

import asyncio

from flightkit.core.ports import FareSource
from flightkit.models import PricedTrip, Search, SearchFailure, SearchResult


class Engine:
    def __init__(self, source: FareSource, *, max_concurrency: int = 10) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._source = source
        self._limit = asyncio.Semaphore(max_concurrency)

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

    async def _search_one(self, search: Search) -> list[PricedTrip]:
        async with self._limit:
            return await self._source.search(search)
