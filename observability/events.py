import json


def log_event(
    conn,
    span_id: str,
    event_type: str,
    review_id: int | None = None,
    parent_span_id: str | None = None,
    agent_type: str | None = None,
    cost_usd: float | None = None,
    latency_ms: int | None = None,
    confidence: float | None = None,
    outcome: str | None = None,
    payload: dict | None = None,
) -> None:
    """Append one row to agent_events. Append-only: never updates or deletes
    an existing row — the audit trail depends on that."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_events
                (review_id, span_id, parent_span_id, event_type, agent_type,
                 cost_usd, latency_ms, confidence, outcome, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                review_id,
                span_id,
                parent_span_id,
                event_type,
                agent_type,
                cost_usd,
                latency_ms,
                confidence,
                outcome,
                json.dumps(payload) if payload is not None else None,
            ),
        )


def reconstruct_review(conn, review_id: int) -> list[dict]:
    """Every event for one review, ordered by time: what the trace viewer and
    audit trail both read."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT span_id, parent_span_id, event_type, agent_type, cost_usd,
                   latency_ms, confidence, outcome, payload, created_at
            FROM agent_events
            WHERE review_id = %s
            ORDER BY created_at
            """,
            (review_id,),
        )
        columns = [desc.name for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def grounding_was_used(conn, review_id: int, agent_type: str) -> bool:
    """Verify — not just assert — that a specialist's LLM call was grounded:
    a retrieval event for that agent/review must be on record alongside its
    llm_call event (AC-6)."""
    events = [event for event in reconstruct_review(conn, review_id) if event["agent_type"] == agent_type]
    has_retrieval = any(event["event_type"] == "retrieval" for event in events)
    has_llm_call = any(event["event_type"] == "llm_call" for event in events)
    return has_retrieval and has_llm_call
