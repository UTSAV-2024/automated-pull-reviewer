import uuid

import psycopg
import pytest

from data.config import database_url
from data.db import apply_migrations
from reliability.budget_guard import BudgetGuard


@pytest.fixture(scope="module")
def db_url():
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("DATABASE_URL not configured")
    apply_migrations(url)
    return url


@pytest.fixture
def conn_with_spend(db_url):
    span_prefix = f"test-budget-{uuid.uuid4()}"
    with psycopg.connect(db_url, autocommit=True) as connection:
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_events (span_id, event_type, cost_usd)
                VALUES (%s, 'llm_call', 2.50), (%s, 'llm_call', 1.50)
                """,
                (f"{span_prefix}-1", f"{span_prefix}-2"),
            )
        yield connection
        with connection.cursor() as cur:
            cur.execute("DELETE FROM agent_events WHERE span_id LIKE %s", (f"{span_prefix}%",))


def test_spend_today_sums_todays_costs(conn_with_spend):
    guard = BudgetGuard(conn_with_spend, daily_cap_usd=100)

    assert guard.spend_today() == pytest.approx(4.00)


def test_check_allows_calls_under_the_cap(conn_with_spend):
    guard = BudgetGuard(conn_with_spend, daily_cap_usd=10.0)

    assert guard.check() is True


def test_check_hard_blocks_once_cap_is_reached(conn_with_spend):
    guard = BudgetGuard(conn_with_spend, daily_cap_usd=4.00)

    assert guard.check() is False


def test_check_is_usable_as_a_specialist_budget_check_callable(conn_with_spend):
    guard = BudgetGuard(conn_with_spend, daily_cap_usd=4.00)
    budget_check = guard.check  # bound method matches agents.base.BudgetCheckFn's () -> bool

    assert callable(budget_check)
    assert budget_check() is False
