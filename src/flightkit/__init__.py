"""Async SDK for flight-price search at scale."""

from importlib.metadata import version

from flightkit.adapters.zerolook import ZerolookClient
from flightkit.core.cache import MemoryCache
from flightkit.core.engine import Engine
from flightkit.core.ports import Cache, FareSource
from flightkit.errors import FlightkitError, TooManySearchesError
from flightkit.models import (
    CurrencyResult,
    Price,
    PricedTrip,
    Search,
    SearchFailure,
    SearchResult,
    SearchStats,
    TripQuery,
    TripResult,
)

__version__ = version("flightkit")

__all__ = [
    "Cache",
    "CurrencyResult",
    "Engine",
    "FareSource",
    "FlightkitError",
    "MemoryCache",
    "Price",
    "PricedTrip",
    "Search",
    "SearchFailure",
    "SearchResult",
    "SearchStats",
    "TooManySearchesError",
    "TripQuery",
    "TripResult",
    "ZerolookClient",
    "__version__",
]
