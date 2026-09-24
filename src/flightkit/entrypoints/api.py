"""FastAPI app. Requires the `api` extra.

Run locally against the fake Zerolook server:
    uv run --with fastapi --with uvicorn uvicorn flightkit.entrypoints.api:app --port 8001
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from flightkit.adapters.zerolook import ZerolookClient
from flightkit.core.engine import Engine
from flightkit.models import Search, SearchResult


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
