"""Expand a search into concrete searches."""

from datetime import timedelta

from flightkit.errors import TooManySearchesError
from flightkit.models import Search, TripQuery

DEFAULT_MAX_SEARCHES = 500


def expand(query: TripQuery, *, max_searches: int = DEFAULT_MAX_SEARCHES) -> list[Search]:
    """Turn a TripQuery into every concrete Search it covers."""
    count = count_searches(query)
    if count > max_searches:
        raise TooManySearchesError(count, max_searches)

    searches: list[Search] = []
    for destination in query.destinations:
        for offset in range(_days(query)):
            depart = query.depart_from + timedelta(days=offset)
            for nights in _night_options(query):
                searches.append(
                    Search(
                        origin=query.origin,
                        destination=destination,
                        depart_date=depart,
                        return_date=None if nights is None else depart + timedelta(days=nights),
                        passengers=query.passengers,
                        cabin=query.cabin,
                    )
                )
    return searches


def count_searches(query: TripQuery) -> int:
    return len(query.destinations) * _days(query) * len(_night_options(query))


def _days(query: TripQuery) -> int:
    return (query.depart_to - query.depart_from).days + 1


def _night_options(query: TripQuery) -> list[int | None]:
    if query.min_nights is None or query.max_nights is None:
        return [None]
    return list(range(query.min_nights, query.max_nights + 1))
