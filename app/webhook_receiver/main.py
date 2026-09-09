import os
from typing import Awaitable, Callable

from fastapi import FastAPI, Header, HTTPException, Request

from .signature import verify_signature

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

# True if this delivery was newly enqueued, False if it was a duplicate.
DedupeAndEnqueue = Callable[[str, bytes], Awaitable[bool]]


def create_app(dedupe_and_enqueue: DedupeAndEnqueue) -> FastAPI:
    app = FastAPI()

    @app.post("/webhooks/github")
    async def receive_webhook(
        request: Request,
        x_hub_signature_256: str | None = Header(default=None),
        x_github_delivery: str | None = Header(default=None),
        x_github_event: str | None = Header(default=None),
    ):
        body = await request.body()
        if not verify_signature(body, x_hub_signature_256, WEBHOOK_SECRET):
            raise HTTPException(status_code=401, detail="invalid signature")
        if not x_github_delivery:
            raise HTTPException(status_code=400, detail="missing delivery id")
        if x_github_event != "pull_request":
            return {"status": "ignored"}

        enqueued = await dedupe_and_enqueue(x_github_delivery, body)
        return {"status": "accepted" if enqueued else "duplicate"}

    return app
