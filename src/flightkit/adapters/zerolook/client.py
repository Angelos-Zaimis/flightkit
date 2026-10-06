"""HTTP client for the Zerolook API."""

import httpx
from typing_extensions import Self

from flightkit.adapters.zerolook.mapping import to_priced_trip, to_search_request
from flightkit.adapters.zerolook.wire import ZerolookTrip
from flightkit.models import PricedTrip, Search


class ZerolookClient:
    """Async client for the Zerolook search API."""

    def __init__(
        self, base_url: str, api_key: str, *, max_connections: int = 10, timeout: float = 10.0
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            limits=httpx.Limits(max_connections=max_connections),
            timeout=timeout,
        )

    async def search(self, search: Search) -> list[PricedTrip]:
        payload = to_search_request(search).model_dump(mode="json", exclude_none=True)
        response = await self._http.post("/v1/search", json=payload)
        response.raise_for_status()
        return [
            to_priced_trip(ZerolookTrip.model_validate(item), search)
            for item in response.json()["trips"]
        ]

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
