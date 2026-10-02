from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from flightkit.models import FlightkitModel, Price, PricedTrip, Search, TripQuery


class _Sample(FlightkitModel):
    code: str
    count: int


class TestFlightkitModel:
    def test_is_frozen(self):
        m = _Sample(code="ATH", count=1)
        with pytest.raises(ValidationError, match="frozen"):
            m.code = "ZRH"

    def test_model_copy_is_how_you_change_a_value(self):
        m = _Sample(code="ATH", count=1)
        changed = m.model_copy(update={"code": "ZRH"})
        assert changed.code == "ZRH"
        assert m.code == "ATH"

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError) as exc:
            _Sample(code="ATH", count=1, cuont=2)
        error = exc.value.errors()[0]
        assert error["type"] == "extra_forbidden"
        assert error["loc"] == ("cuont",)

    def test_strips_whitespace_from_strings(self):
        assert _Sample(code="  ATH \n", count=1).code == "ATH"

    def test_equal_models_are_equal_and_hash_the_same(self):
        a = _Sample(code="ATH", count=1)
        b = _Sample(code="ATH", count=1)
        assert a == b
        assert hash(a) == hash(b)

    def test_usable_as_dict_key(self):
        cache = {_Sample(code="ATH", count=1): "cached"}
        assert cache[_Sample(code=" ATH ", count=1)] == "cached"

    def test_different_values_are_different_keys(self):
        assert _Sample(code="ATH", count=1) != _Sample(code="ATH", count=2)


VALID = {"origin": "ATH", "destination": "ZRH", "depart_date": "2026-10-01"}


def _search(**overrides):
    return Search(**{**VALID, **overrides})


class TestSearch:
    def test_minimal_valid_search_uses_defaults(self):
        s = _search()
        assert s.origin == "ATH"
        assert s.destination == "ZRH"
        assert s.depart_date == date(2026, 10, 1)
        assert s.return_date is None
        assert s.passengers == 1
        assert s.cabin == "economy"

    @pytest.mark.parametrize("raw", ["zrh", "ZRH", "Zrh", "zrh ", " zrh", "\tzrh\n"])
    def test_iata_code_is_normalized(self, raw):
        assert _search(destination=raw).destination == "ZRH"

    @pytest.mark.parametrize("raw", ["ZR", "ZRHX", "Z1H", "z rh", "", "ZÜR"])
    def test_invalid_iata_code_is_rejected(self, raw):
        with pytest.raises(ValidationError) as exc:
            _search(destination=raw)
        assert exc.value.errors()[0]["loc"] == ("destination",)

    def test_date_strings_are_parsed(self):
        s = _search(return_date="2026-10-08")
        assert s.return_date == date(2026, 10, 8)

    @pytest.mark.parametrize("raw", ["banana", "2026-13-01", "01/10/2026"])
    def test_invalid_date_is_rejected(self, raw):
        with pytest.raises(ValidationError):
            _search(depart_date=raw)

    def test_same_day_return_is_allowed(self):
        assert _search(return_date="2026-10-01").return_date == date(2026, 10, 1)

    def test_return_before_departure_is_rejected(self):
        with pytest.raises(ValidationError, match="return_date must be on or after"):
            _search(return_date="2026-09-30")

    @pytest.mark.parametrize("origin", ["ZRH", "zrh", " zrh "])
    def test_same_origin_and_destination_is_rejected(self, origin):
        with pytest.raises(ValidationError, match="must differ"):
            _search(origin=origin)

    @pytest.mark.parametrize("n", [1, 9])
    def test_passenger_bounds_accepted(self, n):
        assert _search(passengers=n).passengers == n

    @pytest.mark.parametrize("n", [0, -1, 10])
    def test_passenger_bounds_rejected(self, n):
        with pytest.raises(ValidationError):
            _search(passengers=n)

    @pytest.mark.parametrize("cabin", ["economy", "premium_economy", "business", "first"])
    def test_valid_cabins(self, cabin):
        assert _search(cabin=cabin).cabin == cabin

    @pytest.mark.parametrize("cabin", ["luxury", "Economy", ""])
    def test_invalid_cabin_is_rejected(self, cabin):
        with pytest.raises(ValidationError):
            _search(cabin=cabin)

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            _search(adults=2)

    def test_is_frozen(self):
        with pytest.raises(ValidationError, match="frozen"):
            _search().origin = "LHR"

    def test_differently_written_equal_searches_share_a_cache_key(self):
        a = _search()
        b = Search(origin=" ath", destination="zrh ", depart_date=date(2026, 10, 1))
        assert a == b
        assert {a: "cached"}[b] == "cached"

    def test_json_round_trip(self):
        s = _search(return_date="2026-10-08", passengers=2, cabin="business")
        assert Search.model_validate_json(s.model_dump_json()) == s


class TestPrice:
    @pytest.mark.parametrize("raw", ["129.99", 129.99, Decimal("129.99")])
    def test_amount_is_exact_decimal(self, raw):
        assert _price(amount=raw).amount == Decimal("129.99")

    def test_zero_is_allowed(self):
        assert _price(amount="0").amount == 0

    @pytest.mark.parametrize("raw", ["-0.01", "abc", "NaN", "Infinity"])
    def test_invalid_amount_is_rejected(self, raw):
        with pytest.raises(ValidationError):
            _price(amount=raw)

    @pytest.mark.parametrize("raw", ["eur", "EUR", " eur "])
    def test_currency_is_normalized(self, raw):
        assert _price(currency=raw).currency == "EUR"

    @pytest.mark.parametrize("raw", ["EU", "EURO", "E1R", ""])
    def test_invalid_currency_is_rejected(self, raw):
        with pytest.raises(ValidationError):
            _price(currency=raw)

    def test_json_keeps_exact_amount(self):
        p = _price(amount="0.10")
        assert Price.model_validate_json(p.model_dump_json()) == p


def _price(**overrides):
    return Price(**{"amount": "129.99", "currency": "EUR", **overrides})


TRIP = {
    "price": {"amount": "129.99", "currency": "EUR"},
    "confidence": 0.87,
    "carrier": "LX",
    "stops": 0,
    "deeplink": "https://example.com/book/123",
    "fetched_at": "2026-09-23T10:00:00Z",
    "source": "prediction",
    "search": VALID,
}


def _trip(**overrides):
    return PricedTrip(**{**TRIP, **overrides})


class TestPricedTrip:
    def test_valid_trip_parses_nested_models(self):
        t = _trip()
        assert isinstance(t.price, Price)
        assert isinstance(t.search, Search)
        assert t.price.amount == Decimal("129.99")

    @pytest.mark.parametrize("carrier", ["LX", "A3", "U2", "lx"])
    def test_real_airline_codes_are_accepted(self, carrier):
        assert _trip(carrier=carrier).carrier == carrier.upper()

    @pytest.mark.parametrize("carrier", ["", "L", "LXX", "L-"])
    def test_invalid_airline_codes_are_rejected(self, carrier):
        with pytest.raises(ValidationError):
            _trip(carrier=carrier)

    @pytest.mark.parametrize("value", [0, 0.5, 1])
    def test_confidence_in_range(self, value):
        assert _trip(confidence=value).confidence == value

    @pytest.mark.parametrize("value", [-0.1, 1.1, float("nan")])
    def test_confidence_out_of_range_is_rejected(self, value):
        with pytest.raises(ValidationError):
            _trip(confidence=value)

    def test_live_fare_can_omit_confidence(self):
        data = {k: v for k, v in TRIP.items() if k != "confidence"}
        assert PricedTrip(**{**data, "source": "live"}).confidence is None

    def test_prediction_requires_confidence(self):
        with pytest.raises(ValidationError, match="confidence is required"):
            _trip(confidence=None, source="prediction")

    def test_negative_stops_rejected(self):
        with pytest.raises(ValidationError):
            _trip(stops=-1)

    @pytest.mark.parametrize("link", ["banana", "ftp://example.com/x", ""])
    def test_invalid_deeplink_is_rejected(self, link):
        with pytest.raises(ValidationError):
            _trip(deeplink=link)

    @pytest.mark.parametrize("source", ["prediction", "live"])
    def test_valid_sources(self, source):
        assert _trip(source=source).source == source

    def test_unknown_source_is_rejected(self):
        with pytest.raises(ValidationError):
            _trip(source="cache")

    def test_is_hashable(self):
        assert {_trip(): "cached"}[_trip()] == "cached"

    def test_json_round_trip(self):
        t = _trip()
        assert PricedTrip.model_validate_json(t.model_dump_json()) == t

    def test_fetched_at_parses_timezone(self):
        t = _trip(fetched_at="2026-09-23T12:00:00+02:00")
        assert t.fetched_at.utcoffset() == timedelta(hours=2)

    @pytest.mark.parametrize("raw", ["2026-09-23T10:00:00", "2026-09-23", "banana"])
    def test_fetched_at_without_timezone_is_rejected(self, raw):
        with pytest.raises(ValidationError):
            _trip(fetched_at=raw)

    def test_same_moment_in_different_timezones_is_equal(self):
        utc = _trip(fetched_at="2026-09-23T10:00:00Z")
        athens = _trip(fetched_at="2026-09-23T13:00:00+03:00")
        assert utc == athens


QUERY = {
    "origin": "ZRH",
    "destinations": ["ATH", "HER"],
    "depart_from": "2027-06-01",
    "depart_to": "2027-06-14",
}


def _query(**overrides):
    return TripQuery(**{**QUERY, **overrides})


class TestTripQuery:
    def test_minimal_query_is_one_way_with_defaults(self):
        q = _query()
        assert q.origin == "ZRH"
        assert q.destinations == ("ATH", "HER")
        assert q.min_nights is None and q.max_nights is None
        assert q.passengers == 1
        assert q.cabin == "economy"

    def test_codes_are_normalized(self):
        q = _query(origin=" zrh", destinations=["ath", "Her "])
        assert q.origin == "ZRH"
        assert q.destinations == ("ATH", "HER")

    def test_dates_are_parsed(self):
        q = _query()
        assert q.depart_from == date(2027, 6, 1)
        assert q.depart_to == date(2027, 6, 14)

    def test_nights_range(self):
        q = _query(min_nights=6, max_nights=8)
        assert (q.min_nights, q.max_nights) == (6, 8)

    def test_same_min_and_max_nights_is_allowed(self):
        assert _query(min_nights=7, max_nights=7).min_nights == 7

    def test_single_day_window_is_allowed(self):
        assert _query(depart_to="2027-06-01").depart_to == date(2027, 6, 1)

    def test_window_of_exactly_max_days_is_allowed(self):
        assert _query(depart_to="2027-07-30").depart_to == date(2027, 7, 30)  # 60 days

    def test_window_one_day_over_max_is_rejected(self):
        with pytest.raises(ValidationError, match="at most 60 days"):
            _query(depart_to="2027-07-31")  # 61 days

    def test_reversed_window_is_rejected(self):
        with pytest.raises(ValidationError, match="depart_to must be on or after"):
            _query(depart_to="2027-05-31")

    @pytest.mark.parametrize("origin", ["ATH", "ath", " ATH "])
    def test_origin_in_destinations_is_rejected(self, origin):
        with pytest.raises(ValidationError, match="origin must not be one of the destinations"):
            _query(origin=origin)

    def test_duplicate_destinations_are_rejected(self):
        with pytest.raises(ValidationError, match="duplicates"):
            _query(destinations=["ATH", "ath"])

    def test_empty_destinations_rejected(self):
        with pytest.raises(ValidationError):
            _query(destinations=[])

    def test_twenty_destinations_allowed_but_not_more(self):
        codes = [f"A{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(21)]
        assert len(_query(destinations=codes[:20]).destinations) == 20
        with pytest.raises(ValidationError):
            _query(destinations=codes)

    @pytest.mark.parametrize("nights", [{"min_nights": 5}, {"max_nights": 5}])
    def test_only_one_nights_field_is_rejected(self, nights):
        with pytest.raises(ValidationError, match="both min_nights and max_nights"):
            _query(**nights)

    def test_min_nights_above_max_nights_is_rejected(self):
        with pytest.raises(ValidationError, match="min_nights must not be greater than max_nights"):
            _query(min_nights=9, max_nights=6)

    @pytest.mark.parametrize("value", [0, 31])
    def test_nights_out_of_range_rejected(self, value):
        with pytest.raises(ValidationError):
            _query(min_nights=value, max_nights=value)

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            _query(destination="ATH")

    def test_is_frozen_and_hashable(self):
        q = _query()
        with pytest.raises(ValidationError, match="frozen"):
            q.origin = "BSL"
        assert {q: "cached"}[_query()] == "cached"

    def test_schema_has_descriptions_for_agents(self):
        properties = TripQuery.model_json_schema()["properties"]
        assert all(p.get("description") for p in properties.values())
