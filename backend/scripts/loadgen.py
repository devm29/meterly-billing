"""Hammer the batch ingestion endpoint and report throughput and latency.

Example: python scripts/loadgen.py --events 200000 --batch 500 --concurrency 16 --dup-rate 0.05
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from meterly.config import DEV_ADMIN_KEY


def make_event(customer: str, rng: random.Random) -> dict[str, Any]:
    tokens = int(rng.lognormvariate(9.5, 0.6))
    return {
        "transaction_id": f"lg_{uuid.uuid4().hex}",
        "customer_id": customer,
        "code": "llm.completion",
        "timestamp": (datetime.now(UTC) - timedelta(seconds=rng.randint(0, 3600))).isoformat(),
        "properties": {
            "model": rng.choice(["claude-sonnet-4-5", "claude-haiku-4-5"]),
            "end_user_id": f"u_{rng.randint(1, 5000)}",
            "usage": {"total_tokens": tokens},
        },
    }


async def worker(
    client: httpx.AsyncClient,
    queue: asyncio.Queue[list[dict[str, Any]]],
    latencies: list[float],
    totals: dict[str, int],
) -> None:
    while True:
        try:
            batch = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        started = time.perf_counter()
        response = await client.post("/v1/events/batch", json={"events": batch})
        latencies.append((time.perf_counter() - started) * 1000)
        if response.status_code != 202:
            totals["errors"] += 1
            continue
        body = response.json()
        for key in ("accepted", "duplicates", "rejected"):
            totals[key] += body[key]


async def run(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    headers = {"x-api-key": args.api_key}
    async with httpx.AsyncClient(base_url=args.api, timeout=60, headers=headers) as client:
        page = (await client.get("/v1/customers", params={"limit": 100})).json()
        customers = [
            c["external_id"] for c in page["items"] if c["status"] in {"active", "trialing"}
        ]
        if not customers:
            raise SystemExit("no active customers; run the seed first")

        queue: asyncio.Queue[list[dict[str, Any]]] = asyncio.Queue()
        sent: list[dict[str, Any]] = []
        produced = 0
        while produced < args.events:
            size = min(args.batch, args.events - produced)
            batch = []
            for _ in range(size):
                if sent and rng.random() < args.dup_rate:
                    batch.append(rng.choice(sent))
                else:
                    event = make_event(rng.choice(customers), rng)
                    sent.append(event)
                    batch.append(event)
            queue.put_nowait(batch)
            produced += size

        latencies: list[float] = []
        totals = {"accepted": 0, "duplicates": 0, "rejected": 0, "errors": 0}
        started = time.perf_counter()
        await asyncio.gather(
            *(worker(client, queue, latencies, totals) for _ in range(args.concurrency))
        )
        elapsed = time.perf_counter() - started

    ordered = sorted(latencies)
    p95 = ordered[int(len(ordered) * 0.95) - 1] if ordered else 0.0
    print(f"events     {args.events:,} in {elapsed:.1f}s  ({args.events / elapsed:,.0f} events/s)")
    print(f"batches    {len(latencies)} x {args.batch}, concurrency {args.concurrency}")
    p50 = statistics.median(ordered)
    print(f"latency    p50 {p50:.0f} ms   p95 {p95:.0f} ms   max {ordered[-1]:.0f} ms")
    print(
        f"results    accepted {totals['accepted']:,}  duplicates {totals['duplicates']:,}  "
        f"rejected {totals['rejected']:,}  http errors {totals['errors']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8107")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("METERLY_ADMIN_API_KEY", DEV_ADMIN_KEY),
        help="admin key: the run lists customers before it ingests",
    )
    parser.add_argument("--events", type=int, default=50_000)
    parser.add_argument("--batch", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--dup-rate", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=1)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
