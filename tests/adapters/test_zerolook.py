from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from flightkit.adapters.zerolook.mapping import to_priced_trip, to_search_request
from flightkit.adapters.zerolook.wire import ZerolookTrip
from flightkit.models import PricedTrip, Search

RAW = {
    "fareAmt": "129.99",
    "cur": "eur",
    "airline": " LX",
    "conf": 0.87,
    "stops": 0,
    "url": "https://example.com/book/123",
    "ts": "2026-09-23T10:00:00Z",
}
SEARCH = Search(origin="ATH", destination="ZRH", depart_date=date(2026, 10, 1))


class TestZerolookTrip:
    def test_parses_raw_json(self):
        wire = ZerolookTrip.model_validate(RAW)
        assert wire.fareAmt == Decimal("129.99")
        assert wire.airline == "LX"
        assert wire.cur == "EUR"

    def test_unknown_fields_are_ignored(self):
        wire = ZerolookTrip.model_validate({**RAW, "newField": 123})
        assert not hasattr(wire, "newField")

    @pytest.mark.parametrize("missing", list(RAW))
    def test_missing_field_fails_and_names_it(self, missing):
        data = {k: v for k, v in RAW.items() if k != missing}
        with pytest.raises(ValidationError) as exc:
            ZerolookTrip.model_validate(data)
        assert exc.value.errors()[0]["loc"] == (missing,)


class TestToPricedTrip:
    def test_full_flow_json_to_priced_trip(self):
        trip = to_priced_trip(ZerolookTrip.model_validate(RAW), SEARCH)
        assert isinstance(trip, PricedTrip)
        assert trip.price.amount == Decimal("129.99")
        assert trip.price.currency == "EUR"
        assert trip.carrier == "LX"
        assert trip.confidence == 0.87
        assert str(trip.deeplink) == "https://example.com/book/123"
        assert trip.source == "prediction"
        assert trip.search == SEARCH

    def test_domain_rules_still_apply_after_mapping(self):
        wire = ZerolookTrip.model_validate({**RAW, "conf": 1.5})
        with pytest.raises(ValidationError):
            to_priced_trip(wire, SEARCH)


class TestToSearchRequest:
    def test_maps_every_field(self):
        search = Search(
            origin="ATH",
            destination="ZRH",
            depart_date=date(2026, 10, 1),
            return_date=date(2026, 10, 8),
            passengers=2,
            cabin="business",
        )
        assert to_search_request(search).model_dump(mode="json") == {
            "orig": "ATH",
            "dest": "ZRH",
            "departDate": "2026-10-01",
            "returnDate": "2026-10-08",
            "pax": 2,
            "cabin": "business",
        }

    def test_one_way_leaves_out_return_date(self):
        payload = to_search_request(SEARCH).model_dump(mode="json", exclude_none=True)
        assert "returnDate" not in payload
