import os
from pathlib import Path


def load_env(env_path: str = ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines). No external dependency needed for one variable."""
    path = Path(env_path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def database_url() -> str:
    load_env()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (checked environment and .env)")
    return url
