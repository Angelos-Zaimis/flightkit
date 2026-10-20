# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/). Until 1.0, minor versions may include breaking
changes.

## [Unreleased]

### Added

- MCP server (`flightkit[mcp]`, run as `flightkit-mcp`) with two read-only tools:
  `search_trips`, which returns a compact summary of the cheapest trips, and `estimate_search`,
  which reports how many searches a query needs. Without `ZEROLOOK_API_KEY` it uses simulated
  prices and marks every answer as simulated.

## [0.1.0] - 2026-10-06

First release.

### Added

- `TripQuery` for flexible searches: several destinations, a departure window of up to 60 days
  and an optional range of nights. Queries that would expand into more than 500 searches are
  refused before any provider call.
- `Engine.search_trips` and `Engine.search_many`, which run searches concurrently under a
  shared concurrency limit and report failed searches instead of failing the whole request.
- `MemoryCache` with a TTL and LRU eviction, plus a `Cache` protocol for other backends.
- Request coalescing: identical searches already in flight share a single provider call.
- Ranked results per currency, with the cheapest trip per destination, a cheapest-per-day
  calendar and per-request stats.
- `ZerolookClient` with retries (exponential backoff with jitter, `Retry-After` support),
  timeouts and a connection limit. The Zerolook request and response fields are placeholders
  until the API is publicly documented.
- Error hierarchy under `FlightkitError`. Provider failures raise a `ProviderError` subclass,
  and each failure says whether retrying may help.
- `FakeZerolook`, an in-memory simulation of the Zerolook API for demos and tests, and a
  runnable demo in `examples/demo.py`.
- Optional FastAPI app (`flightkit[api]`) with `POST /trips` and `POST /search`.
- Top-level public API: `from flightkit import Engine, TripQuery, ...`.

[Unreleased]: https://github.com/Angelos-Zaimis/flightkit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Angelos-Zaimis/flightkit/releases/tag/v0.1.0
