"""Rank search results into per-currency views."""

from datetime import date
from decimal import Decimal

from flightkit.models import CurrencyResult, PricedTrip, SearchResult, TripResult


def rank(result: SearchResult) -> TripResult:
    """Group trips by currency, sort them, and build the summary views."""
    by_currency: dict[str, list[PricedTrip]] = {}
    for trip in result.trips:
        by_currency.setdefault(trip.price.currency, []).append(trip)

    return TripResult(
        currencies={
            currency: _rank_currency(trips) for currency, trips in sorted(by_currency.items())
        },
        failures=result.failures,
        stats=result.stats,
    )


def sort_key(trip: PricedTrip) -> tuple[Decimal, int, float, date, str, str]:
    """Cheapest first, then fewer stops, then higher confidence, then earlier departure.

    Live fares have no confidence; they're exact, so they rank as fully confident.
    The last two fields only make the order stable when everything else is equal.
    """
    confidence = 1.0 if trip.confidence is None else trip.confidence
    return (
        trip.price.amount,
        trip.stops,
        -confidence,
        trip.search.depart_date,
        trip.search.destination,
        trip.carrier,
    )


def _rank_currency(trips: list[PricedTrip]) -> CurrencyResult:
    ranked = sorted(trips, key=sort_key)

    cheapest_by_destination: dict[str, PricedTrip] = {}
    calendar: dict[date, PricedTrip] = {}
    for trip in ranked:
        cheapest_by_destination.setdefault(trip.search.destination, trip)
        calendar.setdefault(trip.search.depart_date, trip)

    return CurrencyResult(
        trips=tuple(ranked),
        cheapest_by_destination=cheapest_by_destination,
        calendar=dict(sorted(calendar.items())),
    )
