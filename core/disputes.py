# ponytail: threshold is a raw dispute count, not a rate; tune once real
# dispute volume exists to judge what's actually noisy vs. a real pattern.
MINIMUM_EVIDENCE_THRESHOLD = 3


def record_dispute(conn, finding_id: int, reason: str) -> None:
    """Mark a posted finding as disputed and record the developer's reason.
    Disputes are recorded immediately; they do not immediately change agent
    behavior (see has_enough_evidence_to_act)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE findings SET disputed = true, dispute_reason = %s, disputed_at = now() WHERE id = %s",
            (reason, finding_id),
        )


def dispute_rate(conn, agent_type: str) -> float:
    """Fraction of an agent's findings that have been disputed."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE disputed), count(*) FROM findings WHERE agent_type = %s",
            (agent_type,),
        )
        disputed, total = cur.fetchone()
        return disputed / total if total else 0.0


def has_enough_evidence_to_act(conn, agent_type: str) -> bool:
    """Minimum evidence threshold before disputes influence future behavior —
    a defense against feedback-loop poisoning: a couple of noisy disputes
    must not retrain anything."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM findings WHERE agent_type = %s AND disputed", (agent_type,))
        (disputed_count,) = cur.fetchone()
        return disputed_count >= MINIMUM_EVIDENCE_THRESHOLD
