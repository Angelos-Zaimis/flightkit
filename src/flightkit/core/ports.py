"""Interfaces the core depends on."""

from typing import Protocol

from flightkit.models import PricedTrip, Search


class FareSource(Protocol):
    async def search(self, search: Search) -> list[PricedTrip]: ...


class Cache(Protocol):
    """Stores search results for reuse."""

    async def get(self, search: Search) -> list[PricedTrip] | None: ...

    async def set(self, search: Search, trips: list[PricedTrip]) -> None: ...
