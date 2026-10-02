"""Exceptions raised by flightkit."""


class FlightkitError(Exception):
    """Base class for all flightkit errors."""


class TooManySearchesError(FlightkitError, ValueError):
    """A query would expand into more searches than allowed."""

    def __init__(self, count: int, limit: int) -> None:
        self.count = count
        self.limit = limit
        super().__init__(f"query expands to {count} searches, limit is {limit}")
