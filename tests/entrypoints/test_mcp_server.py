import json
from datetime import date, datetime, timezone

import httpx
import pytest

pytest.importorskip("mcp")

import respx  # noqa: E402
from mcp import Client  # noqa: E402

from flightkit import (  # noqa: E402
    Price,
    PricedTrip,
    Search,
    SearchFailure,
    SearchResult,
    SearchStats,
)
from flightkit.adapters.zerolook.fake import fake_trips  # noqa: E402
from flightkit.core.rank import rank  # noqa: E402
from flightkit.entrypoints.mcp_server import BEST_TRIPS, _summarize, server  # noqa: E402

QUERY = {
    "origin": "ZRH",
    "destinations": ["ATH", "HER", "JTR"],
    "depart_from": "2027-06-01",
    "depart_to": "2027-06-14",
    "min_nights": 6,
    "max_nights": 8,
}
TOO_BIG = {
    **QUERY,
    "destinations": ["ATH", "HER", "JTR", "CHQ", "RHO", "CFU", "JMK", "KGS"],
    "depart_to": "2027-07-30",
}

# Each test opens its own Client rather than sharing one from an async fixture: anyio
# requires its task group to be entered and exited in the same task, and pytest-asyncio
# runs fixture setup and teardown in different ones.


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    monkeypatch.delenv("ZEROLOOK_API_KEY", raising=False)


async def _tools() -> dict:
    async with Client(server) as client:
        return {t.name: t for t in (await client.list_tools()).tools}


async def _call(tool: str, query: dict):
    async with Client(server) as client:
        return await client.call_tool(tool, {"query": query})


async def test_lists_both_tools_as_read_only():
    tools = await _tools()

    assert set(tools) == {"search_trips", "estimate_search"}
    assert all(t.annotations.read_only_hint for t in tools.values())
    assert tools["search_trips"].annotations.open_world_hint is True
    assert tools["estimate_search"].annotations.open_world_hint is False


async def test_trip_query_descriptions_reach_the_agent():
    tool = (await _tools())["search_trips"]
    fields = tool.input_schema["$defs"]["TripQuery"]["properties"]

    assert fields and all(f.get("description") for f in fields.values())
    assert tool.output_schema is not None


async def test_estimate_within_limit():
    result = await _call("estimate_search", QUERY)

    assert result.structured_content == {
        "searches": 126,
        "limit": 500,
        "within_limit": True,
        "advice": None,
    }


async def test_estimate_too_big_gives_advice():
    result = await _call("estimate_search", TOO_BIG)

    assert result.structured_content["within_limit"] is False
    assert "1440 searches" in result.structured_content["advice"]
    assert "shorter departure window" in result.structured_content["advice"]


async def test_search_without_key_is_simulated_and_compact():
    result = await _call("search_trips", QUERY)
    summary = result.structured_content

    assert not result.is_error
    assert summary["simulated"] is True
    assert summary["searches"] == 126
    assert summary["failed_searches"] == 0
    eur = summary["results"][0]
    assert eur["currency"] == "EUR"
    assert [o["destination"] for o in eur["cheapest_by_destination"]] == ["HER", "ATH", "JTR"]
    assert len(eur["best_trips"]) == BEST_TRIPS
    assert len(eur["calendar"]) == 14
    assert len(json.dumps(summary)) < 6000


async def test_repeat_search_is_served_from_the_cache():
    async with Client(server) as client:
        await client.call_tool("search_trips", {"query": QUERY})
        result = await client.call_tool("search_trips", {"query": QUERY})

    assert result.structured_content["provider_calls"] == 0
    assert result.structured_content["cache_hits"] == 126


async def test_too_big_query_is_an_actionable_error():
    result = await _call("search_trips", TOO_BIG)

    assert result.is_error
    assert "needs 1440 searches, but the limit is 500" in result.content[0].text


async def test_invalid_query_is_rejected():
    result = await _call("search_trips", {**QUERY, "destinations": ["ZRH"]})

    assert result.is_error
    assert "origin must not be one of the destinations" in result.content[0].text


async def test_with_api_key_it_calls_zerolook(monkeypatch):
    monkeypatch.setenv("ZEROLOOK_API_KEY", "real-key")
    monkeypatch.setenv("ZEROLOOK_BASE_URL", "https://zerolook.example")
    query = {**QUERY, "destinations": ["ATH"], "depart_to": "2027-06-01"}

    with respx.mock(base_url="https://zerolook.example") as zerolook:
        route = zerolook.post("/v1/search").mock(
            side_effect=lambda request: httpx.Response(
                200, json={"trips": fake_trips(json.loads(request.content))}
            )
        )
        result = await _call("search_trips", query)

    assert result.structured_content["simulated"] is False
    assert route.call_count == 3
    assert route.calls.last.request.headers["Authorization"] == "Bearer real-key"


def _trip(destination: str, amount: str, currency: str) -> PricedTrip:
    return PricedTrip(
        price=Price(amount=amount, currency=currency),
        confidence=0.9,
        carrier="LX",
        stops=0,
        deeplink="https://example.com/book",
        fetched_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        source="prediction",
        search=Search(origin="ZRH", destination=destination, depart_date=date(2027, 6, 1)),
    )


def test_summary_keeps_currencies_apart_and_counts_failures():
    failed = Search(origin="ZRH", destination="RHO", depart_date=date(2027, 6, 1))
    result = rank(
        SearchResult(
            trips=(_trip("ATH", "100", "EUR"), _trip("HER", "90", "USD")),
            failures=(
                SearchFailure(search=failed, error="RateLimitedError: slow down", retryable=True),
                SearchFailure(search=failed, error="AuthenticationError: bad key"),
            ),
            stats=SearchStats(searches=4, calls=4, failures=2),
        )
    )

    summary = _summarize(result, simulated=False)

    assert [r.currency for r in summary.results] == ["EUR", "USD"]
    assert summary.results[0].cheapest_by_destination[0].price == "100"
    assert summary.failed_searches == 2
    assert summary.retryable_failures == 1
    assert summary.failure_examples[0] == "RateLimitedError: slow down"
