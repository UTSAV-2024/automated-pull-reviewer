import json
import uuid

import httpx
import psycopg
import pytest

from app.pipeline import run_review
from data.config import database_url
from data.db import apply_migrations

pytestmark = pytest.mark.asyncio

FAKE_DIFF = 'diff --git a/app.py b/app.py\n+cursor.execute(f"SELECT * FROM users WHERE id={user_id}")\n'

FINDING_RESPONSE = json.dumps(
    [
        {
            "severity": "HIGH",
            "category": "injection",
            "file": "app.py",
            "line": 2,
            "confidence": 0.9,
            "rationale": "user input reaches a raw SQL string",
        }
    ]
)


@pytest.fixture(scope="module")
def db_url():
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("DATABASE_URL not configured")
    apply_migrations(url)
    return url


async def test_full_pipeline_from_webhook_payload_to_posted_review(db_url):
    delivery_id = f"e2e-{uuid.uuid4()}"
    payload = json.dumps({"repository": {"full_name": "acme/widgets"}, "pull_request": {"number": 7}}).encode()

    async def fake_llm_call(system_prompt: str, user_content: str) -> str:
        return FINDING_RESPONSE

    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "/pulls/" in str(request.url):
            return httpx.Response(200, text=FAKE_DIFF)
        if request.method == "POST" and "/reviews" in str(request.url):
            posted["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"id": 1, "state": "COMMENTED"})
        return httpx.Response(404)

    conn = psycopg.connect(db_url, autocommit=True)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await run_review(
            None, delivery_id, payload, conn=conn, llm_call=fake_llm_call, github_client=client, github_token="gh-token"
        )

        with conn.cursor() as cur:
            cur.execute("SELECT status, confidence FROM reviews WHERE delivery_id = %s", (delivery_id,))
            status, confidence = cur.fetchone()
            cur.execute("SELECT count(*) FROM findings WHERE review_id = %s", (result["review_id"],))
            (finding_count,) = cur.fetchone()
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM reviews WHERE delivery_id = %s", (delivery_id,))  # cascades to findings
        conn.close()
        await client.aclose()

    # All 4 specialists returned one HIGH finding each; none are CRITICAL and
    # confidence (0.9) clears the default threshold -> auto-posted.
    assert result["decision"] == "auto_post"
    assert result["finding_count"] >= 1
    assert status == "posted"
    assert confidence == pytest.approx(0.9)
    assert finding_count == result["finding_count"]
    assert posted, "the review should have reached GitHub"
    assert len(posted["payload"]["comments"]) == result["finding_count"]


async def test_a_critical_finding_is_escalated_instead_of_posted(db_url):
    delivery_id = f"e2e-critical-{uuid.uuid4()}"
    payload = json.dumps({"repository": {"full_name": "acme/widgets"}, "pull_request": {"number": 8}}).encode()
    critical_response = json.dumps(
        [{"severity": "CRITICAL", "category": "injection", "file": "app.py", "line": 2, "confidence": 0.95, "rationale": "sql injection"}]
    )

    async def fake_llm_call(system_prompt: str, user_content: str) -> str:
        return critical_response

    posted = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "/pulls/" in str(request.url):
            return httpx.Response(200, text=FAKE_DIFF)
        if request.method == "POST" and "/reviews" in str(request.url):
            posted["called"] = True
            return httpx.Response(200, json={"id": 1})
        return httpx.Response(404)

    conn = psycopg.connect(db_url, autocommit=True)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await run_review(
            None, delivery_id, payload, conn=conn, llm_call=fake_llm_call, github_client=client, github_token="gh-token"
        )

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM hitl_queue WHERE review_id = %s", (result["review_id"],))
            (queue_count,) = cur.fetchone()
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM reviews WHERE delivery_id = %s", (delivery_id,))
        conn.close()
        await client.aclose()

    assert result["decision"] == "escalate"
    assert not posted, "a CRITICAL finding must never auto-post"
    assert queue_count == 1
