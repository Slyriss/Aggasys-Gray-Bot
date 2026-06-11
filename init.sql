-- Extensions (must come first)
CREATE EXTENSION IF NOT EXISTS vector;

-- Conversation memory: stores last N messages per user
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Long-term memory: personal facts about specific users
CREATE TABLE IF NOT EXISTS user_memory (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    fact TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Company wiki: LLM-maintained structured knowledge pages
CREATE TABLE IF NOT EXISTS wiki_pages (
    id SERIAL PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT[] DEFAULT '{}',
    embedding vector(768),
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', title || ' ' || content)
    ) STORED,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Company-wide atomic facts mined from conversations (shared across users)
CREATE TABLE IF NOT EXISTS company_memory (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL DEFAULT 'general',
    fact TEXT NOT NULL,
    source_user_id BIGINT,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Quick-capture notes per user
CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_created_at ON conversations(telegram_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_memory_user ON user_memory(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_wiki_search ON wiki_pages USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_wiki_path ON wiki_pages(path);
CREATE INDEX IF NOT EXISTS idx_wiki_embedding ON wiki_pages USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_company_memory_embedding ON company_memory USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_company_memory_search ON company_memory USING gin(to_tsvector('english', fact));
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(telegram_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_embedding ON notes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_notes_search ON notes USING gin(to_tsvector('english', content));
