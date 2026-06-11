-- Run this on an EXISTING installation to upgrade to the 2nd Brain schema.
-- Safe to run multiple times (all statements are idempotent).

CREATE EXTENSION IF NOT EXISTS vector;

-- Add vector embedding column to wiki_pages
ALTER TABLE wiki_pages ADD COLUMN IF NOT EXISTS embedding vector(768);

-- Drop old IVFFlat index if it exists, create HNSW instead
DROP INDEX IF EXISTS idx_wiki_embedding;
CREATE INDEX IF NOT EXISTS idx_wiki_embedding ON wiki_pages USING hnsw (embedding vector_cosine_ops);

-- Company-wide atomic facts
CREATE TABLE IF NOT EXISTS company_memory (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL DEFAULT 'general',
    fact TEXT NOT NULL,
    source_user_id BIGINT,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_company_memory_embedding ON company_memory USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_company_memory_search ON company_memory USING gin(to_tsvector('english', fact));

-- Quick-capture notes
CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(telegram_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_embedding ON notes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_notes_search ON notes USING gin(to_tsvector('english', content));
