"""In-memory result cache."""

import time
from collections import OrderedDict
from collections.abc import Callable

from flightkit.models import PricedTrip, Search


class MemoryCache:
    """Keeps recent search results in memory, with expiry and a size limit."""

    def __init__(
        self,
        *,
        ttl: float = 300.0,
        max_entries: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[Search, tuple[float, tuple[PricedTrip, ...]]] = OrderedDict()

    async def get(self, search: Search) -> list[PricedTrip] | None:
        entry = self._entries.get(search)
        if entry is None:
            return None
        stored_at, trips = entry
        if self._clock() - stored_at >= self._ttl:
            del self._entries[search]
            return None
        self._entries.move_to_end(search)
        return list(trips)

    async def set(self, search: Search, trips: list[PricedTrip]) -> None:
        self._entries[search] = (self._clock(), tuple(trips))
        self._entries.move_to_end(search)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)
