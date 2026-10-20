"""Interfaces the core depends on."""

from typing import Protocol

from flightkit.models import PricedTrip, Search


class FareSource(Protocol):
    """Anything that can price a search, such as a provider client."""

    async def search(self, search: Search) -> list[PricedTrip]:
        """Return the priced trips for one concrete search."""
        ...


class Cache(Protocol):
    """Stores search results for reuse."""

    async def get(self, search: Search) -> list[PricedTrip] | None:
        """Return the stored trips, or None if missing or expired."""
        ...

    async def set(self, search: Search, trips: list[PricedTrip]) -> None:
        """Store the trips found for a search."""
        ...
