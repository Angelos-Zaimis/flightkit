from datetime import date

import pytest

from flightkit.core.expand import DEFAULT_MAX_SEARCHES, count_searches, expand
from flightkit.errors import FlightkitError, TooManySearchesError
from flightkit.models import TripQuery

QUERY = {
    "origin": "ZRH",
    "destinations": ["ATH", "HER"],
    "depart_from": "2027-06-01",
    "depart_to": "2027-06-03",
}


def _query(**overrides) -> TripQuery:
    return TripQuery(**{**QUERY, **overrides})


def test_one_way_makes_one_search_per_destination_per_day():
    searches = expand(_query())

    assert [(s.destination, s.depart_date.day, s.return_date) for s in searches] == [
        ("ATH", 1, None),
        ("ATH", 2, None),
        ("ATH", 3, None),
        ("HER", 1, None),
        ("HER", 2, None),
        ("HER", 3, None),
    ]


def test_nights_range_adds_return_dates():
    searches = expand(_query(destinations=["ATH"], min_nights=6, max_nights=7))

    assert [(s.depart_date.day, s.return_date.day) for s in searches] == [
        (1, 7),
        (1, 8),
        (2, 8),
        (2, 9),
        (3, 9),
        (3, 10),
    ]


def test_return_date_crosses_month_end():
    searches = expand(
        _query(
            destinations=["ATH"],
            depart_from="2027-06-28",
            depart_to="2027-06-28",
            min_nights=7,
            max_nights=7,
        )
    )

    assert searches[0].return_date == date(2027, 7, 5)


def test_copies_origin_passengers_and_cabin():
    searches = expand(_query(origin="BSL", passengers=3, cabin="business"))

    assert {(s.origin, s.passengers, s.cabin) for s in searches} == {("BSL", 3, "business")}


def test_single_day_single_destination():
    searches = expand(_query(destinations=["ATH"], depart_to="2027-06-01"))

    assert len(searches) == 1


def test_no_duplicate_searches():
    searches = expand(_query(min_nights=5, max_nights=9))

    assert len(set(searches)) == len(searches)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, 2 * 3),
        ({"min_nights": 6, "max_nights": 8}, 2 * 3 * 3),
        ({"min_nights": 7, "max_nights": 7}, 2 * 3 * 1),
        ({"depart_to": "2027-06-30"}, 2 * 30),
    ],
)
def test_count_matches_what_expand_builds(overrides, expected):
    query = _query(**overrides)

    assert count_searches(query) == expected
    assert len(expand(query)) == expected


def test_too_many_searches_raises_before_building():
    query = _query(depart_to="2027-07-30", min_nights=6, max_nights=8)  # 2 × 60 × 3 = 360

    with pytest.raises(TooManySearchesError) as exc:
        expand(query, max_searches=100)

    assert exc.value.count == 360
    assert exc.value.limit == 100
    assert str(exc.value) == "query expands to 360 searches, limit is 100"


def test_exactly_at_the_limit_is_allowed():
    assert len(expand(_query(), max_searches=6)) == 6


def test_default_limit():
    many = [f"A{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(10)]
    query = _query(destinations=many, depart_to="2027-07-30")  # 10 × 60 = 600

    with pytest.raises(TooManySearchesError) as exc:
        expand(query)

    assert exc.value.limit == DEFAULT_MAX_SEARCHES


def test_error_can_be_caught_as_flightkit_or_value_error():
    with pytest.raises(FlightkitError):
        expand(_query(), max_searches=1)
    with pytest.raises(ValueError):
        expand(_query(), max_searches=1)


def test_same_query_gives_same_order():
    assert expand(_query(min_nights=6, max_nights=8)) == expand(_query(min_nights=6, max_nights=8))
