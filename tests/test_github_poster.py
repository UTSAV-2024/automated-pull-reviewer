import httpx
import pytest

from tools.github_client import post_review

pytestmark = pytest.mark.asyncio

FINDING = {
    "agent_type": "security",
    "severity": "HIGH",
    "category": "injection",
    "file": "app.py",
    "line": 42,
    "confidence": 0.9,
    "rationale": "user input reaches a raw SQL string",
}


def make_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_post_review_sends_findings_as_inline_comments():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 1, "state": "COMMENTED"})

    async with make_client(handler) as client:
        result = await post_review(client, "acme", "widgets", 42, "gh-token", [FINDING])

    assert captured["url"] == "https://api.github.com/repos/acme/widgets/pulls/42/reviews"
    assert captured["auth"] == "Bearer gh-token"
    assert captured["payload"]["event"] == "COMMENT"
    assert captured["payload"]["comments"] == [
        {
            "path": "app.py",
            "line": 42,
            "body": "**[HIGH] injection** (security, confidence 0.90)\n\nuser input reaches a raw SQL string",
        }
    ]
    assert result == {"id": 1, "state": "COMMENTED"}


async def test_finding_without_a_line_falls_back_to_line_one():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 1})

    docs_finding = {**FINDING, "line": None, "agent_type": "docs", "category": "missing-docstring"}

    async with make_client(handler) as client:
        await post_review(client, "acme", "widgets", 1, "gh-token", [docs_finding])

    assert captured["payload"]["comments"][0]["line"] == 1


async def test_a_github_error_response_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "Validation Failed"})

    async with make_client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await post_review(client, "acme", "widgets", 1, "gh-token", [FINDING])
