# Flightkit

Python SDK that orchestrates flight-price APIs (starting with [Zerolook](https://www.zerolook.ai/)):
fan-out (one request → many concurrent searches), caching, and a confidence-based fallback to live fares.

Unofficial — not affiliated with Zerolook.

## How a search flows

```mermaid
%%{init: {"flowchart": {"wrappingWidth": 320}}}%%
flowchart TD
    dev["<b>Developer or AI agent</b><br/>engine.search_trips(TripQuery) · POST /trips"]
    validate["<b>Validate TripQuery</b><br/>bad input → 422"]
    expand["<b>Expand</b><br/>1 query → N concrete searches · max 500"]

    subgraph per ["For each search, concurrently"]
        cache{"<b>Cache</b><br/>fresh result?"}
        coalesce["<b>Coalesce</b><br/>same search in flight? share one call"]
        fanout["<b>Fan-out</b><br/>max 10 in flight"]
        client["<b>Zerolook client</b><br/>map · POST · retry · timeout"]
        api[("Zerolook API")]
        parse["<b>Parse + validate</b><br/>ZerolookTrip → PricedTrip"]
        conf["<b>Confidence check</b><br/>below 0.8 → live fare"]
        live[("Live fares")]
        write["<b>Write back to cache</b>"]
        failed["<b>Failed search</b><br/>reported, never cached"]
    end

    merge["<b>Merge + sort</b><br/>per currency · price, stops, confidence, date"]
    result["<b>Result</b><br/>trips · cheapest per destination · calendar · failures · stats"]

    dev --> validate --> expand --> cache
    cache -- miss --> coalesce --> fanout --> client
    client <--> api
    client --> parse --> conf --> write
    conf -.-> live
    client -. "timeout / 5xx after retries" .-> failed
    cache -- hit --> merge
    write --> merge
    failed --> merge
    merge --> result

    classDef core fill:#b2f2bb,stroke:#2b8a3e,color:#000
    classDef adapter fill:#d0bfff,stroke:#5f3dc4,color:#000
    classDef external fill:#ff8787,stroke:#c92a2a,color:#000
    classDef planned fill:#e9ecef,stroke:#868e96,stroke-dasharray: 5 5,color:#495057
    classDef failure fill:#ffc9c9,stroke:#c92a2a,color:#000
    classDef output fill:#ffd43b,stroke:#e67700,color:#000

    class dev,validate,expand,cache,coalesce,fanout,write,merge core
    class client,parse adapter
    class api external
    class conf,live planned
    class failed failure
    class result output
```

Green: core (pure orchestration) · purple: Zerolook adapter · red: external API ·
dashed grey: planned, waiting on Zerolook's API docs.

## Install

```bash
pip install flightkit            # library only (httpx + pydantic)
pip install "flightkit[api]"     # + FastAPI wrapper
pip install "flightkit[mcp]"     # + MCP server
pip install "flightkit[all]"     # everything
```

## Layout

```
src/flightkit/
  core/         pure logic — no I/O, no FastAPI, no adapters imports
  adapters/     implementations of core ports that call external services
  entrypoints/  optional doors (FastAPI, MCP) that call into core
```

Dependencies point inward: `entrypoints → core ← adapters`. `tests/test_architecture.py` enforces it.

## Development

```bash
uv sync                  # base install + dev tools (no extras)
uv sync --extra all      # with FastAPI + MCP
uv run pytest -v
uv run ruff check . && uv run ruff format .
uv run mypy
uv build                 # sdist + wheel into dist/
```

Pre-commit hooks: `uv run pre-commit install` once per clone.
