"""Hybrid retrieval over the code_chunks table: vector similarity search fused
with keyword full-text search via Reciprocal Rank Fusion (RRF).

# ponytail: embeddings are supplied by the caller (query_embedding), not
# computed here. Wire in a real embedding provider (e.g. an OpenAI or Voyage
# embedding call) at the call site once one is chosen; this module only owns
# the fusion/search logic, which is fully testable without one.
"""


def vector_search(conn, repo: str, query_embedding: list[float], limit: int = 10) -> list[dict]:
    """Nearest-neighbor code chunks by cosine distance. Good at meaning, weak at exact names."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, file_path, chunk_text, embedding <=> %s::vector AS distance
            FROM code_chunks
            WHERE repo = %s AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_embedding, repo, query_embedding, limit),
        )
        return [
            {"id": row[0], "file_path": row[1], "chunk_text": row[2], "distance": row[3]}
            for row in cur.fetchall()
        ]


def keyword_search(conn, repo: str, query: str, limit: int = 10) -> list[dict]:
    """Exact-identifier / keyword matches via Postgres full-text search. Good at exact
    strings, blind to meaning."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, file_path, chunk_text, ts_rank(search_vector, websearch_to_tsquery('english', %s)) AS rank
            FROM code_chunks
            WHERE repo = %s AND search_vector @@ websearch_to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT %s
            """,
            (query, repo, query, limit),
        )
        return [
            {"id": row[0], "file_path": row[1], "chunk_text": row[2], "rank": row[3]}
            for row in cur.fetchall()
        ]


def reciprocal_rank_fusion(*ranked_lists: list[dict], k: int = 60) -> list[dict]:
    """Fuse multiple ranked result lists (matched by 'id') into one ranking via RRF."""
    scores: dict[int, float] = {}
    chunks: dict[int, dict] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item["id"]] = scores.get(item["id"], 0.0) + 1.0 / (k + rank)
            chunks[item["id"]] = item
    ordered_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [{**chunks[cid], "rrf_score": scores[cid]} for cid in ordered_ids]


def hybrid_retrieve(conn, repo: str, query: str, query_embedding: list[float], top_k: int = 10) -> list[dict]:
    """Fetch the top-k code chunks relevant to a diff/query, fusing vector and keyword search."""
    vector_hits = vector_search(conn, repo, query_embedding, limit=top_k)
    keyword_hits = keyword_search(conn, repo, query, limit=top_k)
    fused = reciprocal_rank_fusion(vector_hits, keyword_hits)
    return fused[:top_k]
