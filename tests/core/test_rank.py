from datetime import date, datetime, timezone
from decimal import Decimal

from flightkit.core.rank import rank
from flightkit.models import (
    Price,
    PricedTrip,
    Search,
    SearchFailure,
    SearchResult,
    SearchStats,
    TripResult,
)


def _trip(
    destination: str = "ATH",
    day: int = 1,
    amount: str = "100",
    currency: str = "EUR",
    stops: int = 0,
    confidence: float | None = 0.9,
    carrier: str = "LX",
) -> PricedTrip:
    return PricedTrip(
        price=Price(amount=amount, currency=currency),
        confidence=confidence,
        carrier=carrier,
        stops=stops,
        deeplink="https://example.com/book",
        fetched_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        source="prediction" if confidence is not None else "live",
        search=Search(origin="ZRH", destination=destination, depart_date=date(2027, 6, day)),
    )


def _ranked(*trips: PricedTrip) -> TripResult:
    return rank(SearchResult(trips=trips))


def test_sorts_cheapest_first():
    result = _ranked(_trip(amount="150"), _trip(amount="89"), _trip(amount="120"))

    assert [t.price.amount for t in result.currencies["EUR"].trips] == [
        Decimal("89"),
        Decimal("120"),
        Decimal("150"),
    ]


def test_price_comparison_is_numeric_not_text():
    result = _ranked(_trip(amount="100"), _trip(amount="99.5"))

    assert result.currencies["EUR"].trips[0].price.amount == Decimal("99.5")


def test_equal_price_prefers_fewer_stops():
    result = _ranked(_trip(stops=1, carrier="A3"), _trip(stops=0, carrier="LX"))

    assert result.currencies["EUR"].trips[0].carrier == "LX"


def test_equal_price_and_stops_prefers_higher_confidence():
    result = _ranked(_trip(confidence=0.6, carrier="A3"), _trip(confidence=0.9, carrier="LX"))

    assert result.currencies["EUR"].trips[0].carrier == "LX"


def test_live_fare_counts_as_fully_confident():
    result = _ranked(_trip(confidence=0.99, carrier="A3"), _trip(confidence=None, carrier="LX"))

    assert result.currencies["EUR"].trips[0].carrier == "LX"


def test_then_earlier_departure():
    result = _ranked(_trip(day=5), _trip(day=2))

    assert result.currencies["EUR"].trips[0].search.depart_date == date(2027, 6, 2)


def test_order_is_the_same_whatever_the_input_order():
    trips = [_trip(destination=d, day=n) for d in ["ATH", "HER"] for n in [1, 2, 3]]

    assert _ranked(*trips) == _ranked(*reversed(trips))


def test_currencies_are_never_compared():
    result = _ranked(
        _trip(destination="ATH", amount="100", currency="EUR"),
        _trip(destination="HER", amount="50", currency="USD"),
    )

    assert list(result.currencies) == ["EUR", "USD"]
    assert result.currencies["EUR"].cheapest_by_destination["ATH"].price.amount == 100
    assert "HER" not in result.currencies["EUR"].cheapest_by_destination


def test_cheapest_by_destination_is_sorted_by_price():
    result = _ranked(
        _trip(destination="HER", amount="112"),
        _trip(destination="ATH", amount="95"),
        _trip(destination="ATH", amount="89"),
        _trip(destination="HER", amount="140"),
    )

    cheapest = result.currencies["EUR"].cheapest_by_destination
    assert list(cheapest) == ["ATH", "HER"]
    assert cheapest["ATH"].price.amount == 89
    assert cheapest["HER"].price.amount == 112


def test_calendar_has_cheapest_per_day_in_date_order():
    result = _ranked(
        _trip(day=3, amount="80"),
        _trip(day=1, amount="150"),
        _trip(day=1, amount="120", destination="HER"),
        _trip(day=2, amount="99"),
    )

    calendar = result.currencies["EUR"].calendar
    assert list(calendar) == [date(2027, 6, 1), date(2027, 6, 2), date(2027, 6, 3)]
    assert calendar[date(2027, 6, 1)].search.destination == "HER"
    assert calendar[date(2027, 6, 1)].price.amount == 120


def test_keeps_failures_and_stats():
    search = Search(origin="ZRH", destination="HER", depart_date=date(2027, 6, 1))
    failure = SearchFailure(search=search, error="TimeoutError: slow")
    stats = SearchStats(searches=2, calls=2, failures=1)

    result = rank(SearchResult(trips=(_trip(),), failures=(failure,), stats=stats))

    assert result.failures == (failure,)
    assert result.stats == stats


def test_no_trips_gives_no_currencies():
    assert rank(SearchResult()).currencies == {}


def test_result_round_trips_through_json():
    result = _ranked(_trip(day=1), _trip(day=2, destination="HER", currency="USD"))

    assert TripResult.model_validate_json(result.model_dump_json()) == result
