import psycopg
import pytest

from data.config import database_url
from data.db import apply_migrations
from tools.retrieval.hybrid import hybrid_retrieve, keyword_search, reciprocal_rank_fusion, vector_search

REPO = "test-retrieval-repo"


def one_hot(index: int, dim: int = 256) -> list[float]:
    vec = [0.0] * dim
    vec[index] = 1.0
    return vec


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
        with connection.cursor() as cur:
            cur.execute("DELETE FROM code_chunks WHERE repo = %s", (REPO,))
            cur.execute(
                """
                INSERT INTO code_chunks (repo, file_path, chunk_text, content_hash, embedding)
                VALUES
                    (%s, 'math.py', 'def add(a, b): return a + b', 'h1', %s),
                    (%s, 'math.py', 'def subtract(a, b): return a - b', 'h2', %s),
                    (%s, 'README.md', 'installation instructions for the package', 'h3', %s)
                """,
                (
                    REPO, one_hot(0),
                    REPO, one_hot(1),
                    REPO, one_hot(2),
                ),
            )
        yield connection
        with connection.cursor() as cur:
            cur.execute("DELETE FROM code_chunks WHERE repo = %s", (REPO,))


def test_reciprocal_rank_fusion_combines_two_ranked_lists():
    vector_hits = [{"id": 1}, {"id": 2}, {"id": 3}]
    keyword_hits = [{"id": 2}, {"id": 3}]

    fused = reciprocal_rank_fusion(vector_hits, keyword_hits)

    # id 2 is ranked well in both lists (unlike 1 and 3, each strong in only
    # one) -> its combined reciprocal-rank score wins overall.
    assert fused[0]["id"] == 2
    assert {item["id"] for item in fused} == {1, 2, 3}


def test_vector_search_finds_the_nearest_embedding_regardless_of_keywords(conn):
    # Query embedding matches chunk 'subtract' exactly; query text mentions
    # neither "subtract" nor "add", proving this is pure vector similarity.
    results = vector_search(conn, REPO, one_hot(1), limit=3)

    assert results[0]["chunk_text"] == "def subtract(a, b): return a - b"


def test_keyword_search_finds_exact_identifier_matches(conn):
    results = keyword_search(conn, REPO, "subtract", limit=3)

    assert results
    assert results[0]["chunk_text"] == "def subtract(a, b): return a - b"


def test_hybrid_retrieve_fuses_vector_and_keyword_results(conn):
    results = hybrid_retrieve(conn, REPO, query="subtract", query_embedding=one_hot(1), top_k=3)

    # Both signals agree on the 'subtract' chunk, so it must rank first.
    assert results[0]["chunk_text"] == "def subtract(a, b): return a - b"
    assert len(results) <= 3
