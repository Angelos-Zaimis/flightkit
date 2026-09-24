"""Local stand-in for the Zerolook API, for manual testing.

Run with:
    uv run --with fastapi --with uvicorn python scripts/fake_zerolook.py
"""

import asyncio
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI(title="Fake Zerolook")

LATENCY = 0.5


@app.post("/v1/search")
async def search(request: Request) -> dict:
    body = await request.json()
    print("received:", body, flush=True)
    await asyncio.sleep(LATENCY)

    now = datetime.now(timezone.utc).isoformat()
    return {
        "trips": [
            {
                "fareAmt": "129.99",
                "cur": "eur",
                "airline": " LX",
                "conf": 0.87,
                "stops": 0,
                "url": "https://example.com/book/1",
                "ts": now,
            },
            {
                "fareAmt": "98.50",
                "cur": "EUR",
                "airline": "A3",
                "conf": 0.62,
                "stops": 1,
                "url": "https://example.com/book/2",
                "ts": now,
                "extraField": "ignored by ZerolookTrip",
            },
        ]
    }


if __name__ == "__main__":
    uvicorn.run(app, port=9000)
