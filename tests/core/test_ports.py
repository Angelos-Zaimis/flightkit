from datetime import date

from mypy import api as mypy_api

from flightkit.core.ports import FareSource
from flightkit.models import PricedTrip, Search

SEARCH = Search(origin="ATH", destination="ZRH", depart_date=date(2026, 10, 1))


class FakeSource:
    def __init__(self, trips: list[PricedTrip]) -> None:
        self.trips = trips
        self.calls: list[Search] = []

    async def search(self, search: Search) -> list[PricedTrip]:
        self.calls.append(search)
        return self.trips


def _mypy(code: str) -> tuple[str, int]:
    stdout, _, status = mypy_api.run(["--config-file=", "--strict", "-c", code])
    return stdout, status


async def test_fake_source_works_through_the_protocol():
    source: FareSource = FakeSource([])
    assert await source.search(SEARCH) == []


def test_zerolook_client_satisfies_fare_source():
    out, status = _mypy(
        "from flightkit.adapters.zerolook import ZerolookClient\n"
        "from flightkit.core.ports import FareSource\n"
        "source: FareSource = ZerolookClient('http://x', 'k')\n"
    )
    assert status == 0, out


def test_wrong_signature_is_rejected():
    out, status = _mypy(
        "from flightkit.core.ports import FareSource\n"
        "from flightkit.models import PricedTrip\n"
        "class Wrong:\n"
        "    async def search(self, query: str) -> list[PricedTrip]:\n"
        "        return []\n"
        "source: FareSource = Wrong()\n"
    )
    assert status == 1
    assert "Incompatible types in assignment" in out
