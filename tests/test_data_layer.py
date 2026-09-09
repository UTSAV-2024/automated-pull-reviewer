import psycopg
import pytest

from data.config import database_url
from data.db import apply_migrations

TABLES = ["reviews", "findings", "hitl_queue", "code_chunks", "repo_file_index", "agent_events"]


@pytest.fixture(scope="module")
def db_url():
    try:
        return database_url()
    except RuntimeError:
        pytest.skip("DATABASE_URL not configured")


@pytest.fixture(scope="module", autouse=True)
def migrated(db_url):
    apply_migrations(db_url)


def test_migrations_are_idempotent(db_url):
    # Running twice must not error and must not re-apply anything.
    assert apply_migrations(db_url) == []


@pytest.mark.parametrize("table", TABLES)
def test_table_exists(db_url, table):
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table,))
        assert cur.fetchone()[0] == table


def test_vector_and_timescale_extensions_are_enabled(db_url):
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'vectorscale', 'timescaledb')")
        assert {row[0] for row in cur.fetchall()} == {"vector", "vectorscale", "timescaledb"}


def test_agent_events_is_a_hypertable(db_url):
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_name = 'agent_events'")
        assert cur.fetchone() is not None


def test_code_chunks_has_vector_and_keyword_indexes(db_url):
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'code_chunks'")
        indexdefs = " ".join(row[1] for row in cur.fetchall())
        assert "diskann" in indexdefs
        assert "gin" in indexdefs.lower()
