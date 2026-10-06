"""HTTP client for the Zerolook API."""

import asyncio
import random
from typing import Any

import httpx
from typing_extensions import Self

from flightkit.adapters.zerolook.mapping import to_priced_trip, to_search_request
from flightkit.adapters.zerolook.wire import ZerolookTrip
from flightkit.models import PricedTrip, Search

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_DELAY = 10.0


class ZerolookClient:
    """Async client for the Zerolook search API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        max_connections: int = 10,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff: float = 0.5,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            limits=httpx.Limits(max_connections=max_connections),
            timeout=timeout,
        )
        self._max_retries = max_retries
        self._backoff = backoff

    async def search(self, search: Search) -> list[PricedTrip]:
        """Search Zerolook for trips matching `search`."""
        payload = to_search_request(search).model_dump(mode="json", exclude_none=True)
        response = await self._post("/v1/search", payload)
        return [
            to_priced_trip(ZerolookTrip.model_validate(item), search)
            for item in response.json()["trips"]
        ]

    async def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        attempt = 0
        while True:
            retry_after: float | None = None
            try:
                response = await self._http.post(path, json=payload)
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise
            else:
                if response.status_code not in RETRYABLE_STATUS or attempt >= self._max_retries:
                    response.raise_for_status()
                    return response
                retry_after = _retry_after_seconds(response)
            await asyncio.sleep(self._delay(attempt, retry_after))
            attempt += 1

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, MAX_DELAY)
        return random.uniform(0, min(MAX_DELAY, self._backoff * 2**attempt))

    async def aclose(self) -> None:
        """Close the underlying HTTP connections."""
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def _retry_after_seconds(response: httpx.Response) -> float | None:
    try:
        return max(0.0, float(response.headers["Retry-After"]))
    except (KeyError, ValueError):
        return None
