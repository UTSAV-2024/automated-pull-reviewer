import os

from arq.connections import RedisSettings

from app.pipeline import run_review
from data.config import load_env

load_env()

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


class WorkerSettings:
    functions = [run_review]
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
