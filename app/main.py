"""The runnable FastAPI app: GitHub webhook in, review job queued out.
`app/worker.py` is the ARQ process that actually processes the queue."""

import os
from contextlib import asynccontextmanager

from data.config import load_env

load_env()  # must run before importing webhook_receiver.main, which reads WEBHOOK_SECRET at import time

from fastapi import FastAPI  # noqa: E402

from app.webhook_receiver.main import create_app  # noqa: E402
from app.webhook_receiver.queue import make_dedupe_and_enqueue  # noqa: E402

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

_dedupe_and_enqueue = None


async def _dispatch(delivery_id: str, payload: bytes) -> bool:
    return await _dedupe_and_enqueue(delivery_id, payload)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _dedupe_and_enqueue
    _dedupe_and_enqueue = await make_dedupe_and_enqueue(REDIS_URL)
    yield


app: FastAPI = create_app(_dispatch)
app.router.lifespan_context = lifespan


@app.get("/health")
async def health():
    return {"status": "ok"}
