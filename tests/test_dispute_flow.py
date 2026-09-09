import uuid

import psycopg
import pytest

from core.disputes import MINIMUM_EVIDENCE_THRESHOLD, dispute_rate, has_enough_evidence_to_act, record_dispute
from data.config import database_url
from data.db import apply_migrations

AGENT_TYPE = "security-dispute-test"


@pytest.fixture(scope="module")
def db_url():
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("DATABASE_URL not configured")
    apply_migrations(url)
    return url


@pytest.fixture
def conn(db_url):
    with psycopg.connect(db_url, autocommit=True) as connection:
        yield connection


@pytest.fixture
def findings(conn):
    """Insert a review with 4 findings from AGENT_TYPE; return their ids."""
    delivery_id = f"test-dispute-{uuid.uuid4()}"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO reviews (repo, pr_number, delivery_id) VALUES ('acme/widgets', 1, %s) RETURNING id",
            (delivery_id,),
        )
        review_id = cur.fetchone()[0]
        ids = []
        for i in range(4):
            cur.execute(
                """
                INSERT INTO findings (review_id, agent_type, severity, category, file_path, confidence, rationale)
                VALUES (%s, %s, 'HIGH', 'injection', %s, 0.8, 'r')
                RETURNING id
                """,
                (review_id, AGENT_TYPE, f"file{i}.py"),
            )
            ids.append(cur.fetchone()[0])
    yield ids
    with conn.cursor() as cur:
        cur.execute("DELETE FROM reviews WHERE id = %s", (review_id,))  # cascades to findings


def test_record_dispute_flags_the_finding(conn, findings):
    record_dispute(conn, findings[0], reason="this is a false positive")

    with conn.cursor() as cur:
        cur.execute("SELECT disputed, dispute_reason, disputed_at FROM findings WHERE id = %s", (findings[0],))
        disputed, reason, disputed_at = cur.fetchone()
        assert disputed is True
        assert reason == "this is a false positive"
        assert disputed_at is not None


def test_dispute_rate_reflects_disputed_fraction(conn, findings):
    record_dispute(conn, findings[0], reason="r1")
    record_dispute(conn, findings[1], reason="r2")

    assert dispute_rate(conn, AGENT_TYPE) == pytest.approx(0.5)


def test_not_enough_evidence_below_threshold(conn, findings):
    for finding_id in findings[: MINIMUM_EVIDENCE_THRESHOLD - 1]:
        record_dispute(conn, finding_id, reason="r")

    assert has_enough_evidence_to_act(conn, AGENT_TYPE) is False


def test_enough_evidence_once_threshold_is_reached(conn, findings):
    for finding_id in findings[:MINIMUM_EVIDENCE_THRESHOLD]:
        record_dispute(conn, finding_id, reason="r")

    assert has_enough_evidence_to_act(conn, AGENT_TYPE) is True
