"""Exceptions raised by flightkit."""


class FlightkitError(Exception):
    """Base class for all flightkit errors."""


class TooManySearchesError(FlightkitError, ValueError):
    """A query would expand into more searches than allowed."""

    def __init__(self, count: int, limit: int) -> None:
        self.count = count
        self.limit = limit
        super().__init__(f"query expands to {count} searches, limit is {limit}")


class ProviderError(FlightkitError):
    """Something went wrong while talking to a fare provider."""

    retryable: bool = False

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


class ProviderUnavailableError(ProviderError):
    """The provider couldn't be reached, or didn't answer in time."""

    retryable = True


class ProviderStatusError(ProviderError):
    """The provider answered with an error status."""

    def __init__(self, message: str, *, provider: str, status_code: int) -> None:
        super().__init__(message, provider=provider)
        self.status_code = status_code
        self.retryable = status_code >= 500


class AuthenticationError(ProviderStatusError):
    """The provider rejected the API key (401 or 403)."""


class RateLimitedError(ProviderStatusError):
    """The provider is rate limiting us (429)."""

    def __init__(
        self, message: str, *, provider: str, status_code: int, retry_after: float | None
    ) -> None:
        super().__init__(message, provider=provider, status_code=status_code)
        self.retry_after = retry_after
        self.retryable = True


class InvalidResponseError(ProviderError):
    """The provider answered, but not in the format we expect."""
