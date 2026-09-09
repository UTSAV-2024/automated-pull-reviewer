-- Extensions -------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Truth lane: relational review/finding/HITL rows -------------------------

CREATE TABLE IF NOT EXISTS reviews (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    delivery_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    confidence DOUBLE PRECISION,
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS findings (
    id BIGSERIAL PRIMARY KEY,
    review_id BIGINT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    agent_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    file_path TEXT NOT NULL,
    line_number INTEGER,
    confidence DOUBLE PRECISION NOT NULL,
    rationale TEXT NOT NULL,
    disputed BOOLEAN NOT NULL DEFAULT false,
    dispute_reason TEXT,
    disputed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hitl_queue (
    id BIGSERIAL PRIMARY KEY,
    review_id BIGINT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Memory lane: embedded code chunks for hybrid retrieval -------------------

CREATE TABLE IF NOT EXISTS code_chunks (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    file_path TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding VECTOR(256),
    search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repo, file_path, content_hash)
);

CREATE INDEX IF NOT EXISTS code_chunks_search_idx ON code_chunks USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS code_chunks_embedding_idx ON code_chunks USING diskann (embedding vector_cosine_ops);

-- Freshness table: which files need re-embedding ---------------------------

CREATE TABLE IF NOT EXISTS repo_file_index (
    repo TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    last_indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (repo, file_path)
);

-- Time lane: append-only agent events, partitioned by day ------------------

CREATE TABLE IF NOT EXISTS agent_events (
    id BIGSERIAL,
    review_id BIGINT,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    event_type TEXT NOT NULL,
    agent_type TEXT,
    cost_usd DOUBLE PRECISION,
    latency_ms INTEGER,
    confidence DOUBLE PRECISION,
    outcome TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
);

SELECT create_hypertable('agent_events', by_range('created_at', INTERVAL '1 day'), if_not_exists => TRUE);
