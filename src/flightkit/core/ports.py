"""Interfaces the core depends on."""

from typing import Protocol

from flightkit.models import PricedTrip, Search


class FareSource(Protocol):
    async def search(self, search: Search) -> list[PricedTrip]: ...
