import random

import psycopg
import pytest

from data.config import database_url
from data.db import apply_migrations
from observability.events import grounding_was_used, log_event, reconstruct_review


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
def review_id():
    # No FK constraint on agent_events.review_id; a random large id keeps
    # each test isolated without needing a real reviews row.
    return random.randint(10_000_000, 99_999_999)


@pytest.fixture(autouse=True)
def cleanup(conn, review_id):
    yield
    with conn.cursor() as cur:
        cur.execute("DELETE FROM agent_events WHERE review_id = %s", (review_id,))


def test_a_review_is_fully_reconstructable_in_order(conn, review_id):
    log_event(conn, span_id="s1", event_type="retrieval", review_id=review_id, agent_type="security")
    log_event(conn, span_id="s2", event_type="llm_call", review_id=review_id, agent_type="security", cost_usd=0.02)
    log_event(conn, span_id="s3", event_type="completed", review_id=review_id, agent_type="security", confidence=0.9)

    events = reconstruct_review(conn, review_id)

    assert [event["event_type"] for event in events] == ["retrieval", "llm_call", "completed"]
    assert events[1]["cost_usd"] == 0.02
    assert events[2]["confidence"] == 0.9


def test_reconstruct_review_only_returns_that_reviews_events(conn, review_id):
    other_review_id = review_id + 1
    log_event(conn, span_id="s1", event_type="retrieval", review_id=review_id, agent_type="security")
    log_event(conn, span_id="s2", event_type="retrieval", review_id=other_review_id, agent_type="quality")

    events = reconstruct_review(conn, review_id)

    assert len(events) == 1
    assert events[0]["agent_type"] == "security"

    # tidy up the extra review's row too, outside the fixture's scope
    with conn.cursor() as cur:
        cur.execute("DELETE FROM agent_events WHERE review_id = %s", (other_review_id,))


def test_grounding_was_used_is_true_when_retrieval_precedes_the_llm_call(conn, review_id):
    log_event(conn, span_id="s1", event_type="retrieval", review_id=review_id, agent_type="docs")
    log_event(conn, span_id="s2", event_type="llm_call", review_id=review_id, agent_type="docs")

    assert grounding_was_used(conn, review_id, "docs") is True


def test_grounding_was_used_is_false_when_llm_call_has_no_retrieval_on_record(conn, review_id):
    log_event(conn, span_id="s1", event_type="llm_call", review_id=review_id, agent_type="docs")

    assert grounding_was_used(conn, review_id, "docs") is False
