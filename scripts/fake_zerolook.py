"""Local stand-in for the Zerolook API, for trying the HTTP API by hand.

Run with:
    uv run --with fastapi --with uvicorn python scripts/fake_zerolook.py

Prices come from the same generator as FakeZerolook, so they vary by destination,
weekday and length of stay, and the same search always returns the same trips.
"""

import asyncio
import random

import uvicorn
from fastapi import FastAPI, Request

from flightkit.adapters.zerolook.fake import fake_trips

app = FastAPI(title="Fake Zerolook")


@app.post("/v1/search")
async def search(request: Request) -> dict:
    body = await request.json()
    print("received:", body, flush=True)
    await asyncio.sleep(random.uniform(0.1, 0.4))
    return {"trips": fake_trips(body)}


if __name__ == "__main__":
    uvicorn.run(app, port=9000)
