"""Simulated Zerolook API for demos and tests. No network or API key needed.

    fake = FakeZerolook()
    client = ZerolookClient("https://zerolook.test", "any-key", transport=fake.transport())

Prices are deterministic: the same search always returns the same trips, the way a real
API would within a short window. With `chaos=True` some requests fail with 429 or 503,
so retries and partial results show up too.
"""

import asyncio
import hashlib
import json
import random
from datetime import date, datetime, timezone
from typing import Any

import httpx

# Multipliers by weekday, Monday first. Midweek is cheapest, Friday and Sunday dearest.
WEEKDAY_FACTOR = (1.0, 0.82, 0.86, 0.98, 1.22, 1.08, 1.27)
CABIN_FACTOR = {"economy": 1.0, "premium_economy": 1.7, "business": 3.2, "first": 5.5}
CARRIERS = ("LX", "A3", "OA", "EW", "U2", "FR", "TP", "KL")


def fake_trips(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a believable, deterministic Zerolook response body for one search request."""
    # Route and dates decide the fare; passengers and cabin only scale it.
    route = {key: request.get(key) for key in ("orig", "dest", "departDate", "returnDate")}
    rng = random.Random(_digest(route))
    destination_rng = random.Random(_digest({"dest": request["dest"]}))

    depart = date.fromisoformat(request["departDate"])
    base = 70 + destination_rng.random() * 110
    price = base * WEEKDAY_FACTOR[depart.weekday()] * rng.uniform(0.85, 1.15)

    if request.get("returnDate"):
        nights = (date.fromisoformat(request["returnDate"]) - depart).days
        price *= 1.7 + 0.03 * nights
    price *= CABIN_FACTOR.get(request.get("cabin", "economy"), 1.0) * request.get("pax", 1)

    now = datetime.now(timezone.utc).isoformat()
    carriers = rng.sample(CARRIERS, 3)
    options = [(0, 1.0), (1, 0.84)] + ([(2, 0.76)] if rng.random() < 0.4 else [])
    return [
        {
            "fareAmt": f"{price * factor:.2f}",
            "cur": "EUR",
            "airline": carrier,
            "conf": round(rng.uniform(0.55, 0.97), 2),
            "stops": stops,
            "url": f"https://example.com/book/{_digest(request)[:12]}-{stops}",
            "ts": now,
        }
        for (stops, factor), carrier in zip(options, carriers[: len(options)], strict=True)
    ]


class FakeZerolook:
    """In-memory stand-in for the Zerolook API, used through an httpx transport."""

    def __init__(
        self,
        *,
        chaos: bool = True,
        latency: tuple[float, float] = (0.05, 0.3),
        seed: int = 0,
    ) -> None:
        self.chaos = chaos
        self.latency = latency
        self.requests = 0
        self.errors = 0
        self._rng = random.Random(seed)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        await asyncio.sleep(self._rng.uniform(*self.latency))

        if self.chaos:
            roll = self._rng.random()
            if roll < 0.05:
                self.errors += 1
                return httpx.Response(429, headers={"Retry-After": "0"})
            if roll < 0.08:
                self.errors += 1
                return httpx.Response(503)

        if request.url.path != "/v1/search" or request.method != "POST":
            return httpx.Response(404)
        return httpx.Response(200, json={"trips": fake_trips(json.loads(request.content))})


def _digest(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
