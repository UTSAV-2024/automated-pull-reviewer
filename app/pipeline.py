"""The ARQ job body: the whole review pipeline for one PR, from a queued
webhook payload to a posted (or human-queued/escalated) result. Wires
together every module built as its own bounded task."""

import json
import os
import time
import uuid

import httpx
import psycopg

from agents.anthropic_client import call_claude
from agents.base import SpecialistAgent
from agents.specialists import DOMAIN_PROMPTS
from core.hitl_gate import GateDecision, evaluate
from data.config import database_url
from observability.events import log_event
from orchestrator.aggregator import aggregate
from orchestrator.graph import build_graph
from reliability.budget_guard import BudgetGuard
from tools.github_client import post_review
from tools.retrieval.hybrid import hybrid_retrieve

CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.75"))
DAILY_BUDGET_CAP_USD = float(os.environ.get("DAILY_BUDGET_CAP_USD", "10.0"))

# ponytail: no embedding provider is wired in yet (an open assumption — see
# ASSUMPTION-51dccc33 and the SPEC.md open questions). Vector search is a
# no-op against a zero vector until an ingestion pipeline populates real
# embeddings; keyword search still works. Grounding quality is limited to
# whatever the repo's code_chunks table has been separately populated with.
_ZERO_EMBEDDING = [0.0] * 256


async def fetch_pr_diff(client: httpx.AsyncClient, owner: str, repo: str, pr_number: int, token: str) -> str:
    response = await client.get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3.diff"},
    )
    response.raise_for_status()
    return response.text


def _get_or_create_review(conn, repo: str, pr_number: int, delivery_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reviews (repo, pr_number, delivery_id) VALUES (%s, %s, %s)
            ON CONFLICT (delivery_id) DO UPDATE SET repo = EXCLUDED.repo
            RETURNING id
            """,
            (repo, pr_number, delivery_id),
        )
        return cur.fetchone()[0]


def _store_findings(conn, review_id: int, findings: list[dict]) -> None:
    with conn.cursor() as cur:
        for finding in findings:
            cur.execute(
                """
                INSERT INTO findings
                    (review_id, agent_type, severity, category, file_path, line_number, confidence, rationale)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    review_id,
                    finding["agent_type"],
                    finding["severity"],
                    finding["category"],
                    finding["file"],
                    finding.get("line"),
                    finding["confidence"],
                    finding["rationale"],
                ),
            )


def _log_agent_event(conn, review_id: int):
    def log(event: dict) -> None:
        event = dict(event)
        event_type = event.pop("event_type")
        agent_type = event.pop("agent_type", None)
        log_event(
            conn, span_id=f"agent-{uuid.uuid4()}", event_type=event_type,
            review_id=review_id, agent_type=agent_type, payload=event or None,
        )

    return log


def _build_specialists(conn, repo: str, review_id: int, raw_llm_call, budget_check) -> dict[str, SpecialistAgent]:
    log = _log_agent_event(conn, review_id)
    specialists = {}
    for name, prompt in DOMAIN_PROMPTS.items():

        async def retrieve(query: str, _name=name) -> list[dict]:
            chunks = hybrid_retrieve(conn, repo, query, _ZERO_EMBEDDING, top_k=5)
            log_event(conn, span_id=f"retrieval-{uuid.uuid4()}", event_type="retrieval", review_id=review_id, agent_type=_name)
            return chunks

        async def llm_call(system_prompt: str, user_content: str, _name=name) -> str:
            start = time.monotonic()
            text = await raw_llm_call(system_prompt, user_content)
            latency_ms = int((time.monotonic() - start) * 1000)
            log_event(conn, span_id=f"llm-{uuid.uuid4()}", event_type="llm_call", review_id=review_id, agent_type=_name, latency_ms=latency_ms)
            return text

        specialists[name] = SpecialistAgent(
            name=name, domain_prompt=prompt, retrieve=retrieve, llm_call=llm_call, budget_check=budget_check, log_event=log,
        )
    return specialists


async def run_review(
    ctx,
    delivery_id: str,
    payload: bytes,
    *,
    conn=None,
    llm_call=None,
    github_client=None,
    github_token: str | None = None,
) -> dict:
    data = json.loads(payload)
    repo = data["repository"]["full_name"]
    owner, name = repo.split("/")
    pr_number = data["pull_request"]["number"]

    own_conn = conn is None
    conn = conn or psycopg.connect(database_url(), autocommit=True)
    own_client = github_client is None
    github_client = github_client or httpx.AsyncClient()
    github_token = github_token or os.environ.get("GITHUB_TOKEN", "")
    llm_call = llm_call or call_claude

    try:
        review_id = _get_or_create_review(conn, repo, pr_number, delivery_id)
        diff = await fetch_pr_diff(github_client, owner, name, pr_number, github_token)

        guard = BudgetGuard(conn, DAILY_BUDGET_CAP_USD)
        specialists = _build_specialists(conn, repo, review_id, llm_call, guard.check)
        graph = build_graph({agent_name: agent.run for agent_name, agent in specialists.items()})
        result = await graph.ainvoke({"diff": diff}, {"configurable": {"thread_id": f"review-{review_id}"}})

        aggregated = aggregate(result.get("findings", {}))
        _store_findings(conn, review_id, aggregated["findings"])
        decision = evaluate(aggregated["findings"], aggregated["confidence"], CONFIDENCE_THRESHOLD)

        with conn.cursor() as cur:
            if decision == GateDecision.AUTO_POST:
                await post_review(github_client, owner, name, pr_number, github_token, aggregated["findings"])
                cur.execute(
                    "UPDATE reviews SET status = 'posted', confidence = %s, posted_at = now() WHERE id = %s",
                    (aggregated["confidence"], review_id),
                )
            else:
                cur.execute(
                    "INSERT INTO hitl_queue (review_id, reason) VALUES (%s, %s)", (review_id, decision.value)
                )
                cur.execute(
                    "UPDATE reviews SET status = %s, confidence = %s WHERE id = %s",
                    (decision.value, aggregated["confidence"], review_id),
                )

        return {"review_id": review_id, "decision": decision.value, "finding_count": len(aggregated["findings"])}
    finally:
        if own_conn:
            conn.close()
        if own_client:
            await github_client.aclose()
