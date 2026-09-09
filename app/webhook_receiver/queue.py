from arq import create_pool
from arq.connections import RedisSettings

from .main import DedupeAndEnqueue

SEEN_KEY_PREFIX = "webhook:seen:"
# ponytail: Redis-only idempotency window, not a durable ledger row. Raise or
# move to a durable table if a delivery could plausibly retry after this TTL.
SEEN_TTL_SECONDS = 24 * 60 * 60


async def make_dedupe_and_enqueue(redis_url: str) -> DedupeAndEnqueue:
    pool = await create_pool(RedisSettings.from_dsn(redis_url))

    async def dedupe_and_enqueue(delivery_id: str, payload: bytes) -> bool:
        newly_seen = await pool.set(SEEN_KEY_PREFIX + delivery_id, "1", nx=True, ex=SEEN_TTL_SECONDS)
        if not newly_seen:
            return False
        await pool.enqueue_job("run_review", delivery_id, payload)
        return True

    return dedupe_and_enqueue
