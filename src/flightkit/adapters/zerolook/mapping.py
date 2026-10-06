"""Conversions between flightkit models and Zerolook's formats."""

from flightkit.adapters.zerolook.wire import ZerolookSearchRequest, ZerolookTrip
from flightkit.models import Price, PricedTrip, Search


def to_search_request(search: Search) -> ZerolookSearchRequest:
    """Convert a Search into a Zerolook search request."""
    return ZerolookSearchRequest(
        orig=search.origin,
        dest=search.destination,
        departDate=search.depart_date,
        returnDate=search.return_date,
        pax=search.passengers,
        cabin=search.cabin,
    )


def to_priced_trip(wire: ZerolookTrip, search: Search) -> PricedTrip:
    """Convert a Zerolook trip into a PricedTrip."""
    return PricedTrip(
        price=Price(amount=wire.fareAmt, currency=wire.cur),
        confidence=wire.conf,
        carrier=wire.airline,
        stops=wire.stops,
        deeplink=wire.url,
        fetched_at=wire.ts,
        source="prediction",
        search=search,
    )
