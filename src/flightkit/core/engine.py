"""Search engine: fan-out and fallback."""

import asyncio

from flightkit.core.ports import FareSource
from flightkit.models import PricedTrip, Search


class Engine:
    def __init__(self, source: FareSource, *, max_concurrency: int = 10) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._source = source
        self._limit = asyncio.Semaphore(max_concurrency)

    async def search_many(self, searches: list[Search]) -> list[PricedTrip]:
        results = await asyncio.gather(*(self._search_one(s) for s in searches))
        return [trip for trips in results for trip in trips]

    async def _search_one(self, search: Search) -> list[PricedTrip]:
        async with self._limit:
            return await self._source.search(search)
