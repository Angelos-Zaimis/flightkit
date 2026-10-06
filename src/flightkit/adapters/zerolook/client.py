"""HTTP client for the Zerolook API."""

import asyncio
import random
from typing import Any

import httpx
from typing_extensions import Self

from flightkit.adapters.zerolook.mapping import to_priced_trip, to_search_request
from flightkit.adapters.zerolook.wire import ZerolookTrip
from flightkit.errors import (
    AuthenticationError,
    InvalidResponseError,
    ProviderStatusError,
    ProviderUnavailableError,
    RateLimitedError,
)
from flightkit.models import PricedTrip, Search

PROVIDER = "zerolook"

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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # `transport` swaps out the network layer, e.g. for a proxy or the in-memory
        # FakeZerolook. Without it, httpx uses a normal pooled connection.
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            limits=httpx.Limits(max_connections=max_connections),
            timeout=timeout,
            transport=transport,
        )
        self._max_retries = max_retries
        self._backoff = backoff

    async def search(self, search: Search) -> list[PricedTrip]:
        """Search Zerolook for trips matching `search`."""
        payload = to_search_request(search).model_dump(mode="json", exclude_none=True)
        response = await self._post("/v1/search", payload)
        try:
            return [
                to_priced_trip(ZerolookTrip.model_validate(item), search)
                for item in response.json()["trips"]
            ]
        except (ValueError, KeyError, TypeError) as e:
            raise InvalidResponseError(
                f"unexpected response from Zerolook: {e}", provider=PROVIDER
            ) from e

    async def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        attempt = 0
        while True:
            retry_after: float | None = None
            try:
                response = await self._http.post(path, json=payload)
            except httpx.TransportError as e:
                if attempt >= self._max_retries:
                    raise ProviderUnavailableError(
                        f"could not reach Zerolook: {e}", provider=PROVIDER
                    ) from e
            else:
                if response.status_code not in RETRYABLE_STATUS or attempt >= self._max_retries:
                    if response.is_error:
                        raise _status_error(response)
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


def _status_error(response: httpx.Response) -> ProviderStatusError:
    status = response.status_code
    message = f"Zerolook returned HTTP {status}"
    if status in (401, 403):
        return AuthenticationError(message, provider=PROVIDER, status_code=status)
    if status == 429:
        return RateLimitedError(
            message,
            provider=PROVIDER,
            status_code=status,
            retry_after=_retry_after_seconds(response),
        )
    return ProviderStatusError(message, provider=PROVIDER, status_code=status)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    try:
        return max(0.0, float(response.headers["Retry-After"]))
    except (KeyError, ValueError):
        return None
