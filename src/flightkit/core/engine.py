"""Search engine: fan-out and fallback."""

import asyncio

from flightkit.core.ports import FareSource
from flightkit.models import PricedTrip, Search


class Engine:
    def __init__(self, source: FareSource) -> None:
        self._source = source

    async def search_many(self, searches: list[Search]) -> list[PricedTrip]:
        results = await asyncio.gather(*(self._source.search(s) for s in searches))
        return [trip for trips in results for trip in trips]
