"""FastAPI app. Requires the `api` extra.

Run locally against the fake Zerolook server:
    uv run --with fastapi --with uvicorn uvicorn flightkit.entrypoints.api:app --port 8001
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from flightkit.adapters.zerolook import ZerolookClient
from flightkit.core.engine import Engine
from flightkit.errors import TooManySearchesError
from flightkit.models import Search, SearchResult, TripQuery


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with ZerolookClient(
        base_url=os.environ.get("ZEROLOOK_BASE_URL", "http://localhost:9000"),
        api_key=os.environ.get("ZEROLOOK_API_KEY", "dev"),
    ) as client:
        app.state.engine = Engine(client)
        yield


app = FastAPI(title="Flightkit", lifespan=lifespan)


@app.post("/search")
async def search(searches: list[Search]) -> SearchResult:
    engine: Engine = app.state.engine
    return await engine.search_many(searches)


@app.post("/trips")
async def trips(query: TripQuery) -> SearchResult:
    engine: Engine = app.state.engine
    try:
        return await engine.search_trips(query)
    except TooManySearchesError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
